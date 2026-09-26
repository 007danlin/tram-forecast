"""Finite temporal experiment runner with immutable, fingerprinted fold outputs."""
from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import itertools
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys
import tempfile
import time

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.artifact import sha256_file, load_artifact, predict_artifact, submission_preflight, write_submission
from ml.baselines import BlockMeanBaseline, ComparableWeeksMedianBaseline, PreviousWeekdayBaseline
from ml.data import load_organizer_labels
from ml.experiment_config import normalize_config
from ml.factors import add_official_calendar_features, load_weather_factors
from ml.model import build_hgbt_model
from ml.score_models import SCHEMA, ScoreModel, score_config
from ml.settings import KEY_COLUMNS, TARGET_COLUMN

BASE_CONFIG = normalize_config({'id': 'W00', 'weather_groups': []})
BASELINES = {'B-block': BlockMeanBaseline, 'B-weekday': PreviousWeekdayBaseline, 'B-median': ComparableWeeksMedianBaseline}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        f.write('\n')


def metrics(frame, rounded=True):
    y = frame[TARGET_COLUMN].to_numpy(float)
    p = np.maximum(frame.prediction.to_numpy(float), 0)
    if not np.isfinite(p).all() or not np.isfinite(y).all():
        raise ValueError('Nonfinite metric inputs')
    if rounded:
        p = np.floor(p + .5)
    ae = np.abs(y - p)
    total = float(y.sum())
    return {'rows': len(frame), 'sum_y': total, 'absolute_error': float(ae.sum()),
            'mae': float(ae.mean()), 'signed_bias': float((p-y).sum()),
            'score': max(0., 1 - float(ae.sum()) / total) if total else None}


def summarize(frame):
    data = add_official_calendar_features(frame)
    data['horizon'] = pd.cut(data.horizon_day, [0, 7, 30, 61], labels=['1-7', '8-30', '31-61']).astype(str)
    data['peak'] = np.where(data.hour.isin([7, 8, 9, 16, 17, 18, 19]), 'peak', 'offpeak')
    return {'rounded': metrics(data), 'unrounded': metrics(data, False),
            'unique_dates': int(data.date.nunique()),
            'slices': {key: {str(name): metrics(part) for name, part in data.groupby(key, sort=True)}
                       for key in ['fold', 'route', 'hour', 'is_day_off', 'peak', 'horizon']}}


def assert_same_tasks(a, b):
    keys = ['fold', *KEY_COLUMNS, TARGET_COLUMN, 'horizon_day']
    if not a[keys].reset_index(drop=True).equals(b[keys].reset_index(drop=True)):
        raise ValueError('OOF keys, targets, horizons or order disagree')


def guardrail(candidate, baseline, thresholds):
    assert_same_tasks(candidate, baseline)
    a, b = summarize(candidate), summarize(baseline)
    reasons = []
    delta = a['rounded']['score'] - b['rounded']['score']
    folds = {k: a['slices']['fold'][k]['score'] - v['score'] for k, v in b['slices']['fold'].items()}
    if delta < thresholds['min_gain']:
        reasons.append('combined_gain_below_minimum')
    if sum(v > 0 for v in folds.values()) < thresholds['min_improved_folds']:
        reasons.append('too_few_improved_folds')
    if min(folds.values()) < thresholds['min_fold_delta']:
        reasons.append('fold_regression')
    route_changes = {}
    for route, prior in b['slices']['route'].items():
        current = a['slices']['route'][route]['mae']
        change = current / prior['mae'] - 1 if prior['mae'] else (0. if current == 0 else None)
        route_changes[route] = change
        if current > prior['mae'] * (1 + thresholds['max_route_mae_increase']) + 1e-12:
            reasons.append('route_' + route + '_mae_regression')
    horizons = {k: a['slices']['horizon'][k]['score'] - v['score'] for k, v in b['slices']['horizon'].items()}
    if min(horizons.values()) < thresholds['min_horizon_delta']:
        reasons.append('horizon_regression')
    return {'passed': not reasons, 'reasons': reasons, 'delta_score': delta,
            'fold_deltas': folds, 'route_mae_changes': route_changes, 'horizon_deltas': horizons}


def block_uncertainty(candidate, baseline, seed, repeats=2000):
    assert_same_tasks(candidate, baseline)
    frame = candidate[['date', TARGET_COLUMN]].copy()
    frame['gain'] = np.abs(baseline[TARGET_COLUMN] - np.floor(baseline.prediction + .5)) - np.abs(candidate[TARGET_COLUMN] - np.floor(candidate.prediction + .5))
    # Same seven-day calendar block from every overlapping origin moves together.
    frame['block'] = (frame.date - frame.date.min()).dt.days // 7
    blocks = frame.groupby('block')[[TARGET_COLUMN, 'gain']].sum().to_numpy(float)
    rng = np.random.default_rng(seed)
    samples = blocks[rng.integers(0, len(blocks), (repeats, len(blocks)))].sum(axis=1)
    gains = samples[:, 1] / samples[:, 0]
    return {'delta_score_interval_95': np.quantile(gains, [.025, .975]).tolist(), 'blocks': len(blocks),
            'repeats': repeats, 'unit': 'shared calendar seven-day blocks across origins',
            'caveat': 'Selected on these OOF: optimistic, dependent windows; not independent evidence.'}


def choose(records, thresholds):
    eligible = [r for r in records.values() if r['admission']['passed']]
    if not eligible:
        return 'W00'
    best = max(r['summary']['rounded']['score'] for r in eligible)
    near = [r for r in eligible if best-r['summary']['rounded']['score'] < thresholds['tie_tolerance']]
    return min(near, key=lambda r: (complexity(r['config']), -min(r['admission']['fold_deltas'].values()), r['id']))['id']


def complexity(config):
    if config.get('kind') == 'blend':
        return sum(complexity(c) for c in config['components'])
    return 2 if config.get('kind') in ('profile', 'level', 'direct') else 1


def source_fingerprint(config, dataset, baseline_artifact, baseline_submission, weather_path):
    root = Path(__file__).resolve().parent.parent
    paths = [*sorted((root/'ml').glob('*.py')), *sorted((root/'ml').glob('requirements*.txt')),
             root/'scripts/package_ml_handoff.py']
    sources = {str(p.relative_to(root)): sha256_file(p) for p in paths}
    data_paths = ['README.md', 'train.csv', 'test.csv', 'labels/labels_day_train.csv', 'labels/labels_day_test.csv', 'test_submission.csv']
    data = {name: sha256_file(Path(dataset)/name) for name in data_paths}
    versions = {p: importlib.metadata.version(p) for p in ['numpy', 'pandas', 'scikit-learn', 'scipy', 'joblib', 'threadpoolctl']}
    try:
        versions['catboost'] = importlib.metadata.version('catboost')
    except importlib.metadata.PackageNotFoundError:
        versions['catboost'] = None
    baseline = {p.name: sha256_file(p) for p in sorted(Path(baseline_artifact).iterdir()) if p.is_file()}
    weather = {p.name: sha256_file(p) for p in [weather_path, weather_path.with_name('manifest.json'), weather_path.with_name('raw.json')] if p.is_file()} if weather_path else None
    fields = {'config': config, 'sources': sources, 'data': data, 'dependencies': versions,
              'python': sys.version, 'baseline_artifact': baseline, 'baseline_submission': sha256_file(baseline_submission), 'weather': weather}
    return {'fingerprint': digest(fields), **fields}


def initialize_run(output, fingerprint, resume=False):
    output = Path(output)
    if output.exists():
        if not resume:
            raise ValueError('Output exists; choose a new directory or validated --resume')
        saved = json.loads((output/'fingerprint.json').read_text())
        if saved != fingerprint:
            raise ValueError('Resume fingerprint mismatch: config/data/source/dependency/baseline changed')
    else:
        if resume:
            raise ValueError('Cannot resume an absent run')
        output.mkdir(parents=True)
        write_json(output/'fingerprint.json', fingerprint)
        write_json(output/'config.json', fingerprint['config'])
        (output/'initial.diff').write_bytes(subprocess.check_output(['git', 'diff']))
    return output


class Runner:
    def __init__(self, data, config, output, fingerprint, factors=None, snapshot=None):
        self.data, self.config, self.output = data, config, Path(output)
        self.fingerprint, self.factors, self.snapshot = fingerprint, factors, snapshot
        self.records, self.oof, self.baseline_models = {}, {}, {}

    def evaluate(self, id, config, folds=None, diagnostic=False):
        folds = self.config['folds'] if folds is None else folds
        parts, details = [], []
        for fold in folds:
            target = self.output/'folds'/id/fold['id']
            identity = digest({'run': self.fingerprint, 'id': id, 'config': config, 'fold': fold})
            if target.exists():
                saved = json.loads((target/'record.json').read_text())
                if saved['identity'] != identity or sha256_file(target/'oof.csv') != saved['oof_sha256'] or sha256_file(target/'model.joblib') != saved['model_sha256']:
                    raise ValueError('Invalid completed fold cache')
                part = pd.read_csv(target/'oof.csv', parse_dates=['date'], float_precision='round_trip')
                model = joblib.load(target/'model.joblib') if id == 'W00' else None
                info = saved['fit']
            else:
                history = self.data[self.data.date.between(fold['train_start'], fold['train_end'])].copy()
                actual = self.data[self.data.date.between(fold['start'], fold['end'])].copy()
                started = time.monotonic()
                with threadpool_limits(limits=self.config['threads']):
                    if id in BASELINES:
                        model = BASELINES[id]().fit(history)
                        predicted = model.predict(fold['start'], fold['end'])
                    else:
                        model = build_hgbt_model(config['model_name'], config)
                        if isinstance(model, ScoreModel):
                            cache = {json.dumps(BASE_CONFIG, sort_keys=True): self.baseline_models[fold['id']]} if fold['id'] in self.baseline_models else {}
                            model.fit(history, self.factors, _cache=cache)
                        else:
                            model.fit(history, self.factors)
                        predicted = model.predict(fold['start'], fold['end'], factors=self.factors)
                part = actual[[*KEY_COLUMNS, TARGET_COLUMN]].merge(predicted[[*KEY_COLUMNS, 'prediction', 'status']], on=list(KEY_COLUMNS), validate='one_to_one')
                if len(part) != len(actual) or not np.isfinite(part.prediction).all():
                    raise ValueError('Incomplete forecast grid')
                part['fold'] = fold['id']
                part['horizon_day'] = (part.date - pd.Timestamp(fold['start'])).dt.days + 1
                info = {'seconds': time.monotonic()-started, 'peak_process_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024),
                        'model': getattr(model, 'fit_details_', {}), 'thread_limit': self.config['threads']}
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=target.parent))
                try:
                    part.to_csv(temporary/'oof.csv', index=False)
                    joblib.dump(model, temporary/'model.joblib', compress=3)
                    write_json(temporary/'record.json', {'identity': identity, 'fit': info, 'config': config, 'fold': fold,
                                                        'oof_sha256': sha256_file(temporary/'oof.csv'), 'model_sha256': sha256_file(temporary/'model.joblib')})
                    temporary.rename(target)
                finally:
                    if temporary.exists(): shutil.rmtree(temporary)
                print(json.dumps({'event': 'fold_complete', 'experiment': id, 'fold': fold['id'], **info}, default=str), flush=True)
            if id == 'W00':
                self.baseline_models[fold['id']] = model
            parts.append(part)
            details.append(info)
        result = pd.concat(parts, ignore_index=True)
        if diagnostic:
            return result, details
        self.record(id, config, result, details)
        return result

    def record(self, id, config, frame, details):
        baseline = self.oof.get('W00', frame)
        record = {'id': id, 'config': config, 'config_hash': digest(config), 'run_fingerprint': self.fingerprint,
                  'summary': summarize(frame), 'admission': guardrail(frame, baseline, self.config['thresholds']),
                  'fit': details, 'platform_score': None}
        target = self.output/'experiments'/id
        if target.exists():
            old = json.loads((target/'record.json').read_text())
            if old != record or sha256_file(target/'oof.csv') != (target/'oof.sha256').read_text().strip():
                raise ValueError('Experiment differs from completed immutable output')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix='.pending-', dir=target.parent))
            try:
                frame.to_csv(tmp/'oof.csv', index=False)
                (tmp/'oof.sha256').write_text(sha256_file(tmp/'oof.csv')+'\n')
                write_json(tmp/'record.json', record)
                tmp.rename(target)
            finally:
                if tmp.exists(): shutil.rmtree(tmp)
        self.records[id], self.oof[id] = record, frame
        print(json.dumps({'event': 'experiment_complete', 'id': id, 'score': record['summary']['rounded']['score'], 'admission': record['admission']}), flush=True)

    def blend(self, id, left, right, right_weight):
        a, b = self.oof[left], self.oof[right]
        assert_same_tasks(a, b)
        result = a.copy()
        result['prediction'] = (1-right_weight)*a.prediction + right_weight*b.prediction
        config = score_config('blend', id, seed=self.config['seed'], threads=self.config['threads'],
                              components=[self.records[left]['config'], self.records[right]['config']], weights=[1-right_weight, right_weight])
        self.record(id, config, result, [{'reused_oof': [left, right], 'seconds': 0.}])

    def ensemble(self, prefix, extra=()):
        winners = ['W00']
        for family in ['R', 'H', 'C']:
            candidates = {k:v for k,v in self.records.items() if k.startswith(family) and v['admission']['passed']}
            if candidates:
                winners.append(choose(candidates, self.config['thresholds']))
        winners.extend(extra)
        for a, b in itertools.combinations(winners, 2):
            if prefix == 'E-rain' and not ({a,b} & set(extra)):
                continue
            for weight in self.config['ensemble_weights']:
                self.blend(f'{prefix}-{a}-{b}-{int(weight*100)}', a, b, weight)


def freeze_iterations(config, records):
    result = copy.deepcopy(config)
    if result.get('kind') == 'blend':
        result['components'] = [freeze_iterations(c, records) for c in result['components']]
    elif result.get('kind') in ('catboost', 'direct'):
        record = records[result['id']]
        result['iterations'] = int(np.median([f['model']['iterations'] for f in record['fit']]))
    return result


def validate_protocol(config):
    if config.get('schema') != SCHEMA or not 1 <= config['threads'] <= 4:
        raise ValueError('Unknown study or invalid threads')
    if len(config['folds']) != 4 or len({f['id'] for f in config['folds']}) != 4:
        raise ValueError('Four unique selection folds required')
    for f in config['folds']:
        if pd.Timestamp(f['start']) != pd.Timestamp(f['train_end']) + pd.Timedelta(days=1) or (pd.Timestamp(f['end']) - pd.Timestamp(f['start'])).days != 60:
            raise ValueError('Folds require 61 days after cutoff')
        if pd.Timestamp(f['end']) > pd.Timestamp('2025-10-31'):
            raise ValueError('Forbidden evaluation target')


def run_study(dataset_dir, config_path, baseline_artifact, baseline_submission, output_dir, resume=False):
    config = json.loads(Path(config_path).read_text())
    validate_protocol(config)
    if sys.version_info[:2] != (3,12):
        raise ValueError('Use Python 3.12 for the score study')
    dataset = Path(dataset_dir)
    weather_path = Path(config['weather_snapshot'])/'normalized.csv'
    weather_available = weather_path.is_file()
    fp = source_fingerprint(config, dataset, baseline_artifact, baseline_submission, weather_path if weather_available else None)
    output = initialize_run(output_dir, fp, resume)
    if (output/'complete.json').exists():
        return json.loads((output/'complete.json').read_text())
    audit_path = output/'audit.json'
    if not audit_path.exists():
        preflight = submission_preflight(baseline_submission, dataset/'test_submission.csv')
        if not preflight['passed'] or preflight['sha256'] != config['baseline_sha256']:
            raise ValueError('Baseline submission identity/preflight failed')
        payload, metadata = load_artifact(baseline_artifact)
        if metadata['model_name'] != 'calendar_holiday_hgbt' or payload['model'].include_weather:
            raise ValueError('W00 artifact differs from agreed baseline')
        manifest = json.loads((Path(baseline_artifact)/'manifest.json').read_text())
        if any(fp['data'][('labels/'+k if k.startswith('labels_') else k)] != v for k,v in manifest['source_checksums'].items()):
            raise ValueError('Source differs from audited baseline: run verify-target first')
        reproduced = output/'baseline-reproduced.csv'
        if not reproduced.exists():
            write_submission(predict_artifact(baseline_artifact,'2025-11-01','2025-12-31'), dataset/'test_submission.csv', reproduced)
        if sha256_file(reproduced) != preflight['sha256']:
            raise ValueError('Saved baseline fails exact reproduction')
        hardware = subprocess.run(['sysctl','hw.memsize','machdep.cpu.brand_string'], capture_output=True, text=True)
        write_json(audit_path, {'preflight': preflight, 'source_checksums': fp['data'], 'head': subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                 'python':sys.version, 'dependencies':fp['dependencies'], 'cpu_count':os.cpu_count(), 'hardware': hardware.stdout or hardware.stderr,
                 'raw_check': 'checksums match streaming audit; zero label discrepancies in prior audit',
                 'reported_platform_baseline': .83732, 'platform_protocol_verified': False})
    factors, snapshot = None, None
    if weather_available:
        snapshot = json.loads(weather_path.with_name('manifest.json').read_text())
        if snapshot['alignment'] != 'next_hour_accumulation_v2' or snapshot['normalized']['sha256'] != sha256_file(weather_path) or snapshot['raw_snapshot']['sha256'] != sha256_file(weather_path.with_name('raw.json')):
            raise ValueError('Weather snapshot integrity/alignment failed')
        factors = load_weather_factors(weather_path)
    data = load_organizer_labels(dataset, '2025-01-01', '2025-10-31')
    runner = Runner(data, config, output, fp['fingerprint'], factors, snapshot)
    runner.evaluate('W00', BASE_CONFIG)
    for id in BASELINES:
        runner.evaluate(id, {'model_name': id})
    common = {'seed':config['seed'], 'threads':config['threads']}
    for spec in config['profiles']:
        id = spec['id']
        pure = score_config('profile', id, **common, window=spec['window'], statistic=spec['statistic'], alpha=1.)
        runner.evaluate(id, pure)
        for alpha in config['profile_weights']:
            if alpha < 1:
                mixed = runner.oof[id].copy()
                mixed['prediction'] = (1-alpha)*runner.oof['W00'].prediction + alpha*mixed.prediction
                cfg = {**pure, 'id':f'{id}-{int(alpha*100)}', 'alpha':alpha}
                runner.record(cfg['id'], cfg, mixed, [{'reused_oof':['W00',id], 'seconds':0.}])
    runner.evaluate('R-level', score_config('level','R-level',**common))
    for spec in config['hgbt']:
        runner.evaluate(spec['id'], score_config('hgbt', **spec, **common))
    blocked = {}
    if fp['dependencies']['catboost']:
        for spec in config['catboost']:
            runner.evaluate(spec['id'], score_config('catboost', **spec, **common, **config['catboost_fixed']))
    else:
        blocked['C'] = 'CatBoost dependency unavailable'
    runner.ensemble('E')
    p1_choice = choose({k:v for k,v in runner.records.items() if k not in BASELINES}, config['thresholds'])
    if factors is not None:
        rain = normalize_config({'id':'W02','weather_groups':['precipitation'],'alignment':'next_hour_accumulation_v2'})
        runner.evaluate('W02', rain)
        for weight in config['ensemble_weights']:
            runner.blend(f'W-rain-{int(weight*100)}','W00','W02',weight)
        rains = {k:v for k,v in runner.records.items() if (k == 'W02' or k.startswith('W-rain')) and v['admission']['passed']}
        if rains:
            runner.ensemble('E-rain', [choose(rains, config['thresholds'])])
    else:
        blocked['W-rain'] = 'Buffered snapshot unavailable'
    if p1_choice == 'W00' and fp['dependencies']['catboost']:
        for weather in ([[], ['precipitation']] if factors is not None else [[]]):
            id = 'D-rain' if weather else 'D-calendar'
            runner.evaluate(id, score_config('direct', id, **common, **config['direct'], weather_groups=weather))
    elif p1_choice == 'W00':
        blocked['D'] = 'CatBoost dependency unavailable'
    blocked['F-events'] = 'See external-events.json for verified sources; effect unestimated without comparable historical restrictions'
    blocked['T-clean'] = 'No confirmed technological-validation mask or raw-data error'
    selected = choose({k:v for k,v in runner.records.items() if k not in BASELINES}, config['thresholds'])
    best_rejected = max((v for k,v in runner.records.items() if k not in BASELINES and not v['admission']['passed'] and k != 'W00'),key=lambda r:r['summary']['rounded']['score'])
    chosen_config = freeze_iterations(runner.records[selected]['config'], runner.records)
    chosen_oof = runner.oof[selected]
    supported = chosen_oof[chosen_oof.status == 'ok']
    selection = {'protocol':config, 'run_fingerprint':fp['fingerprint'], 'selected_id':selected, 'selected_model':chosen_config['model_name'],
                 'selected_config':chosen_config, 'snapshot':snapshot if chosen_config.get('weather_groups') else None,
                 'interval':{'absolute_error_q90':float(np.quantile(np.abs(supported.boardings-supported.prediction),.9))},
                 'summary':runner.records[selected], 'best_rejected':best_rejected, 'blocked':blocked,
                 'uncertainty':block_uncertainty(chosen_oof,runner.oof['W00'],config['seed']), 'platform_score':None,
                 'selection_caveat':'Overlapping, previously inspected historical windows; not independent test.'}
    selection_path = output/'selection.json'
    if selection_path.exists():
        if json.loads(selection_path.read_text()) != selection:
            raise ValueError('Frozen selection differs')
    else:
        write_json(selection_path, selection)
    journal = output/'experiment-log.csv'
    if not journal.exists():
        pd.DataFrame([{'id':r['id'], 'score':r['summary']['rounded']['score'], 'delta_score':r['admission']['delta_score'],
                       'admitted':r['admission']['passed'], 'reasons':json.dumps(r['admission']['reasons']),
                       'config_hash':r['config_hash'], 'record':f"experiments/{r['id']}/record.json", 'platform_score':None} for r in runner.records.values()]).to_csv(journal,index=False)
    # Freeze selection first. The diagnostic cannot select another candidate.
    holdout = [config['diagnostic_holdout']]
    base_hold, _ = runner.evaluate('diagnostic-W00',BASE_CONFIG,holdout,True)
    if selected == 'W00':
        chosen_hold = base_hold
    else:
        chosen_hold, _ = runner.evaluate('diagnostic-selected',chosen_config,holdout,True)
    delta = metrics(chosen_hold)['score']-metrics(base_hold)['score']
    diagnostic = {'label':'Repeated diagnostic Sep-Oct; previously inspected, not independent', 'baseline':summarize(base_hold), 'selected':summarize(chosen_hold),
                  'delta_score':delta, 'recommended':selected != 'W00' and delta >= config['thresholds']['min_holdout_delta'], 'selection_sha256':sha256_file(selection_path)}
    if not (output/'diagnostic.json').exists(): write_json(output/'diagnostic.json',diagnostic)
    # A second fixed seed checks stability, without choosing the better seed.
    if selected != 'W00':
        repeat = reseed(chosen_config,config['stability_seed'])
        stability, detail = runner.evaluate('stability-selected',repeat,diagnostic=True)
        stability_report = {'seed':config['stability_seed'],'summary':summarize(stability),'admission':guardrail(stability,runner.oof['W00'],config['thresholds']), 'fit':detail,'used_for_selection':False}
    else:
        stability_report = {'status':'No admitted finalist; original W00 retained, no new seed selected'}
    if not (output/'stability.json').exists(): write_json(output/'stability.json',stability_report)
    complete = {'selected_id':selected, 'recommended':diagnostic['recommended'], 'best_rejected_id':best_rejected['id'], 'experiments':len(runner.records),
                'output_dir':str(output),'selection':str(selection_path), 'decision':'new_finalist' if diagnostic['recommended'] else 'retain_original_baseline'}
    write_json(output/'complete.json',complete)
    return complete


def reseed(config, seed):
    c = copy.deepcopy(config)
    if c.get('schema') == SCHEMA:
        c['seed'] = seed
        if c.get('kind') == 'blend':
            c['components'] = [reseed(x,seed) for x in c['components']]
    else:
        c['seed'] = seed
    return c
