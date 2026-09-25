import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.artifact import create_artifact, load_artifact, predict_artifact
from ml.experiment_config import normalize_config
from ml.evaluation import weather_guardrail, run_weather_selection, _merge_actual_prediction
from ml.factors import load_weather_factors, WEATHER_MODEL_COLUMNS
from ml.model import build_hgbt_model
from ml.settings import FINAL_HOLDOUT
from test_model import synthetic_history


class WeatherExperimentsTests(unittest.TestCase):
    def test_disabled_fields_are_not_required_at_fit_or_predict(self):
        config=normalize_config({'id':'W01','weather_groups':['temperature']})
        model=build_hgbt_model(config['model_name'],config)
        model.max_iter=3
        stamps=pd.date_range('2025-01-01','2025-03-01 23:00',freq='h')
        factors=pd.DataFrame({'timestamp':stamps,'temperature_2m':1.,'apparent_temperature':2.})
        model.fit(synthetic_history(),factors)
        self.assertEqual(model.selected_weather_columns,('temperature_2m','apparent_temperature'))
        self.assertEqual(len(model.predict('2025-03-01','2025-03-01',factors)),240)
        with self.assertRaises(ValueError):
            model.predict('2025-03-01','2025-03-01',factors.iloc[:-1])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'temperature.csv'; factors.to_csv(path,sep=';',index=False)
            self.assertEqual(list(load_weather_factors(path,model.selected_weather_columns).columns),['timestamp','temperature_2m','apparent_temperature'])

    def test_full_config_preserves_original_feature_order(self):
        config=normalize_config({'id':'W05','weather_groups':['temperature','precipitation','snow','wind']})
        self.assertEqual(config['weather_columns'],list(WEATHER_MODEL_COLUMNS))
        with self.assertRaises(ValueError): normalize_config({**config,'weather_columns':['precipitation']})

    def test_route_guardrail_rejects_gain_that_harms_one_route(self):
        actual=synthetic_history().iloc[:240].copy()
        predicted=actual[['route','date','hour']].copy(); predicted['prediction']=actual['boardings']+10; predicted['status']='ok'
        baseline=_merge_actual_prediction(actual,predicted)
        candidate=baseline.copy(); candidate['prediction']=candidate['boardings']+9
        self.assertTrue(weather_guardrail([candidate,candidate],[baseline,baseline])['passed'])
        candidate['prediction']=candidate['boardings']+11
        self.assertFalse(weather_guardrail([candidate,candidate],[baseline,baseline])['passed'])
        candidate.loc[0,'boardings']+=1
        with self.assertRaises(ValueError): weather_guardrail([candidate],[baseline])

    def test_artifact_roundtrip_keeps_config_interval_and_offline_factors(self):
        config=normalize_config({'id':'W01','weather_groups':['temperature']})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); dataset=root/'data'; dataset.mkdir(); (dataset/'labels').mkdir()
            for name in ('README.md','train.csv','test.csv','test_submission.csv','labels/labels_day_train.csv','labels/labels_day_test.csv'):
                (dataset/name).write_text('synthetic test source')
            weather=root/'weather.csv'
            pd.DataFrame({'timestamp':pd.date_range('2025-01-01','2025-03-01 23:00',freq='h'),'temperature_2m':1.,'apparent_temperature':2.}).to_csv(weather,sep=';',index=False)
            from ml.factors import sha256_file
            manifest={'alignment':config['alignment'],'normalized':{'sha256':sha256_file(weather)}}
            def small_model(name,experiment):
                model=build_hgbt_model(name,experiment); model.max_iter=3; return model
            with patch('ml.artifact.load_organizer_labels',return_value=synthetic_history()), patch('ml.artifact.build_hgbt_model',side_effect=small_model):
                create_artifact(dataset,root/'artifact',model_name=config['model_name'],interval_absolute_error_q90=3.25,
                                factor_path=weather,experiment_config=config,snapshot_manifest=manifest)
            payload,metadata=load_artifact(root/'artifact')
            self.assertEqual(payload['interval_absolute_error_q90'],3.25)
            self.assertEqual(metadata['experiment_config'],config)
            before=predict_artifact(root/'artifact','2025-03-01','2025-03-01')
            weather.unlink()
            with patch('socket.socket',side_effect=AssertionError('Offline inference')):
                after=predict_artifact(root/'artifact','2025-03-01','2025-03-01')
            pd.testing.assert_frame_equal(before,after)
            with self.assertRaisesRegex(ValueError,'exists'):
                create_artifact(dataset,root/'artifact',model_name=config['model_name'],interval_absolute_error_q90=3.25)

    def test_selection_never_evaluates_holdout_and_keeps_selected_q90(self):
        config=json.loads((Path(__file__).parents[2]/'ml/experiments/weather-groups.json').read_text())
        calls=[]
        def evaluate(dataset,fold,name,factors=None,experiment_config=None):
            self.assertNotEqual(fold,FINAL_HOLDOUT); calls.append(experiment_config['id'])
            actual=synthetic_history().iloc[:240].copy()
            predicted=actual[['route','date','hour']].copy(); predicted['prediction']=actual['boardings']+(1 if experiment_config['id']=='W01' else 2); predicted['status']='ok'
            merged=_merge_actual_prediction(actual,predicted)
            return {'config':experiment_config},merged
        with patch('ml.evaluation.evaluate_model',side_effect=evaluate):
            report,_=run_weather_selection('unused',config,None,{'alignment':'legacy_timestamp_v1'})
        self.assertEqual(report['selected_config']['id'],'W01')
        self.assertEqual(report['interval']['absolute_error_q90'],1)
        self.assertFalse(report['protocol']['holdout_opened'])
        self.assertEqual(len(calls),12)


if __name__ == '__main__': unittest.main()
