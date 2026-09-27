"""Assemble an immutable local jury kit from reviewed sources, C01 and accepted B2.

This does not train, deploy, publish, submit, or convert a competition model to web.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

from backend.handoff.install import install
from backend.handoff.store import load_snapshot
from scripts.build_final_bundle import preflight

ROOT = Path(__file__).resolve().parents[1]
GUIDES = (
    'README.md', 'web-launch.md', 'model-current.md', 'external-data.md',
    'performance.md', 'limitations.md', 'submission-fields.md', 'artifacts.md',
    'update-model.md',
)
WEATHER = ('weather-raw.json', 'weather-normalized.csv', 'weather-daily.csv',
           'weather-manifest.json', 'weather-audit.json', 'weather-verified.json')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '..' in path.parts or '\\' in name
            or any(part in {'.git', '.venv', 'node_modules', '.DS_Store'} for part in path.parts)
            or (path.name.startswith('.env') and path.name != '.env.example')
            or path.suffix == '.netrc' or path.name in {'jury-access.txt', 'tramflow-users.caddy', 'dataset.zip'}):
        raise ValueError(f'Unsafe or private archive path: {name}')
    return path


def check_zip(archive):
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError('Duplicate ZIP members')
    for info in archive.infolist():
        safe_name(info.filename)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('Archive symlink')
    if archive.testzip() is not None:
        raise ValueError('ZIP CRC failed')


def checked_files(root):
    root = root.resolve()
    found = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        rel = safe_name(name)
        path = root / rel
        if (name in found or not path.resolve().is_relative_to(root)
                or any(p.is_symlink() for p in [path, *path.parents] if p != root.parent)
                or not path.is_file() or sha(path) != digest):
            raise ValueError(f'Checksum/path failed: {name}')
        found[name] = path
    return found


def put(root, name, content):
    path = root / safe_name(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f'Refusing to overwrite {name}')
    path.write_bytes(content)


def dump(root, name, value):
    put(root, name, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--web-bundle', type=Path, required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--registry', type=Path, default=ROOT/'ml/experiments/platform-leader.json')
    parser.add_argument('--verification-dir', type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists() or Path(str(out)+'.zip').exists() or Path(str(out)+'.zip.sha256').exists():
        parser.error('Use a new output directory; old deliveries are immutable')
    # C01 paths and its replay entrypoint have been reviewed. New package layouts
    # need explicit adaptation, rather than silently reusing these instructions.
    if args.candidate != 'V11-C01':
        parser.error('This guide/external-data layout is reviewed for V11-C01; adapt it for a new model first')
    registry = json.loads(args.registry.read_text())
    if registry['leader'] != args.candidate:
        parser.error('Registry leader changed; review the selected version and guide before packaging')
    record = registry['artifacts'][args.candidate]
    paths = {}
    for key in ('package', 'csv', 'float', 'model', 'release_manifest'):
        path = ROOT / record[key]['path']
        if path.is_symlink() or sha(path) != record[key]['sha256']:
            raise ValueError(f'Leader checksum mismatch: {key}')
        paths[key] = path
    web = checked_files(args.web_bundle)
    source_sha = sha(args.sources)
    if args.verification_dir:
        proof = json.loads((args.verification_dir/'verification.json').read_text())
        if proof['sources_sha256'] != source_sha:
            raise ValueError('Verification belongs to other source bytes')
    with zipfile.ZipFile(args.sources) as source, zipfile.ZipFile(paths['package']) as model:
        check_zip(source)
        check_zip(model)
        source_manifest = source.read('tram-forecast/MANIFEST.sha256').decode()
        for line in source_manifest.splitlines():
            digest, name = line.split('  ', 1)
            if hashlib.sha256(source.read('tram-forecast/'+str(safe_name(name)))).hexdigest() != digest:
                raise ValueError(f'Source checksum failed: {name}')
        manifest = json.loads(model.read('manifest.json'))
        if model.read('manifest.json') != paths['release_manifest'].read_bytes():
            raise ValueError('Leader ZIP manifest differs from registered manifest')
        for name, item in manifest['files'].items():
            content = model.read(str(safe_name(name)))
            if len(content) != item['bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
                raise ValueError(f'Model manifest failed: {name}')
        candidate_member = 'final/C01/submission-v11-c01-20260927.csv'
        if model.read(candidate_member) != paths['csv'].read_bytes():
            raise ValueError('Candidate ZIP/CSV mismatch')
        ds_check = preflight(paths['csv'], model.read('inputs/template.csv'))
        out.mkdir(parents=True)
        shutil.copyfile(args.sources, out/'sources.zip')
        put(out, 'competition/model-package.zip', paths['package'].read_bytes())
        put(out, 'competition/submission.csv', paths['csv'].read_bytes())
        dump(out, 'competition/preflight.json', ds_check)
        dump(out, 'competition/selection.json', {
            'candidate': args.candidate, 'reported_score': registry['platform_scores'][args.candidate],
            'score_evidence': registry['platform_evidence'],
            'artifacts': {k: record[k] for k in ('package', 'csv', 'float', 'model', 'release_manifest')},
            'web_model': 'B2', 'installed_in_web': False,
            'note': 'Original package reports predate score registration; this sidecar records current selection.',
        })
        put(out, 'external-data/restriction-registry.json', model.read('sources/restriction-registry.json'))
        for name in WEATHER:
            put(out, 'external-data/weather/'+name, model.read('parents/v10/workers/M/sources/'+name))
        put(out, 'evidence/c01/clean-unpack-replay.json', model.read('verification/clean-unpack-replay.json'))
        for name in GUIDES:
            text = source.read('tram-forecast/docs/submission-final/'+name).decode()
            # Copied guides stay together; other Markdown links go to the unpacked source.
            import re
            import posixpath
            from urllib.parse import urlsplit, urlunsplit
            def rebase(match):
                parts = urlsplit(match.group(1))
                if parts.scheme or parts.netloc or not parts.path:
                    return match.group(0)
                if parts.path in GUIDES:
                    return match.group(0)
                path = posixpath.normpath('../tram-forecast/docs/submission-final/'+parts.path)
                return ']('+urlunsplit(parts._replace(path=path))+')'
            put(out, 'guides/'+name, re.sub(r'\]\(([^)]+)\)', rebase, text).encode())
        architecture = source.read('tram-forecast/docs/architecture.md').decode()
        def architecture_link(match):
            parts = urlsplit(match.group(1))
            if parts.scheme or parts.netloc or not parts.path:
                return match.group(0)
            if parts.path.startswith('submission-final/') and parts.path.split('/', 1)[1] in GUIDES:
                path = parts.path.split('/', 1)[1]
            else:
                path = posixpath.normpath('../tram-forecast/docs/'+parts.path)
            return ']('+urlunsplit(parts._replace(path=path))+')'
        architecture = re.sub(r'\]\(([^)]+)\)', architecture_link, architecture)
        put(out, 'guides/architecture.md', architecture.encode())
        guide = (out/'guides/README.md').read_text()
        guide = re.sub(r'\]\(([^)]+)\)', lambda m: m.group(0) if urlsplit(m.group(1)).scheme
                       else ']('+posixpath.normpath('guides/'+m.group(1))+')', guide)
        put(out, 'README.md', guide.encode())
        put(out, 'FORM-FIELDS.txt', (out/'guides/submission-fields.md').read_bytes())
    for name in ('demo-handoff.zip', 'g0-b2.zip', 'g0-reproduction.json'):
        target = name if name == 'demo-handoff.zip' else 'b2/'+name
        put(out, target, web[name].read_bytes())
    for name, path in web.items():
        if name.startswith('evidence/'):
            put(out, 'evidence/web-b2/'+name.removeprefix('evidence/'), path.read_bytes())
    put(out, 'evidence/web-b2/original-release-manifest.json', web['release-manifest.json'].read_bytes())
    if args.verification_dir:
        for path in sorted(args.verification_dir.rglob('*')):
            if path.is_symlink():
                raise ValueError('Verification symlink')
            if path.is_file():
                put(out, 'evidence/current/'+path.relative_to(args.verification_dir).as_posix(), path.read_bytes())
    # Import validation checks the exact B2 ZIP independently; temporary release is
    # outside the delivery and is not retained or mixed with the competition model.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='tram-upload-') as temp:
        release = Path(temp)/'release'
        install(out/'demo-handoff.zip', release)
        snapshot = load_snapshot(release)
        web_run = snapshot.run_id
    old_sources = web['sources.zip']
    with zipfile.ZipFile(old_sources) as before, zipfile.ZipFile(out/'sources.zip') as after:
        # Actual web runtime + shipped map/build config. ML research metadata and
        # documentation do not run in the HTTP service.
        def is_web(name):
            return (name.startswith(('tram-forecast/backend/', 'tram-forecast/frontend/'))
                    and not name.endswith('.md') and '/tests/' not in name
                    or name.startswith('tram-forecast/compose')
                    or name == 'tram-forecast/docs/submission-final/compose.local.yaml')
        names = {n for n in set(before.namelist()) | set(after.namelist()) if is_web(n)}
        changed = sorted(n for n in names if n not in before.namelist() or n not in after.namelist()
                         or before.read(n) != after.read(n))
    dump(out, 'release-manifest.json', {
        'schema': 'tramflow-jury-upload-v1', 'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'local_prepared_not_uploaded', 'competition_model': args.candidate,
        'competition_csv_sha256': sha(out/'competition/submission.csv'),
        'competition_package_sha256': sha(out/'competition/model-package.zip'),
        'reported_score': registry['platform_scores'][args.candidate], 'score_source': 'user_report',
        'web_model': 'B2', 'web_run': web_run, 'sources_sha256': source_sha,
        'web_runtime_changed_from_accepted_b2': changed,
        'historical_evidence_scope': 'B2 checks retain original dates/environments; they do not validate C01 or publication.',
        'current_verification': 'evidence/current/verification.json' if args.verification_dir else None,
        'not_performed': ['upload', 'form_submission', 'DS_submission', 'deployment', 'new_training'],
    })
    intro = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TramFlow — комплект сдачи</title><style>
*{box-sizing:border-box}body{max-width:940px;margin:48px auto;padding:0 24px;font:17px/1.6 system-ui;color:#202336;background:#faf9fc}
h1{font-size:48px;line-height:1.1;letter-spacing:-1.5px;margin:12px 0 24px}h2{font-size:25px;margin-top:38px}a{color:#5038a6}
.label{color:#65558a;font-size:13px;font-weight:700;letter-spacing:2px}.note{background:#eee9f8;padding:20px 24px;border-radius:16px}
table{border-collapse:collapse;width:100%;background:white}td,th{text-align:left;padding:14px;border-bottom:1px solid #e3dfeb}
code{font-size:14px;overflow-wrap:anywhere}li{margin:9px 0}.muted{color:#626477}footer{margin:36px 0;border-top:1px solid #ddd;padding-top:20px;font-size:14px}
@media(max-width:600px){body{margin:28px auto;padding:0 16px}h1{font-size:36px}td,th{padding:9px;font-size:14px}}@media print{body{background:white;margin:0}a{color:inherit}}
</style><main><div class="label">TRAMFLOW · 27 СЕНТЯБРЯ 2026</div>
<h1>Комплект сдачи</h1><p>Прогноз успешных посадок на трамвайных маршрутах: модель, запускаемый веб-сервис и материалы для шести полей формы.</p>
<div class="note"><strong>Подготовлено локально.</strong> Загрузите архив на Диск, проверьте доступ по ссылке и вставьте её в форму. Отправка формы не выполнена. Новую модель Георгия добавляем отдельной версией после проверки.</div>
<h2>Две версии внутри одного комплекта</h2><table><thead><tr><th>Для чего</th><th>Модель</th><th>Результат CSV</th></tr></thead><tbody>
<tr><td>Конкурс Data Science</td><td>C01</td><td>0,89003</td></tr><tr><td>Веб и Docker inference</td><td>B2</td><td>0,84260</td></tr></tbody></table>
<p class="muted">Результат C01 записан по сообщению Даниэля. В вебе пока B2; результаты и замеры этих моделей не смешиваются.</p>
<h2>С чего начать</h2><ol>
<li><strong>Показать веб.</strong> Откройте <a href="guides/web-launch.md">инструкцию Docker Compose</a>. Она использует <code>sources.zip</code> и <code>demo-handoff.zip</code>. Нужны Docker, Compose ≥2.24.4 и интернет для первой сборки.</li>
<li><strong>Повторить конкурсный CSV.</strong> Откройте <a href="guides/model-current.md">инструкцию C01</a>. В <code>competition/model-package.zip</code> сохранены вся цепочка моделей, код и входы. Нужен Python 3.12.</li>
<li><strong>Заполнить форму.</strong> Откройте <a href="FORM-FIELDS.txt">готовые тексты всех шести полей</a>. Замените маркер ссылки на адрес загруженного комплекта. Если поле принимает только URL, вставьте только ссылку.</li></ol>
<h2>Что загрузить на Диск</h2><p>Полный ZIP, соседний файл <code>.zip.sha256</code>, эту страницу и <code>FORM-FIELDS.txt</code>. Альтернатива — распакованная папка целиком. Проверьте скачивание в приватном окне браузера.</p>
<p>CSV в Data Science и форма «Загрузка решения» — две отдельные сдачи. По переданному PDF срок — <strong>27 сентября, 23:59 МСК</strong>; для формы учитывается последняя сохранённая версия.</p>
<h2>Материалы для жюри</h2><ul>
<li><a href="guides/external-data.md">Внешние данные</a> — ссылки, погода, календарь, изменения движения и границы ретроспективного режима.</li>
<li><a href="guides/architecture.md">Архитектура</a> — отдельный ML-расчёт, проверка пакета, FastAPI, React и CSV.</li>
<li><a href="guides/performance.md">Производительность</a> — локально 199,967 запросов/с и p95 9,310 мс при выдаче готового прогноза; условия и ограничения замеров.</li>
<li><a href="guides/limitations.md">Ограничения и развитие</a> — посадки не равны заполненности; остановочного и численного годового прогноза пока нет.</li>
<li><a href="guides/update-model.md">Замена модели</a> — порядок проверки и пересборки нового комплекта.</li></ul>
<footer>Проверка целостности после распаковки: <code>shasum -a 256 -c SHA256SUMS</code>.<br>Полная опись: <a href="README.md">README</a> · <a href="release-manifest.json">Версии и проверки</a>. Модель и агрегированные производные данных предназначены для передачи жюри.</footer></main></html>'''
    put(out, 'START-HERE.html', intro.encode())
    files = [p for p in sorted(out.rglob('*')) if p.is_file()]
    put(out, 'SHA256SUMS', ''.join(f'{sha(p)}  {p.relative_to(out).as_posix()}\n' for p in files).encode())
    archive_path = Path(str(out)+'.zip')
    with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files+[out/'SHA256SUMS']:
            archive.write(path, 'TramFlow/'+path.relative_to(out).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        check_zip(archive)
    Path(str(archive_path)+'.sha256').write_text(f'{sha(archive_path)}  {archive_path.name}\n')
    print(json.dumps({'archive': str(archive_path), 'bytes': archive_path.stat().st_size,
                      'web_runtime_changed': changed}, ensure_ascii=False))


if __name__ == '__main__':
    main()
