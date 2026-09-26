import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.artifact import create_artifact, predict_artifact, submission_preflight, write_submission
from ml.data import full_hourly_grid
from ml.experiment_config import normalize_config
from ml.model import build_hgbt_model
from ml.score_improvement import BASE_CONFIG, Runner, block_uncertainty, digest, guardrail, initialize_run, metrics, summarize
from ml.score_models import RecentProfile, ScoreModel, cat_features, score_config
from test_model import synthetic_history

HAS_CATBOOST = importlib.util.find_spec('catboost') is not None


class ScoreImprovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.limits = threadpool_limits(limits=2)
        cls.config = json.loads(Path('ml/experiments/score-improvement-v2.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.limits.restore_original_limits()

    def test_sparse_holiday_fallback_and_official_day_type(self):
        h = synthetic_history()
        p = RecentProfile(28).fit(h)
        future = full_hourly_grid('2025-03-08', '2025-03-08')
        # A Saturday holiday is comparable to official days off, never working Fridays.
        expected = p.values(future, np.full(len(future), 999.))
        self.assertTrue(np.isfinite(expected).all())
        self.assertTrue((expected[future.route == 5] == 0).all())
        short = h[h.date == h.date.max()]
        self.assertTrue((RecentProfile().fit(short).values(future, np.full(len(future), 999.)) == 999).all())

    def test_outer_future_targets_never_enter_models_or_preprocessing(self):
        whole = synthetic_history()
        cutoff = pd.Timestamp('2025-02-14')
        modified = whole.copy()
        modified.loc[modified.date > cutoff, 'boardings'] = 10000000
        configs = [score_config('hgbt','H',max_iter=3), score_config('profile','R',window=28,statistic='median')]
        if HAS_CATBOOST:
            configs.append(score_config('catboost','C',max_iter=4,inner_days=7,early_stopping_rounds=2))
        for c in configs:
            a = build_hgbt_model(c['model_name'],c).fit(whole[whole.date <= cutoff])
            b = build_hgbt_model(c['model_name'],c).fit(modified[modified.date <= cutoff])
            pd.testing.assert_frame_equal(a.predict('2025-02-15','2025-02-16'),b.predict('2025-02-15','2025-02-16'))
            if c['kind'] == 'hgbt':
                self.assertNotIn('month',a.feature_columns_)
            if c['kind'] == 'catboost':
                self.assertLess(pd.Timestamp(a.fit_details_['inner_train_end']), cutoff)

    def test_direct_profiles_are_frozen_before_each_origin(self):
        h = synthetic_history()
        c = score_config('direct','D',minimum_history=28,max_iter=3,inner_days=7)
        m = ScoreModel(c); m.history_end_ = h.date.max()
        a = m._direct_training(h,None)
        cutoff = pd.Timestamp('2025-01-28')
        changed = h.copy(); changed.loc[changed.date > cutoff,'boardings'] *= 100
        b = m._direct_training(changed,None)
        for data in (a,b):
            self.assertTrue((data._origin < data._date).all())
            self.assertTrue((data._date <= h.date.max()).all())
        np.testing.assert_array_equal(a.loc[a._origin == cutoff,'recent_profile'],b.loc[b._origin == cutoff,'recent_profile'])

    @unittest.skipUnless(HAS_CATBOOST, 'Optional CatBoost dependency is unavailable')
    def test_direct_fit_predict_with_and_without_rain(self):
        h = synthetic_history()
        factors = pd.DataFrame({'timestamp': pd.date_range('2025-01-01', '2025-03-02 23:00', freq='h'),
                                'precipitation': 0., 'is_wet': 0., 'precipitation_6h': 0.})
        for groups in ([], ['precipitation']):
            config = score_config('direct', 'D-smoke', minimum_history=28, inner_days=7,
                                  max_iter=5, early_stopping_rounds=2, weather_groups=groups)
            model = ScoreModel(config).fit(h, factors)
            result = model.predict('2025-03-01', '2025-03-02', factors)
            self.assertEqual(len(result), 480)
            self.assertTrue(np.isfinite(result.prediction).all())
            self.assertTrue((result.loc[result.route == 5, 'prediction'] == 0).all())
            self.assertIn('horizon_day', model.feature_columns_)
            self.assertIn('recent_profile', model.feature_columns_)
            with self.assertRaises(ValueError):
                model.predict('2025-03-01', '2025-05-01', factors)

    @unittest.skipUnless(HAS_CATBOOST, 'Optional CatBoost dependency is unavailable')
    def test_november_calendar_same_encoding_and_serialization(self):
        h = synthetic_history()
        c = score_config('catboost','C',iterations=3)
        m = ScoreModel(c).fit(h)
        future = full_hourly_grid('2025-11-01','2025-11-04')
        features = cat_features(future)
        self.assertEqual(set(features.loc[future.date == '2025-11-01','day_type']),{'0'})
        self.assertEqual(set(features.loc[future.date == '2025-11-03','day_type']),{'1'})
        self.assertNotIn('month',features.columns)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'model.joblib'; joblib.dump(m,path)
            pd.testing.assert_frame_equal(m.predict('2025-11-01','2025-11-04'), joblib.load(path).predict('2025-11-01','2025-11-04'))

    def _oof(self):
        frame = full_hourly_grid('2025-05-01','2025-06-30')
        frame['boardings'] = 100
        frame['prediction'] = 110.
        frame['horizon_day'] = (frame.date-frame.date.min()).dt.days+1
        return pd.concat([frame.assign(fold=f'S{i}') for i in range(1,5)],ignore_index=True)

    def test_global_metric_rounding_and_guardrails(self):
        base = self._oof()
        candidate = base.copy(); candidate['prediction'] = 109.49
        self.assertAlmostEqual(metrics(candidate)['score'],.91)
        self.assertAlmostEqual(metrics(candidate,False)['score'],.9051)
        self.assertTrue(guardrail(candidate,base,self.config['thresholds'])['passed'])
        candidate.loc[candidate.route == 28,'prediction'] = 112
        decision = guardrail(candidate,base,self.config['thresholds'])
        self.assertFalse(decision['passed']); self.assertIn('route_28_mae_regression',decision['reasons'])
        base['boardings'] = 0
        self.assertIsNone(metrics(base)['score'])

    def test_shared_calendar_blocks_and_mismatched_keys(self):
        a=self._oof(); b=a.copy(); a['prediction']=109
        result=block_uncertainty(a,b,123,repeats=50)
        self.assertEqual(result['blocks'],9)
        np.testing.assert_allclose(result['delta_score_interval_95'],[.01,.01])
        a.loc[0,'boardings']=101
        with self.assertRaises(ValueError): block_uncertainty(a,b,123)

    def test_fingerprint_guards_resume_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'run'; fp={'fingerprint':'abc','config':{}}
            initialize_run(output,fp)
            with self.assertRaises(ValueError): initialize_run(output,fp)
            initialize_run(output,fp,True)
            for key in ('data','sources','config'):
                changed={**fp,key:{'changed':True}}
                with self.assertRaises(ValueError): initialize_run(output,changed,True)

    def test_artifact_full_submission_and_unrounded_blend(self):
        h=synthetic_history()
        c=score_config('blend','E',components=[score_config('hgbt','H1',max_iter=3),score_config('hgbt','H2',max_iter=4)],weights=[.25,.75])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); dataset=root/'data'; (dataset/'labels').mkdir(parents=True)
            for name in ('README.md','train.csv','test.csv','labels/labels_day_train.csv','labels/labels_day_test.csv'):
                (dataset/name).write_text('synthetic fixture')
            template=full_hourly_grid('2025-11-01','2025-12-31'); template['prediction']=0
            template.to_csv(dataset/'test_submission.csv',sep=';',index=False)
            with patch('ml.artifact.load_organizer_labels',return_value=h):
                create_artifact(dataset,root/'artifact',model_name=c['model_name'],interval_absolute_error_q90=17.,experiment_config=c)
            predicted=predict_artifact(root/'artifact','2025-11-01','2025-12-31')
            self.assertTrue((predicted.loc[predicted.route==5,'prediction']==0).all())
            self.assertTrue((predicted.prediction % 1 != 0).any())
            pd.testing.assert_frame_equal(predicted,predict_artifact(root/'artifact','2025-11-01','2025-12-31'))
            path=root/'submission.csv'; write_submission(predicted,dataset/'test_submission.csv',path)
            self.assertTrue(submission_preflight(path,dataset/'test_submission.csv')['passed'])
            with self.assertRaises(ValueError): write_submission(predicted,dataset/'test_submission.csv',path)

    def test_fold_cache_reproduces_summary_and_rejects_corruption(self):
        h=synthetic_history()
        fold=dict(id='S1',train_start='2025-01-01',train_end='2025-02-14',start='2025-02-15',end='2025-02-28')
        cfg={**self.config,'folds':[fold]}
        c=score_config('hgbt','H',max_iter=3)
        with tempfile.TemporaryDirectory() as tmp:
            runner=Runner(h,cfg,tmp,'test-fingerprint')
            a,details=runner.evaluate('H',c,diagnostic=True)
            other=Runner(h,cfg,tmp,'test-fingerprint')
            b,other_details=other.evaluate('H',c,diagnostic=True)
            pd.testing.assert_frame_equal(a,b)
            self.assertEqual(details,other_details)
            path=Path(tmp)/'folds/H/S1/oof.csv'; path.write_text(path.read_text().replace('prediction','broken'))
            with self.assertRaises(ValueError): other.evaluate('H',c,diagnostic=True)


if __name__ == '__main__': unittest.main()
