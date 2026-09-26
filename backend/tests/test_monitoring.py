"""Synthetic collector contracts and failure modes; these tests do not use the network."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from io import BytesIO

from backend.monitoring.collectors import (MET, MSK, CALENDAR, collect, parse_calendar, parse_closures, parse_changes,
    parse_events, parse_met, parse_open_meteo, parse_deptrans, record, timestamp)
from backend.monitoring.service import Fetcher, FetchError, Monitor

NOW=datetime(2026,9,26,16,tzinfo=timezone.utc)


def met_payload():
    return {'properties': {'meta': {'updated_at':NOW.isoformat(), 'units':{
        'air_temperature':'celsius','precipitation_amount':'mm','wind_speed':'m/s'}},'timeseries':[
        {'time':(NOW+timedelta(hours=i)).isoformat(), 'data':{
            'instant': {'details':{'air_temperature':10+i/10,'wind_speed':2}},
            'next_1_hours':{'details':{'precipitation_amount':.1},'summary':{'symbol_code':'cloudy'}}}}
        for i in range(48)]}}


def closures():
    return '''<input id="search_road_closures_dateFrom" value="26.09.2026">
<input id="search_road_closures_dateTo" value="26.09.2026">
<div class="closures_item" data-id="x"><div>Тестовая улица</div><div>с 25.09.2026 по 27.09.2026</div></div>
<div class="closures_cont" id="item-x"><div>Перекрыто полос: 1 из 2</div></div>'''.encode()


def change(mode='avt-ds'):
    return f'''<div class="transport-item-ds"><div class="route-line"><p>26.09.2026</p>
<div class="route-list"><span class="{mode}">7, 50</span></div></div>
<a href="/routes/changes/test/"><h6>Временное изменение</h6></a>
<span class="date-pub-ds">Опубликовано: 01.09.2026</span></div>'''.encode()


def event_payload():
    return {'count':1,'next':None,'results':[{'id':1,'site_url':'https://kudago.com/msk/event/test/',
        'title':'Тестовое событие','publication_date':int((NOW-timedelta(days=2)).timestamp()),
        'dates':[{'start':int(NOW.timestamp()),'end':int((NOW+timedelta(hours=2)).timestamp())}],
        'place':{'title':'Тестовая площадка','address':'Тестовая, 1','coords':{'lat':55.75,'lon':37.61}}}]}


def calendar(period='26 сентября', year=2026):
    return f'''<div class="tn-atom">{year}</div>
<div class="t-rec"><a name="s-26"></a></div>
<div class="t-rec uc-header-1"><div class="t-text">{period}</div></div>
<div class="t-rec uc-header-2"><div class="t-text">Тестовое мероприятие</div></div>
<div class="t-rec uc-header-3"><div class="t-text">Перекрытия</div></div>
<div class="t-rec"><meta itemprop="image" content="https://static.tildacdn.com/test/map.png"></div>'''.encode()


class CollectorTests(unittest.TestCase):
    def test_calendar_preserves_days_and_images_without_inventing_publication_or_routes(self):
        rows, coverage = parse_calendar(calendar(), NOW)
        r = rows[0]
        self.assertEqual(r['valid_start'], '2026-09-26T00:00:00+03:00')
        self.assertEqual(r['valid_end'], '2026-09-27T00:00:00+03:00')
        self.assertEqual(r['source_url'], CALENDAR+'#s-26')
        self.assertIsNone(r['published_at'])
        self.assertEqual(r['route_link']['status'], 'unknown')
        self.assertEqual(r['location']['status'], 'city_only')
        self.assertEqual(len(r['values']['infographic_urls']), 1)
        self.assertFalse(coverage['complete'])
        rows,_=parse_calendar(calendar('10 апреля – 27 сентября'),NOW)
        self.assertEqual(rows[0]['valid_end'], '2026-09-28T00:00:00+03:00')
        urls=[]
        collect('changes', lambda u: urls.append(u) or calendar(), NOW)
        self.assertEqual(urls,[CALENDAR])

    def test_calendar_rejects_stale_year_expired_sections_and_changed_structure(self):
        for html in [calendar(year=2025), calendar('25 сентября'), calendar('27 сентября – 26 сентября'),
                     calendar('неизвестный период'), calendar().replace(b'uc-header-2',b'unknown'),
                     calendar().replace(b'https://static.tildacdn.com/',b'https://evil.invalid/')]:
            with self.subTest(html=html), self.assertRaises(ValueError):parse_calendar(html,NOW)

    def test_weather_units_provenance_and_no_route_invention(self):
        rows,coverage=parse_met(json.dumps(met_payload()).encode(),NOW)
        self.assertEqual(len(rows),48);self.assertTrue(coverage['complete'])
        self.assertEqual(rows[0]['values']['precipitation_period'],'next_hour')
        for r in rows:
            self.assertEqual(r['information_mode'],'operational'); self.assertEqual(r['forecast_effect'],'not_applied')
            self.assertEqual(r['route_link'],{'status':'unknown','route_ids':[],'method':None})
            self.assertEqual(timestamp(r['fetched_at']),NOW)

    def test_weather_rejects_stale_nonfinite_units_and_missing_grid(self):
        payloads=[]
        p=met_payload();p['properties']['meta']['units']['wind_speed']='km/h';payloads.append(p)
        p=met_payload();p['properties']['meta']['updated_at']=(NOW-timedelta(days=2)).isoformat();payloads.append(p)
        p=met_payload();p['properties']['timeseries'].pop(3);payloads.append(p)
        p=met_payload();p['properties']['timeseries'].reverse();payloads.append(p)
        p=met_payload();p['properties']['timeseries'][0]['data']['instant']['details']['air_temperature']=float('nan');payloads.append(p)
        for p in payloads:
            with self.subTest(p=p['properties']['meta']),self.assertRaises(ValueError): parse_met(json.dumps(p).encode(),NOW)

    def test_open_meteo_hourly_alignment_and_finite_values(self):
        start=NOW.astimezone(MSK).replace(hour=0)
        p={'timezone':'Europe/Moscow','utc_offset_seconds':10800,
           'hourly_units':{'temperature_2m':'°C','wind_speed_10m':'m/s','precipitation':'mm'},
           'hourly':{'time':[(start+timedelta(hours=i)).replace(tzinfo=None).isoformat() for i in range(72)],
                     'temperature_2m':[10]*72,'wind_speed_10m':[2]*72,'precipitation':[.1]*72}}
        rows,_=parse_open_meteo(json.dumps(p).encode(),NOW)
        self.assertEqual(rows[0]['values']['precipitation_period'],'preceding_hour')
        p['hourly']['time'][5]=p['hourly']['time'][4]
        with self.assertRaises(ValueError):parse_open_meteo(json.dumps(p).encode(),NOW)

    def test_closure_inclusive_day_and_unknown_routes(self):
        rows,_=parse_closures(closures(),NOW);r=rows[0]
        self.assertEqual(r['valid_end'],'2026-09-28T00:00:00+03:00')
        self.assertEqual(r['location']['name'],'Тестовая улица')
        self.assertEqual(r['route_link']['status'],'unknown')
        self.assertIn('1 из 2',r['values']['restriction'])
        rows,_=parse_closures(closures().replace(' по 27.09.2026'.encode(),b''),NOW)
        self.assertIsNone(rows[0]['valid_end'])
        with self.assertRaises(ValueError):parse_closures(closures(),NOW+timedelta(days=1))
        with self.assertRaises(ValueError):parse_closures(b'<html>Maintenance</html>',NOW)

    def test_bus_numbers_and_publication_not_promoted_to_tram_or_validity(self):
        r=parse_changes(change(),NOW)[0]
        self.assertEqual(r['route_link']['route_ids'],[])
        self.assertEqual(r['published_at'],'2026-09-01T00:00:00+03:00')
        self.assertIsNone(r['valid_start']);self.assertIsNone(r['valid_end'])
        self.assertEqual(r['location']['status'],'unknown')
        r=parse_changes(change('tram-ds'),NOW)[0]
        self.assertEqual(set(r['route_link']['route_ids']),{'7','50'})
        with self.assertRaises(ValueError):parse_changes(change().replace(b'/routes/changes/test/',b'https://evil.invalid/'),NOW)

    def test_deptrans_reply_excludes_quote_and_links_reopening(self):
        html="""<div class="tgme_widget_message" data-post="DtOperativno/100">
        <a class="tgme_widget_message_reply" href="https://t.me/DtOperativno/99">
        <div class="tgme_widget_message_text">Трамваи 7 и 50 не идут</div></a>
        <div class="tgme_widget_message_text">Движение открыто на Тестовой улице.</div>
        <time datetime="2026-09-26T15:00:00+00:00"></time></div>"""
        rows,_=parse_deptrans(html.encode(),NOW)
        self.assertEqual(rows[0]['route_link']['route_ids'],[])
        self.assertEqual(rows[0]['values']['notice_kind'],'reopening')
        self.assertEqual(rows[0]['values']['related_source_urls'],['https://t.me/DtOperativno/99'])
        self.assertIsNone(rows[0]['valid_start'])
        html=html.replace('Движение открыто на Тестовой улице.',
            'Завтра с 08:00 до 17:30 трамваи 7 и 50 будут изменены. Автобусы 13 идут обычно.')
        r=parse_deptrans(html.encode(),NOW)[0][0]
        self.assertEqual(set(r['route_link']['route_ids']),{'7','50'})
        self.assertEqual(r['valid_start'],'2026-09-27T08:00:00+03:00')
        self.assertEqual(r['valid_end'],'2026-09-27T17:30:00+03:00')
        with self.assertRaises(ValueError):parse_deptrans(b'<html>Login required</html>',NOW)

    def test_event_open_dates_schedule_and_unverified_route(self):
        p=event_payload();rows=parse_events(p,NOW)
        self.assertEqual(rows[0]['period_precision'],'provider_schedule')
        self.assertEqual(rows[0]['location']['lat'],55.75)
        p['results'][0]['dates']=[{'start':-62135433000,'end':253370754000}]
        r=parse_events(p,NOW)[0]
        self.assertIsNone(r['valid_start']);self.assertIsNone(r['valid_end'])
        self.assertEqual(r['period_precision'],'open_schedule'); self.assertEqual(r['route_link']['status'],'unknown')
        p['results'][0]['site_url']='javascript:alert(1)'
        with self.assertRaises(ValueError):parse_events(p,NOW)

    def test_event_pagination_dedup_and_partial_coverage(self):
        def fetch(url):
            page=int(url.split('page=')[-1]);p=event_payload()
            p['results'][0]['id']=page;p['count']=21;p['next']='https://evil.invalid/ignored'
            self.assertTrue(url.startswith('https://kudago.com/public-api/'))
            return json.dumps(p).encode()
        rows,coverage=collect('events',fetch,NOW)
        self.assertEqual(len(rows),20); self.assertFalse(coverage['complete'])
        self.assertEqual(coverage['pages'],20)
        p=event_payload();p['count']=2;p['next']='ignored'
        with self.assertRaises(ValueError):collect('events',lambda _:json.dumps(p).encode(),NOW)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        class FakeFetch:
            expires=None; weather_cache=None
            def __init__(self,*args):pass
            def __call__(self,url):return json.dumps(met_payload()).encode()
        self.monitor=Monitor(self.root,fetcher_factory=FakeFetch)

    def refresh(self):
        with patch('backend.monitoring.service.utcnow',return_value=NOW):self.monitor.refresh('weather')

    def test_restart_checksum_freshness_and_no_forecast_effect(self):
        self.refresh();r=self.monitor.rows['weather']; self.assertEqual(len(r),48)
        reload=Monitor(self.root)
        self.assertEqual(reload.rows['weather'],r)
        self.assertEqual(reload.view(NOW)['sources'][0]['status'],'fresh')
        self.assertEqual(reload.view(NOW+timedelta(hours=4))['sources'][0]['status'],'stale')
        self.assertFalse(reload.view(NOW)['historical']['external_live_join'])
        snapshot=self.root/'weather'/'snapshots'/reload.states['weather']['snapshot']/'records.json'
        snapshot.write_text('[]')
        damaged=Monitor(self.root)
        self.assertEqual(damaged.rows['weather'],[])
        self.assertEqual(damaged.view(NOW)['sources'][0]['status'],'error')

    def test_network_failure_retains_good_snapshot_and_survives_restart(self):
        self.refresh();before=copy.deepcopy(self.monitor.rows['weather'])
        with patch('backend.monitoring.service.collect',side_effect=FetchError('HTTP 429',NOW+timedelta(hours=8))),patch('backend.monitoring.service.utcnow',return_value=NOW+timedelta(hours=1)):
            self.monitor.refresh('weather')
        self.assertEqual(self.monitor.rows['weather'],before)
        state=self.monitor.view(NOW+timedelta(hours=1))['sources'][0]
        self.assertEqual(state['status'],'error');self.assertEqual(state['last_success_at'],NOW.isoformat())
        self.assertGreaterEqual(timestamp(state['next_refresh_at']),NOW+timedelta(hours=8))
        reload=Monitor(self.root)
        self.assertEqual(reload.rows['weather'],before);self.assertEqual(reload.states['weather']['error'],'HTTP 429')
        self.refresh();self.assertIsNone(self.monitor.states['weather']['error'])

    def test_provider_change_does_not_relabel_old_weather(self):
        self.refresh();other=Monitor(self.root,weather_provider='open_meteo')
        self.assertEqual(other.rows['weather'],[])
        self.assertEqual(other.view(NOW)['sources'][0]['provider'],'Open-Meteo')

    def test_lagging_publications_disabled_and_hidden_traffic(self):
        m=self.monitor
        m.states['changes'].update(last_success_at=NOW.isoformat(),coverage={'latest_publication':(NOW-timedelta(days=8)).isoformat()})
        self.assertEqual(m.view(NOW)['sources'][2]['status'],'lagging')
        self.assertEqual(len(m.view(NOW)['sources']),4)
        m.enabled=False;self.assertEqual(m.view(NOW)['sources'][0]['status'],'disabled')

    def test_removed_traffic_does_not_reuse_old_telegram_records(self):
        m=self.monitor
        row=record('changes','1','Traffic',NOW,url='https://t.me/DtOperativno/1',
            published=(NOW-timedelta(hours=3)).isoformat(),values={'traffic_bulletin':{'road_load_score':6}})
        m.states['changes'].update(last_success_at=NOW.isoformat())
        m.rows['changes']=[row]
        self.assertNotIn('traffic',[s['id'] for s in m.view(NOW)['sources']])
        self.assertEqual(m.records('traffic')['records'],[])
        self.assertEqual(m.records('traffic')['collection_status'],'not_connected')

    def test_provider_replacement_drops_old_records_and_failure_backoff(self):
        legacy=[record('changes','old','Old bulletin',NOW,url='https://t.me/DtOperativno/1')]
        with patch('backend.monitoring.service.collect',return_value=(legacy,{})):
            self.monitor.refresh('changes')
        path=self.root/'changes/current.json'
        state=json.loads(path.read_text());state['source_url']='https://t.me/s/DtOperativno'
        path.write_text(json.dumps(state))
        failure={'last_attempt_at':(NOW+timedelta(days=1)).isoformat(), 'next_refresh_at':(NOW+timedelta(days=2)).isoformat(),
                 'error':'Old Telegram timeout', 'failures':5}
        (self.root/'changes/failure.json').write_text(json.dumps(failure))
        m=Monitor(self.root)
        self.assertEqual(m.rows['changes'],[])
        self.assertIsNone(m.states['changes']['next_refresh_at'])
        path.unlink()
        self.assertIsNone(Monitor(self.root).states['changes']['error'])

    def test_calendar_becomes_stale_when_announced_period_ends(self):
        self.monitor.states['changes'].update(last_success_at=NOW.isoformat(),coverage={'window_end':NOW.isoformat()})
        self.assertEqual(self.monitor.view(NOW)['sources'][2]['status'],'stale')

    def test_single_collector_owner_and_disabled_no_acquisition(self):
        self.assertTrue(self.monitor.acquire());other=Monitor(self.root)
        self.assertFalse(other.acquire()); self.monitor.owner.close()
        async def check():
            m=Monitor(self.root,enabled=False)
            await m.start();self.assertEqual(m.tasks,[]);await m.close()
        asyncio.run(check())

    def test_worker_collects_without_browser_and_honors_saved_schedule(self):
        async def check():
            m=self.monitor; m.sources=m.sources[:1]
            with patch('backend.monitoring.service.utcnow',return_value=NOW):
                await m.start()
                for _ in range(100):
                    if m.rows['weather']:break
                    await asyncio.sleep(.005)
                self.assertEqual(len(m.rows['weather']),48)
                first=m.states['weather']['snapshot']
                await asyncio.sleep(.02)
                self.assertEqual(m.states['weather']['snapshot'],first)
                await m.close()
                self.assertIsNone(m.owner)
        asyncio.run(check())

    def test_atomic_snapshot_failure_keeps_previous_state(self):
        self.refresh();before=self.monitor.rows['weather']
        with patch('backend.monitoring.service.write_json',side_effect=OSError('disk full')):self.refresh()
        self.assertEqual(self.monitor.rows['weather'],before)
        self.assertEqual(self.monitor.view(NOW)['sources'][0]['status'],'error')

    def test_retention_keeps_last_good_snapshot_during_failures(self):
        self.refresh();name=self.monitor.states['weather']['snapshot']
        for i in range(55):
            with patch('backend.monitoring.service.collect',side_effect=ValueError('bad')):self.refresh()
        self.assertTrue((self.root/'weather'/'snapshots'/name/'records.json').exists())
        self.assertLessEqual(len(list((self.root/'weather'/'snapshots').iterdir())),49)

    def test_http_304_reuses_bytes_with_provenance_and_header(self):
        raw=json.dumps(met_payload()).encode();cachepath=self.root/'old.bin';cachepath.write_bytes(raw)
        cache={'path':str(cachepath),'sha256':hashlib.sha256(raw).hexdigest(),'last_modified':'Sat, 26 Sep 2026 13:00:00 GMT'}
        error=HTTPError(MET,304,'Not modified',{'Expires':'Sat, 26 Sep 2026 18:00:00 GMT'},BytesIO())
        fetcher=Fetcher(self.root,cache)
        with patch('backend.monitoring.service.urlopen',side_effect=error) as request:
            self.assertEqual(fetcher(MET),raw)
            self.assertEqual(request.call_args.args[0].get_header('If-modified-since'),cache['last_modified'])
        self.assertEqual(fetcher.receipts[0]['http_status'],304)
        self.assertEqual(fetcher.weather_cache['sha256'],cache['sha256'])

    def test_size_limit_and_429_retry_after(self):
        class HugeResponse(BytesIO):
            code=200
            headers={'Content-Length':str(6*1024*1024)}
        with patch('backend.monitoring.service.urlopen',return_value=HugeResponse()),self.assertRaises(FetchError):
            Fetcher(self.root)(MET)

        error=HTTPError(MET,429,'Rate limit',{'Retry-After':'7200'},BytesIO())
        with patch('backend.monitoring.service.urlopen',side_effect=error),self.assertRaises(FetchError) as e:
            Fetcher(self.root)(MET)
        self.assertIsNotNone(e.exception.retry_after)


if __name__=='__main__': unittest.main()
