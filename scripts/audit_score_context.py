"""Read-only score audit; writes diagnostics to a new local artifacts directory.

No hyperparameter search, final model, submission, or source-data edits.
Run with the repository's Python 3.12 score environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from threadpoolctl import threadpool_limits

from ml.data import load_organizer_labels
from ml.factors import HOLIDAY_MODEL_COLUMNS, add_official_calendar_features
from ml.metrics import regression_metrics, round_submission_predictions
from ml.model import build_hgbt_model
from ml.settings import MODELED_ROUTES


FOLDS = [
    ('S1', '2025-04-30', '2025-05-01', '2025-06-30'),
    ('S2', '2025-05-31', '2025-06-01', '2025-07-31'),
    ('S3', '2025-06-30', '2025-07-01', '2025-08-30'),
    ('S4', '2025-07-31', '2025-08-01', '2025-09-30'),
    ('D', '2025-08-31', '2025-09-01', '2025-10-31'),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(frame, column='ensemble'):
    result = regression_metrics(frame.boardings, round_submission_predictions(frame[column]))
    result['sum_prediction'] = int(round_submission_predictions(frame[column]).sum())
    result['bias'] = result['sum_prediction'] - result['sum_y']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    data = load_organizer_labels(args.dataset_dir, '2025-01-01', '2025-10-31')
    model_data = data[data.route.isin(MODELED_ROUTES)].copy()
    report = {
        'purpose': 'diagnostic reproduction, not model selection or pristine validation',
        'python': platform.python_version(), 'sklearn': sklearn.__version__,
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'source_sha256': {str(p): sha(p) for p in [Path(__file__), Path('ml/model.py'),
            Path('ml/data.py'), Path('ml/factors.py'), Path('ml/settings.py'),
            args.dataset_dir / 'README.md', args.dataset_dir / 'labels/labels_day_train.csv',
            args.dataset_dir / 'labels/labels_day_test.csv', args.dataset_dir / 'test_submission.csv']},
        'profile': {'rows': len(data), 'model_rows': len(model_data),
            'sum_y': int(data.boardings.sum()), 'duplicate_keys': int(data.duplicated(['route','date','hour']).sum()),
            'zero_cells': int(data.boardings.eq(0).sum()),
            'route5_sum': int(data.loc[data.route.eq(5), 'boardings'].sum())},
        'folds': [],
    }
    daily = model_data.groupby(['route','date'], as_index=False).boardings.sum()
    daily['month'] = daily.date.dt.to_period('M').astype(str)
    daily['weekend'] = daily.date.dt.dayofweek.ge(5)
    monthly = daily.groupby(['route','month','weekend']).boardings.agg(['mean','sum','count']).reset_index()
    monthly.to_csv(output / 'monthly-demand.csv', index=False)
    template = pd.read_csv(args.dataset_dir/'test_submission.csv', sep=';')
    report['sample'] = {'rows':len(template), 'routes':sorted(template.route.unique().tolist()),
        'duplicate_keys':int(template.duplicated(['route','date','hour']).sum()),
        'route5_rows':int(template.route.eq(5).sum())}
    forecast_calendar = add_official_calendar_features(pd.DataFrame({'date':pd.date_range('2025-11-01','2025-12-31')}))
    training_calendar = add_official_calendar_features(model_data[['date']].drop_duplicates())
    report['calendar_unseen'] = {name: {'training_values': sorted(training_calendar[name].unique().tolist()),
        'future_values':sorted(forecast_calendar[name].unique().tolist())} for name in HOLIDAY_MODEL_COLUMNS
        if set(forecast_calendar[name]) - set(training_calendar[name])}
    report['forecast_months_unseen'] = [11,12]
    all_frames = []
    with threadpool_limits(limits=4):
        for fold, cutoff, start, end in FOLDS:
            begin = time.monotonic()
            history = model_data[model_data.date.le(pd.Timestamp(cutoff))]
            # S3 also reproduces the legacy 62-day window without another fit.
            predict_end = '2025-08-31' if fold == 'S3' else end
            actual = model_data[model_data.date.between(start, predict_end)][['route','date','hour','boardings']]
            frame = actual.copy()
            fit = {}
            for name, column in [('calendar_holiday_hgbt','calendar'),('calendar_interaction_squared_hgbt','interaction')]:
                model = build_hgbt_model(name).fit(history)
                pred = model.predict(start, predict_end)
                frame = frame.merge(pred[['route','date','hour','prediction']].rename(columns={'prediction':column}),
                    on=['route','date','hour'], validate='one_to_one')
                estimator = model.pipeline_ if column == 'interaction' else model.pipeline_['regressor']
                fit[column] = {'iterations':int(estimator.n_iter_), 'internal_early_stopping':bool(estimator.do_early_stopping_)}
            frame['ensemble'] = .96 * (.425*frame.calendar + .575*frame.interaction)
            frame['fold'] = fold
            frame['horizon_day'] = (frame.date-pd.Timestamp(start)).dt.days+1
            assert len(frame) == len(actual) and not frame.isna().any().any()
            if fold == 'S3':
                report['legacy_S3_62_days'] = {column:metrics(frame,column) for column in ['calendar','interaction','ensemble']}
                frame[frame.horizon_day.eq(62)].to_csv(output/'legacy-day62.csv',index=False)
                frame = frame[frame.horizon_day.le(61)].copy()
            assert frame.horizon_day.nunique() == 61 and len(frame) == 9*61*24
            report['folds'].append({'fold':fold,'train_end':cutoff,'start':start,'end':end,'fit':fit,
                **{column:metrics(frame,column) for column in ['calendar','interaction','ensemble']},
                'elapsed_seconds':round(time.monotonic()-begin,3)})
            all_frames.append(frame)
            print(json.dumps(report['folds'][-1], ensure_ascii=False), flush=True)
    predictions = pd.concat(all_frames,ignore_index=True)
    predictions.to_csv(output/'predictions.csv',index=False)
    for scope, frame in [('selection',predictions[predictions.fold.ne('D')]),('diagnostic',predictions[predictions.fold.eq('D')])]:
        total = metrics(frame)
        frame = frame.copy()
        frame['abs_error'] = np.abs(frame.boardings - round_submission_predictions(frame.ensemble))
        frame['weekend'] = frame.date.dt.dayofweek.ge(5)
        frame['night_00_05'] = frame.hour.between(0,4)
        frame['night_00_06'] = frame.hour.between(0,5)
        frame['horizon'] = pd.cut(frame.horizon_day,[0,7,30,61],labels=['1-7','8-30','31-61'])
        slices = []
        for col in ['route','weekend','night_00_05','night_00_06','horizon','hour']:
            for value, part in frame.groupby(col,observed=True):
                score = metrics(part)
                slices.append({'slice':col,'value':str(value), **score,
                    'error_share':score['sum_abs_error']/total['sum_abs_error'],
                    'max_score_gain_if_perfect':score['sum_abs_error']/total['sum_y']})
        route_days = frame.groupby(['fold','route','date'],as_index=False).agg(y=('boardings','sum'),
            prediction=('ensemble','sum'),abs_error=('abs_error','sum'))
        route_days.nlargest(30,'abs_error').to_csv(output/f'{scope}-top-route-days.csv',index=False)
        report[scope] = {'metrics':total,'slices':slices,
            'components':{c:metrics(frame,c) for c in ['calendar','interaction','ensemble']}}
        frame['rounded'] = round_submission_predictions(frame.ensemble)
        grouped = frame.groupby(['fold','route','date'])
        totals = grouped[['boardings','rounded']].sum()
        daily_error_bound = float((totals.boardings-totals.rounded).abs().sum())
        true_total = grouped.boardings.transform('sum')
        raw_total = grouped.ensemble.transform('sum')
        oracle = np.divide(frame.ensemble*true_total,raw_total,
            out=np.zeros(len(frame)),where=raw_total.to_numpy()>0)
        report[scope]['error_structure'] = {
            'daily_total_error_lower_bound': daily_error_bound,
            'share_error_from_daily_total_lower_bound': daily_error_bound/total['sum_abs_error'],
            'oracle_true_daily_total_score': regression_metrics(frame.boardings,round_submission_predictions(oracle))['wape_score'],
            'oracle_warning': 'Uses future actual daily totals. Diagnostic only; not a candidate or performance claim.',
            'unscaled_fixed_ensemble_score_diagnostic_only': regression_metrics(frame.boardings,round_submission_predictions(frame.ensemble/.96))['wape_score'],
        }
        pd.DataFrame(slices).to_csv(output/f'{scope}-slices.csv',index=False)
    # This diagnostic is an oracle bound, never a proposed prediction rule.
    diagnostic = predictions[predictions.fold.eq('D')].copy()
    for label, condition in [('zero_target', diagnostic.boardings.eq(0)),
                             ('route_50_day_2025_09_14',diagnostic.route.eq(50)&diagnostic.date.eq(pd.Timestamp('2025-09-14')))]:
        report.setdefault('oracle_bounds_diagnostic',{})[label] = {
            'rows':int(condition.sum()),
            'max_gain':float(np.abs(diagnostic.loc[condition,'boardings'] - round_submission_predictions(diagnostic.loc[condition,'ensemble'])).sum()/diagnostic.boardings.sum())}
    (output/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Saved read-only audit:', output, flush=True)


if __name__ == '__main__':
    main()
