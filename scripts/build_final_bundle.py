"""Assemble a local, auditable source/demo/DS bundle; never publish or submit it."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from urllib.parse import urlsplit, urlunsplit
from backend.handoff.install import install
from backend.handoff.store import load_snapshot


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle_readme(source):
    """Keep local Markdown links valid after copying the guide to the bundle root."""
    def rebase(match):
        target = match.group(1)
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or not parts.path or parts.path.startswith('/'):
            return match.group(0)
        path = posixpath.normpath('tram-forecast/docs/submission-final/' + parts.path)
        return '](' + urlunsplit(parts._replace(path=path)) + ')'
    return re.sub(r'\]\(([^)]+)\)', rebase, source)


def additional_evidence(directory, output):
    """Copy an explicitly supplied, fully checksum-covered evidence directory."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Additional evidence must be a regular directory')
    root = directory.resolve()
    files = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        rel = PurePosixPath(name)
        path = root / rel
        if (rel.is_absolute() or '..' in rel.parts or '\\' in name or name in files
                or name == 'SHA256SUMS' or any(p.is_symlink() for p in [path, *path.parents] if p != root.parent)
                or not path.resolve().is_relative_to(root) or not path.is_file() or sha(path) != digest):
            raise ValueError(f'Invalid additional evidence: {name}')
        files[name] = path
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p != root / 'SHA256SUMS'}
    if not files or set(files) != actual:
        raise ValueError('Additional evidence must be nonempty and fully covered by SHA256SUMS')
    target_root = output / 'evidence/final-closure'
    if target_root.exists():
        raise ValueError('Additional evidence destination already exists')
    for name, path in files.items():
        target = target_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return {name: sha(path) for name, path in files.items()}


def runtime_hashes(archive):
    """Bind acceptance to every shipped non-document source, including assets."""
    with zipfile.ZipFile(archive) as source:
        return {n: hashlib.sha256(source.read(n)).hexdigest() for n in sorted(source.namelist())
                if not n.endswith(('/', '.md', '/MANIFEST.sha256'))
                and n != 'tram-forecast/docs/submission-final/source-allowlist.json'}


def accept_runtime(proof, archive, run_id):
    required = {'backend', 'integration', 'frontend_build', 'browser_chromium',
                'browser_webkit', 'clean_launch', 'api_csv', 'restart'}
    if (proof.get('status') != 'passed' or proof.get('run_id') != run_id
            or proof.get('runtime_sha256') != runtime_hashes(archive)
            or not required.issubset(proof.get('checks', {}))
            or any(proof['checks'][name] != 'passed' for name in required)):
        raise ValueError('Current runtime verification does not cover this source/run and required checks')


def supporting_files(directory, handoff, ds_csv, model_sha):
    """Reuse only checksum-covered local evidence tied to the same model and CSV."""
    root = directory.resolve()
    files = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        rel = PurePosixPath(name)
        path = root / rel
        if (rel.is_absolute() or '..' in rel.parts or '\\' in name or name in files
                or path.is_symlink() or not path.resolve().is_relative_to(root)
                or not path.is_file() or sha(path) != digest):
            raise ValueError(f'Invalid supporting bundle entry: {name}')
        files[name] = path
    for name in ('release-manifest.json', 'sources.zip', 'g0-b2.zip',
                 'demo-handoff.zip', 'ds-candidate.csv', 'local-acceptance.json'):
        if name not in files:
            raise ValueError(f'Supporting bundle is incomplete: {name}')
    previous = json.loads(files['release-manifest.json'].read_text())
    if (sha(files['demo-handoff.zip']) != sha(handoff)
            or sha(files['ds-candidate.csv']) != sha(ds_csv)
            or previous['demo']['model_sha256'] != model_sha
            or previous['g0']['archive_sha256'] != sha(files['g0-b2.zip'])):
        raise ValueError('Supporting bundle belongs to a different model/handoff/DS')
    with zipfile.ZipFile(files['g0-b2.zip']) as archive:
        roots = [n.removesuffix('bundle-manifest.json') for n in archive.namelist()
                 if n.endswith('/bundle-manifest.json')]
        if len(roots) != 1:
            raise ValueError('Expected one G0 bundle manifest')
        prefix = roots[0]
        for name, digest in (('model/model.joblib', model_sha), ('champion.csv', sha(ds_csv)),
                             ('handoff-b2.zip', sha(handoff))):
            if hashlib.sha256(archive.read(prefix + name)).hexdigest() != digest:
                raise ValueError(f'G0 does not match current input: {name}')
    evidence_name = previous['competition'].get('score_evidence')
    if evidence_name not in files:
        raise ValueError('Checksum-covered score evidence is required')
    evidence = json.loads(files[evidence_name].read_text())
    score = evidence.get('displayed_score')
    screenshot = PurePosixPath(evidence['screenshot_file'])
    screenshot_name = str(PurePosixPath(evidence_name).parent / screenshot)
    if (len(screenshot.parts) != 1 or screenshot.is_absolute()
            or screenshot_name not in files
            or sha(files[screenshot_name]) != evidence['screenshot_sha256']
            or evidence['csv_sha256'] != sha(ds_csv)
            or evidence.get('file_binding_accepted') is not True
            or isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1
            or previous['competition']['reported_score'] != evidence['displayed_score']):
        raise ValueError('Score evidence/screenshot does not match the supplied CSV')
    return files, previous


def seal_bundle(output):
    """Include all deliverables in recursive checksums and a portable archive."""
    files = [p for p in sorted(output.rglob('*')) if p.is_file()
             and 'sources' not in p.relative_to(output).parts and p.name != 'SHA256SUMS']
    (output / 'SHA256SUMS').write_text(''.join(
        f'{sha(p)}  {p.relative_to(output).as_posix()}\n' for p in files))
    archive = Path(str(output) + '.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files + [output / 'SHA256SUMS']:
            info = zipfile.ZipInfo('tramflow-local-final/' + path.relative_to(output).as_posix(),
                                   date_time=(2026, 9, 26, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, path.read_bytes())
    archive.with_suffix('.zip.sha256').write_text(f'{sha(archive)}  {archive.name}\n')
    return archive


def preflight(candidate, template):
    with candidate.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        if reader.fieldnames != ['route', 'date', 'hour', 'prediction']:
            raise ValueError('Unexpected submission columns')
        rows = list(reader)
    template_bytes = template if isinstance(template, bytes) else template.read_bytes()
    with io.StringIO(template_bytes.decode('utf-8-sig'), newline='') as f:
        expected = list(csv.DictReader(f, delimiter=';'))
    keys = lambda items: [(r['route'], r['date'], r['hour']) for r in items]
    if len(rows) != 14640 or keys(rows) != keys(expected) or len(set(keys(rows))) != len(rows):
        raise ValueError('Candidate must preserve all 14,640 ordered sample keys')
    if any(not r['prediction'].isdigit() for r in rows):
        raise ValueError('Predictions must be nonnegative integers')
    baseline = [r for r in rows if r['route'] == '5']
    if len(baseline) != 1464 or any(int(r['prediction']) for r in baseline):
        raise ValueError('Expected explicit route 5 zero fallback')
    return {'passed': True, 'rows': len(rows), 'route5_rows': len(baseline),
            'template_sha256': hashlib.sha256(template_bytes).hexdigest(),
            'ordered_keys_equal': True, 'scope': 'full_sample'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True, type=Path)
    p.add_argument('--handoff', required=True, type=Path)
    p.add_argument('--ds-csv', required=True, type=Path)
    p.add_argument('--template', type=Path,
                   help='Organizer template; defaults to the original template inside supporting G0')
    p.add_argument('--include-list', required=True, type=Path)
    p.add_argument('--release-name', help='Display name of the verified local runtime release')
    p.add_argument('--g0-verification', type=Path, help='Independent saved-model CLI inference and float/DS proof')
    p.add_argument('--supporting-bundle', type=Path,
                   help='Unpacked verified local kit: preserve its G0, score confirmation and evidence')
    p.add_argument('--defer-team-acceptance', action='store_true',
                   help='Record explicitly user-deferred rehearsals/personal acceptance without claiming completion')
    p.add_argument('--verification-log', type=Path, help='Include a saved local packaging test log as evidence')
    p.add_argument('--additional-evidence', type=Path, help='Explicit local evidence directory with complete SHA256SUMS')
    p.add_argument('--runtime-verification', type=Path, help='Current tested runtime hashes/run/checks; preserved with original acceptance')
    p.add_argument('--point-reconstruction', type=Path,
                   help='Optional separately verified B2 point reconstruction ZIP, never a demo replacement')
    args = p.parse_args()
    output = args.output_dir.resolve()
    if output.exists() or Path(str(output) + '.zip').exists():
        p.error('Use a new directory; bundles are immutable')
    if args.verification_log and (args.verification_log.is_symlink() or not args.verification_log.is_file()):
        p.error('--verification-log must be a regular local file')
    template = args.template
    if template is None:
        if args.supporting_bundle is None:
            p.error('--template or --supporting-bundle with the original G0 template is required')
        with zipfile.ZipFile(args.supporting_bundle/'g0-b2.zip') as archive:
            roots = [n.removesuffix('bundle-manifest.json') for n in archive.namelist()
                     if n.endswith('/bundle-manifest.json')]
            if len(roots) != 1:
                raise ValueError('Expected one G0 bundle manifest for the organizer template')
            template = archive.read(roots[0] + 'template.csv')
    proof = preflight(args.ds_csv, template)
    reconstruction = None
    if args.point_reconstruction is not None:
        with zipfile.ZipFile(args.point_reconstruction) as archive:
            prefix = 'b2-point-reconstruction/'
            result = json.loads(archive.read(prefix + 'result.json'))
            frozen = json.loads(archive.read(prefix + 'frozen-inputs.json'))
            model_sha = hashlib.sha256(archive.read(prefix + 'reconstructed-point-model.joblib')).hexdigest()
            if (result['kind'] != 'new_fit_reconstruction_not_original_artifact'
                    or result['new_model_sha256'] != model_sha
                    or result['ds_sha256'] != sha(args.ds_csv)
                    or not result['matches_existing_competition_csv_bytes']
                    or not result['repeated_inference_exact']
                    or not result['preflight']['passed']
                    or result['original_artifact_identity_proven']
                    or result['handoff_created']):
                raise ValueError('Unexpected point reconstruction provenance or model/DS mismatch')
            for name, digest in frozen['source_hashes'].items():
                if sha(Path(name)) != digest:
                    raise ValueError(f'Point reconstruction source changed: {name}')
        reconstruction = {
            'archive': 'b2-point-reconstruction.zip',
            'archive_sha256': sha(args.point_reconstruction),
            'kind': result['kind'], 'new_model_sha256': model_sha,
            'point_forecast_sha256': result['point_forecast_sha256'],
            'ds_sha256': result['ds_sha256'], 'repeat_inference_exact': True,
            'original_artifact_identity_proven': False, 'interval_q90': None,
            'platform_receipt_verified': False, 'accepted_as_full_handoff': False}
    with tempfile.TemporaryDirectory(prefix='tram-bundle-') as temp:
        release = Path(temp) / 'release'
        install(args.handoff, release)
        snapshot = load_snapshot(release)
        metadata = json.loads((release / 'metadata.json').read_text())
        model_manifest = json.loads((release / 'manifest.json').read_text())
        demo = {'name': args.release_name or metadata['model_name'], 'model_name': metadata['model_name'], 'run_id': snapshot.run_id,
                'model_version': snapshot.model_version, 'dataset_version': snapshot.dataset_version,
                'model_sha256': sha(release / 'model.joblib'), 'forecast_sha256': snapshot.csv_sha256,
                'schema_sha256': sha(release / 'feature-schema.json'),
                'dataset_hashes': model_manifest['source_checksums'],
                'config': metadata.get('experiment_config'), 'model_parameters': metadata['model_parameters'],
                'seed': metadata['random_seed'],
                'training_period': metadata['training_period'], 'rows': len(snapshot.cells),
                'platform_score': None, 'score_status': 'not_linked_to_B2_score'}
    g0 = None
    if args.g0_verification is not None:
        g0 = json.loads(args.g0_verification.read_text())
        if (g0.get('model_sha256') != demo['model_sha256']
                or g0.get('forecast_sha256') != demo['forecast_sha256']
                or g0.get('csv_sha256') != sha(args.ds_csv)
                or g0.get('two_cli_runs_equal') is not True
                or g0.get('float_csv_roundtrip_all_rows') is not True
                or g0.get('rows') != 14640 or g0.get('fit_performed') is not False):
            raise ValueError('G0 proof does not match the supplied model/float/DS or lacks repeated saved-model inference')
        demo['score_status'] = 'CSV_link_verified_platform_receipt_unverified'
    supporting = None
    if args.supporting_bundle is not None:
        if g0 is None:
            p.error('--supporting-bundle requires --g0-verification')
        supporting = supporting_files(args.supporting_bundle, args.handoff, args.ds_csv,
                                      demo['model_sha256'])
    output.mkdir(parents=True)
    subprocess.run([sys.executable, '-m', 'scripts.package_submission_prep', '--output-dir', str(output/'sources'),
                    '--include-list', str(args.include_list.resolve())], check=True)
    source = json.loads((output/'sources/verification.json').read_text())
    shutil.copyfile(output/'sources/web-handoff-preparation.zip', output/'sources.zip')
    shutil.copyfile(args.handoff, output/'demo-handoff.zip')
    shutil.copyfile(args.ds_csv, output/'ds-candidate.csv')
    if reconstruction is not None:
        shutil.copyfile(args.point_reconstruction, output/'b2-point-reconstruction.zip')
    proof['csv_sha256'] = sha(output/'ds-candidate.csv')
    (output/'ds-preflight.json').write_text(json.dumps(proof, indent=2)+'\n')
    manifest = {'version': 'tramflow-local-final-v1', 'status': 'local_candidate_external_acceptance_pending',
        'source_commit': source['source_commit'], 'source_dirty': source['source_dirty'],
        'source_fingerprint': source['source_fingerprint'], 'source_archive_sha256': sha(output/'sources.zip'),
        'explicit_untracked_sources': source['explicit_untracked_sources'], 'demo': demo,
        'competition': {'csv_sha256': proof['csv_sha256'], 'exact_model_sha256': None,
            'reported_score': 0.84260, 'score_status': 'user_report_receipt_unverified',
            'receipt': None, 'reproducible_B2_inference': 'awaiting_G0'},
        'freeze_moscow': '2026-09-27T16:00:00+03:00',
        'not_performed': ['publication', 'deployment', 'competition_submission', 'form_submission', 'jury_link_access']}
    # This task's reported score is tied only to this exact provided competition CSV.
    if proof['csv_sha256'] != '505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94':
        manifest['competition']['reported_score'] = None
        manifest['competition']['score_status'] = 'unknown'
    if reconstruction is not None:
        manifest['competition']['point_reconstruction'] = reconstruction
    if g0 is not None:
        shutil.copyfile(args.g0_verification, output/'g0-reproduction.json')
        manifest['competition'].update(exact_model_sha256=demo['model_sha256'],
            reproducible_B2_inference='verified_without_fit', float_sha256=demo['forecast_sha256'],
            inference_proof='g0-reproduction.json', inference_proof_sha256=sha(output/'g0-reproduction.json'))
        manifest['original_training_provenance'] = {'commit': g0.get('original_training_commit'),
            'full_lock': g0.get('original_training_lock'), 'status': 'not_recorded_in_original_artifact'}
    if supporting is not None:
        files, previous = supporting
        for name, path in files.items():
            if name == 'g0-b2.zip' or name.startswith('evidence/'):
                target = output / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        manifest['g0'] = previous['g0']
        if 'runtime_scope' in previous:
            manifest['runtime_scope'] = previous['runtime_scope']
        manifest['competition'] = {**previous['competition'], **{
            k: v for k, v in manifest['competition'].items()
            if k not in ('reported_score', 'score_status', 'receipt')}}
        manifest['competition']['score_evidence'] = previous['competition']['score_evidence']
        manifest['demo'].update(platform_score=previous['demo']['platform_score'],
                                score_status=previous['demo']['score_status'],
                                score_scope='competition_integer_CSV')
        with zipfile.ZipFile(files['sources.zip']) as before, zipfile.ZipFile(output/'sources.zip') as after:
            names = set(before.namelist()) | set(after.namelist())
            changed = sorted(n for n in names if n not in before.namelist() or n not in after.namelist()
                             or before.read(n) != after.read(n))
        runtime_changed = [n for n in changed if not (n.endswith('.md')
            or n.endswith('/MANIFEST.sha256') or n.startswith('tram-forecast/scripts/')
            or n.startswith('tram-forecast/tests/tooling/')
            or n == 'tram-forecast/docs/submission-final/source-allowlist.json')]
        acceptance = json.loads(files['local-acceptance.json'].read_text())
        acceptance['source_fingerprint'] = source['source_fingerprint']
        acceptance['previous_runtime_checks_applicable'] = not runtime_changed
        acceptance['source_to_tested_candidate'] = 'revision-verification.json'
        acceptance['deferred_by_user'] = (['two_live_team_rehearsals', 'owners_personal_acceptance']
                                          if args.defer_team_acceptance else [])
        if args.defer_team_acceptance:
            acceptance['not_completed'].pop('two_live_rehearsals_and_code_explanation', None)
            acceptance['D4'] = 'local_materials_ready_rehearsals_and_team_acceptance_deferred_by_user'
        acceptance['status'] = ('local_ready_external_actions_not_authorized' if not runtime_changed
                                else 'runtime_reverification_required')
        manifest['status'] = acceptance['status']
        manifest['deferred_by_user'] = acceptance['deferred_by_user']
        manifest['not_performed_scope'] = 'assistant actions; user-confirmed DS submission is in competition.receipt'
        (output/'local-acceptance.json').write_text(json.dumps(acceptance, ensure_ascii=False, indent=2)+'\n')
        revision = {'supporting_manifest_sha256': sha(files['release-manifest.json']),
            'changed_source_files': changed, 'runtime_changed_files': runtime_changed,
            'previous_runtime_checks_applicable': not runtime_changed,
            'evidence_checksum_verified_before_copy': True,
            'note': 'Evidence records retain their original paths/timestamps/source versions; this is a new source snapshot.'}
        (output/'revision-verification.json').write_text(json.dumps(revision, indent=2)+'\n')
    else:
        manifest['delivery_completeness'] = 'core_only_G0_archive_and_supporting_evidence_not_supplied'
    if args.verification_log:
        target = output/'evidence/current-packaging-tests.log'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.verification_log, target)
        manifest['packaging_test_log'] = {'file': 'evidence/current-packaging-tests.log',
                                          'sha256': sha(target)}
    if args.additional_evidence:
        manifest['additional_evidence'] = additional_evidence(args.additional_evidence, output)
    if args.runtime_verification:
        proof = json.loads(args.runtime_verification.read_text())
        accept_runtime(proof, output / 'sources.zip', demo['run_id'])
        if not args.additional_evidence or not proof.get('evidence_sha256'):
            raise ValueError('Runtime verification requires checksum-covered supporting evidence')
        for name, digest in proof['evidence_sha256'].items():
            if manifest['additional_evidence'].get(name) != digest:
                raise ValueError(f'Runtime verification evidence missing or changed: {name}')
        shutil.copyfile(args.runtime_verification, output / 'current-runtime-verification.json')
        manifest['prior_status'] = manifest['status']
        manifest['status'] = 'local_ready_external_actions_not_authorized'
        manifest['current_runtime_verification'] = {'file': 'current-runtime-verification.json',
            'sha256': sha(output / 'current-runtime-verification.json')}
        if supporting is not None:
            shutil.copyfile(files['local-acceptance.json'], output / 'prior-local-acceptance.json')
            acceptance = {
                'status': manifest['status'], 'prior_status': acceptance['status'],
                'run': demo['run_id'], 'source_fingerprint': source['source_fingerprint'],
                'current_runtime_verification': manifest['current_runtime_verification'],
                'prior_acceptance': {'file': 'prior-local-acceptance.json',
                    'sha256': sha(output / 'prior-local-acceptance.json'),
                    'scope': 'Historical checks, counts, load and recordings belong to the previous source snapshot.'},
                'deferred_by_user': acceptance['deferred_by_user'],
                'not_completed': acceptance['not_completed'],
            }
            (output/'local-acceptance.json').write_text(json.dumps(acceptance, ensure_ascii=False, indent=2)+'\n')
    (output/'release-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    guide = (Path(__file__).resolve().parents[1]/'docs/submission-final/b2-bundle-guide.md').read_text()
    (output/'README.md').write_text(bundle_readme(guide))
    shutil.copyfile(output/'sources/verification.json', output/'source-packager-verification.json')
    print(seal_bundle(output))


if __name__ == '__main__':
    main()
