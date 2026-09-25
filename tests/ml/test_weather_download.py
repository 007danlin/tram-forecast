import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import pandas as pd

from ml.factors import WEATHER_REQUIRED_COLUMNS, WEATHER_UNITS, normalize_open_meteo_snapshot
from ml.weather import fetch_weather


def payload(end='2025-01-01'):
    stamps = pd.date_range('2025-01-01',pd.Timestamp(end)+pd.Timedelta(hours=23),freq='h')
    return {'timezone':'Europe/Moscow','utc_offset_seconds':10800,'latitude':55.75,'longitude':37.5,
            'hourly_units':WEATHER_UNITS,
            'hourly':{'time':stamps.strftime('%Y-%m-%dT%H:%M').tolist(), **{c:[float(i%5) for i in range(len(stamps))] for c in WEATHER_REQUIRED_COLUMNS}}}


def response(data):
    return 200,{},json.dumps(data).encode()


class WeatherDownloadTests(unittest.TestCase):
    def test_receipt_offline_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'snapshot'
            report=fetch_weather('2025-01-01','2025-01-01',root,send=lambda _:response(payload()))
            self.assertEqual(report['target']['available_hours'],24)
            manifest=json.loads((root/'manifest.json').read_text())
            self.assertIsNotNone(manifest['fetched_at'])
            blocked=Mock(side_effect=AssertionError('Offline must not connect'))
            self.assertEqual(report,fetch_weather('2025-01-01','2025-01-01',root,offline=True,send=blocked))
            blocked.assert_not_called()
            with self.assertRaisesRegex(ValueError,'exists'):
                fetch_weather('2025-01-01','2025-01-01',root)
            (root/'raw.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'checksum'):
                fetch_weather('2025-01-01','2025-01-01',root,offline=True,send=blocked)

    def test_retries_and_retry_after_bound(self):
        for errors in ((429,500),(TimeoutError(),500)):
            with self.subTest(errors=errors), tempfile.TemporaryDirectory() as tmp:
                sequence=[(x,{'Retry-After':'0'},b'{}') if isinstance(x,int) else x for x in errors]+[response(payload())]
                send=Mock(side_effect=sequence); sleep=Mock()
                fetch_weather('2025-01-01','2025-01-01',Path(tmp)/'snapshot',send=send,sleep=sleep)
                self.assertEqual(send.call_count,3)
        for status, headers in ((400,{}),(429,{'Retry-After':'3600'})):
            with tempfile.TemporaryDirectory() as tmp:
                send=Mock(return_value=(status,headers,b'{}'))
                with self.assertRaises(ValueError):
                    fetch_weather('2025-01-01','2025-01-01',Path(tmp)/'snapshot',send=send,sleep=Mock())
                self.assertEqual(send.call_count,1)
                self.assertFalse((Path(tmp)/'snapshot').exists())

    def test_invalid_provider_data_retains_diagnostics_without_snapshot(self):
        for defect in ('missing_hour','duplicate','timezone','units','nan','inf','negative','missing_gusts','null','api_error'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as tmp:
                data=payload()
                if defect == 'missing_hour':
                    for col in data['hourly']: data['hourly'][col].pop()
                elif defect == 'duplicate': data['hourly']['time'][-1]=data['hourly']['time'][0]
                elif defect == 'timezone': data['timezone']='UTC'
                elif defect == 'units': data['hourly_units']={**WEATHER_UNITS,'wind_speed_10m':'m/s'}
                elif defect in ('nan','inf','negative','null'): data['hourly']['precipitation'][2]={'nan':float('nan'),'inf':float('inf'),'negative':-1,'null':None}[defect]
                elif defect == 'missing_gusts': del data['hourly']['wind_gusts_10m']
                else: data['error']=True
                target=Path(tmp)/'snapshot'
                with self.assertRaises(ValueError):
                    fetch_weather('2025-01-01','2025-01-01',target,send=lambda _:response(data))
                self.assertFalse(target.exists())
                diagnostic=next(Path(tmp).glob('snapshot.failed-*'))
                self.assertTrue((diagnostic/'raw.json').exists())
                self.assertFalse(json.loads((diagnostic/'coverage.json').read_text())['passed'])

    def test_shift_uses_buffer_but_target_stays_one_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'snapshot'
            data=payload('2025-01-02')
            fetch_weather('2025-01-01','2025-01-01',root,alignment='next_hour_accumulation_v2',send=lambda _:response(data))
            normalized=pd.read_csv(root/'normalized.csv',sep=';')
            self.assertEqual(len(normalized),24)
            self.assertEqual(normalized.iloc[0]['precipitation'],1)
            self.assertEqual(normalized.iloc[0]['temperature_2m'],0)
            self.assertEqual(normalized.iloc[-1]['precipitation'],4)
            fetch_weather('2025-01-01','2025-01-01',root,offline=True)

    def test_full_year_grid_and_splits(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=fetch_weather('2025-01-01','2025-12-31',Path(tmp)/'snapshot',send=lambda _:response(payload('2025-12-31')))
            self.assertEqual(report['target']['expected_hours'],8760)
            self.assertEqual([part['available_hours'] for part in report['splits'].values()],[5832,1464,1464])

    def test_legacy_file_mtime_is_not_acquisition_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'raw.json').write_text(json.dumps(payload()))
            normalize_open_meteo_snapshot(root/'raw.json',root/'out.csv',root/'manifest.json',source_url='https://example.test')
            manifest=json.loads((root/'manifest.json').read_text())
            self.assertIsNone(manifest['raw_snapshot']['fetched_at'])
            self.assertIn('file_mtime',manifest['raw_snapshot'])


if __name__ == '__main__': unittest.main()
