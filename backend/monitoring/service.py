"""Background-only acquisition with bounded storage, cache, provenance and backoff."""
import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import fcntl
import gzip
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import random
import shutil
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .collectors import collect, iso, timestamp, MET, CLOSURES, CALENDAR

LOG = logging.getLogger(__name__)
MAX_BYTES = 5 * 1024 * 1024
USER_AGENT = 'TramFlow/1.0 (+https://github.com/MISISion-Possible/tram-forecast)'
SOURCES = [
    dict(id='weather', title='Погода', provider='MET Norway', url='https://api.met.no/weatherapi/locationforecast/2.0/documentation',
         interval_seconds=3600, stale_after_seconds=10800, needs_key=False,
         description='Температура, осадки и ветер для Москвы', attribution='MET Norway · CC BY 4.0 · значения приведены к общей схеме',
         license_url='https://creativecommons.org/licenses/by/4.0/'),
    dict(id='closures', title='Перекрытия', provider='Дептранс Москвы', url=CLOSURES,
         interval_seconds=1800, stale_after_seconds=7200, needs_key=False,
         description='Ограничения на дорогах, адреса и сроки'),
    dict(id='changes', title='Плановые изменения', provider='Календарь Дептранса', url=CALENDAR,
         interval_seconds=1800, stale_after_seconds=7200, needs_key=False,
         description='Даты ограничений и официальные схемы движения'),
    dict(id='events', title='Мероприятия', provider='KudaGo', url='https://kudago.com/msk/',
         interval_seconds=21600, stale_after_seconds=86400, needs_key=False,
         description='События, площадки и даты на ближайшие 14 дней'),
    dict(id='traffic', title='Пробки', provider='Яндекс Карты · кандидат', url='https://yandex.ru/maps/213/moscow/probki/',
         interval_seconds=300, stale_after_seconds=7200, needs_key=True,
         description='Проверенного доступного источника пока нет', blocked=True, hidden=True),
]


def utcnow():
    return datetime.now(timezone.utc)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class FetchError(ValueError):
    def __init__(self, message, retry_after=None):
        super().__init__(message); self.retry_after=retry_after


def retry_at(value):
    try:
        return utcnow()+timedelta(seconds=max(0,int(value)))
    except (ValueError, TypeError):
        try: return parsedate_to_datetime(value)
        except (TypeError, ValueError): return None


class Fetcher:
    def __init__(self, directory, cache=None):
        self.directory=directory; self.receipts=[]; self.cache=cache
        self.deadline=time.monotonic()+90
        self.expires=None; self.weather_cache=None

    def __call__(self, url):
        if time.monotonic() >= self.deadline:
            raise FetchError('Превышен лимит времени сбора (90 с)')
        headers={'User-Agent':USER_AGENT,'Accept':'application/json,text/html','Accept-Encoding':'gzip'}
        cached=self.cache if url==MET else None
        if cached and cached.get('last_modified'): headers['If-Modified-Since']=cached['last_modified']
        at=utcnow()
        receipt={'url':url,'requested_at':iso(at)}
        self.receipts.append(receipt)
        try:
            try:
                response=urlopen(Request(url,headers=headers),timeout=min(15,max(1,self.deadline-time.monotonic())))
            except HTTPError as exc:
                if exc.code == 304 and cached:
                    body=Path(cached['path']).read_bytes()
                    if hashlib.sha256(body).hexdigest()!=cached['sha256']: raise FetchError('Повреждён погодный кэш')
                    response=exc
                else:
                    retry=retry_at(exc.headers.get('Retry-After'))
                    exc.close()
                    raise FetchError(f'Источник вернул HTTP {exc.code}',retry) from exc
            with response:
                receipt['http_status']=response.code
                if response.code != 304:
                    if int(response.headers.get('Content-Length','0')) > MAX_BYTES:
                        raise FetchError('Ответ источника превышает 5 MiB')
                    body=response.read(MAX_BYTES+1)
                    if len(body)>MAX_BYTES: raise FetchError('Ответ источника превышает 5 MiB')
                    if response.headers.get('Content-Encoding')=='gzip':
                        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream: body=stream.read(MAX_BYTES+1)
                        if len(body)>MAX_BYTES: raise FetchError('Распакованный ответ превышает 5 MiB')
                receipt.update(fetched_at=iso(utcnow()),sha256=hashlib.sha256(body).hexdigest(),
                               bytes=len(body), last_modified=response.headers.get('Last-Modified'),
                               expires=response.headers.get('Expires'))
                if receipt['expires']:
                    with suppress(ValueError,TypeError): self.expires=parsedate_to_datetime(receipt['expires'])
                filename=f'raw-{len(self.receipts):02d}.bin'
                (self.directory/filename).write_bytes(body); receipt['file']=filename
                if url == MET:
                    self.weather_cache=dict(path=str(self.directory/filename),sha256=receipt['sha256'],
                                            last_modified=receipt['last_modified'] or (cached or {}).get('last_modified'))
                return body
        except (URLError, TimeoutError, OSError) as exc:
            receipt['error']=type(exc).__name__
            raise FetchError('Не удалось получить источник: сеть или TLS; проверка сертификата обязательна') from exc
        finally:
            write_json(self.directory/'requests.json', self.receipts)


class Monitor:
    def __init__(self, root, *, enabled=True, weather_provider='met', fetcher_factory=Fetcher):
        if weather_provider not in {'met','open_meteo'}: raise ValueError('Invalid weather provider')
        self.root=Path(root).resolve(); self.enabled=enabled; self.provider=weather_provider
        self.fetcher_factory=fetcher_factory; self.lock=threading.RLock(); self.refresh_locks={}
        self.states={}; self.rows={}; self.tasks=[]; self.owner=None; self.storage_error=None
        self.sources=[dict(s) for s in SOURCES]
        if weather_provider=='open_meteo':
            self.sources[0].update(provider='Open-Meteo',url='https://open-meteo.com/en/docs',
                attribution='Open-Meteo · CC BY 4.0 · Free API только для некоммерческого использования')
        for source in self.sources:
            key=source['id']; self.refresh_locks[key]=threading.Lock()
            self.states[key]={'last_attempt_at':None,'last_success_at':None,'next_refresh_at':None,
                              'error':None,'failures':0,'coverage':{},'refreshing':False,'snapshot':None}
            self.rows[key]=[]
            try:
                current=json.loads((self.root/key/'current.json').read_text())
                snapshot=self.root/key/'snapshots'/current['snapshot']
                if snapshot.parent.resolve()!=(self.root/key/'snapshots').resolve(): raise ValueError('Invalid snapshot path')
                rows_bytes=(snapshot/'records.json').read_bytes()
                if hashlib.sha256(rows_bytes).hexdigest()!=current['records_sha256']: raise ValueError('Snapshot checksum mismatch')
                loaded=json.loads(rows_bytes)
                if not isinstance(loaded,list) or not isinstance(current.get('coverage'),dict):
                    raise ValueError('Invalid snapshot schema')
                for name in ('last_attempt_at','last_success_at','next_refresh_at'):
                    timestamp(current[name])
                if current.get('weather_provider', weather_provider)!=weather_provider and key=='weather': continue
                if key=='changes' and current.get('source_url')!=source['url']: continue
                self.states[key].update(current,refreshing=False); self.rows[key]=loaded
            except FileNotFoundError: pass
            except (OSError,ValueError,KeyError,TypeError):
                self.states[key]['error']='Локальный снимок повреждён; ожидается повторное получение'
            try:
                failure=json.loads((self.root/key/'failure.json').read_text())
                if key=='changes' and failure.get('source_url')!=source['url']: continue
                timestamp(failure['next_refresh_at'])
                if failure['last_attempt_at'] > (self.states[key]['last_attempt_at'] or ''):
                    self.states[key].update(failure)
            except (OSError, ValueError, KeyError, TypeError): pass

    def acquire(self):
        try:
            self.root.mkdir(parents=True,exist_ok=True)
            self.owner=(self.root/'.collector.lock').open('a')
            fcntl.flock(self.owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return True
        except (OSError,BlockingIOError):
            if self.owner: self.owner.close(); self.owner=None
            self.storage_error='Мониторинг не запущен: каталог недоступен или уже занят другим процессом'
            return False

    async def start(self):
        if self.enabled and self.acquire():
            self.tasks=[asyncio.create_task(self.worker(s)) for s in self.sources if not s.get('blocked') and not s.get('derived_from')]

    async def close(self):
        # Each worker finishes its bounded in-flight acquisition before releasing ownership.
        self.enabled=False
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        if self.owner:
            self.owner.close(); self.owner=None

    async def worker(self, source):
        while self.enabled:
            state=self.states[source['id']]
            next_at=timestamp(state['next_refresh_at']) if state.get('next_refresh_at') else utcnow()
            delay=max(0,(next_at-utcnow()).total_seconds())
            if delay: await asyncio.sleep(delay)
            work=asyncio.create_task(asyncio.to_thread(self.refresh,source['id']))
            try: await asyncio.shield(work)
            except asyncio.CancelledError:
                await work
                raise

    def refresh(self, key):
        source=next(s for s in self.sources if s['id']==key)
        if source.get('blocked') or source.get('derived_from') or not self.refresh_locks[key].acquire(blocking=False): return
        now=utcnow(); directory=None; fetch=None
        try:
            with self.lock:
                old=dict(self.states[key]); self.states[key].update(last_attempt_at=iso(now),refreshing=True)
            parent=self.root/key/'snapshots'; parent.mkdir(parents=True,exist_ok=True)
            directory=parent/(now.strftime('%Y%m%dT%H%M%S')+'-'+uuid4().hex[:8]); directory.mkdir()
            cache=old.get('weather_cache')
            if cache:
                # Store relocatable cache references; never trust an absolute path from state.
                filename=cache.get('file')
                if filename and Path(filename).name==filename and old.get('snapshot'):
                    cache={**cache,'path':str(parent/old['snapshot']/filename)}
                else:
                    cache=None
            fetch=self.fetcher_factory(directory,cache)
            rows,coverage=collect(key,fetch,now,self.provider)
            # Receipt time describes when this batch was fully obtained, not when download started.
            completed=utcnow()
            for row in rows: row['fetched_at']=iso(completed)
            write_json(directory/'records.json',rows)
            next_at=completed+timedelta(seconds=source['interval_seconds']+random.uniform(30,180))
            if fetch.expires and fetch.expires>next_at: next_at=fetch.expires
            state=dict(last_attempt_at=iso(now),last_success_at=iso(completed),next_refresh_at=iso(next_at),
                       error=None,failures=0,coverage=coverage,refreshing=False,snapshot=directory.name,
                       records_sha256=hashlib.sha256((directory/'records.json').read_bytes()).hexdigest(),
                       source_url=source['url'],
                       weather_provider=self.provider,weather_cache=(
                           {**{k:v for k,v in fetch.weather_cache.items() if k!='path'},
                            'file':Path(fetch.weather_cache['path']).name} if fetch.weather_cache else None))
            write_json(directory/'manifest.json',{**state,'schema_version':'operational-monitor-v1','source':source,'count':len(rows)})
            write_json(self.root/key/'current.json',state)
            (self.root/key/'failure.json').unlink(missing_ok=True)
            with self.lock: self.states[key]=state; self.rows[key]=rows
            LOG.info('Monitoring refreshed source=%s records=%s',key,len(rows))
            self.prune(parent,directory)
        except Exception as exc:
            failures=self.states[key]['failures']+1
            next_at=utcnow()+timedelta(seconds=min(86400,source['interval_seconds']*2**min(failures-1,4))+random.uniform(30,180))
            if isinstance(exc,FetchError) and exc.retry_after and exc.retry_after>next_at: next_at=exc.retry_after
            error=str(exc) if isinstance(exc,FetchError) else 'Структура или содержимое источника не прошли проверку'
            if isinstance(exc,OSError): error='Не удалось сохранить снимок мониторинга'
            failure=dict(last_attempt_at=iso(now),next_refresh_at=iso(next_at),error=error,failures=failures,refreshing=False,
                         source_url=source['url'])
            with self.lock: self.states[key].update(failure)
            with suppress(OSError):
                write_json(self.root/key/'failure.json',failure)
                if directory: write_json(directory/'failure.json',{**failure,'detail':str(exc)})
                self.prune(self.root/key/'snapshots',directory)
            LOG.warning('Monitoring refresh failed source=%s reason=%s',key,type(exc).__name__)
        finally:
            with self.lock: self.states[key]['refreshing']=False
            self.refresh_locks[key].release()

    def prune(self,parent,current):
        keep=self.states[parent.parent.name].get('snapshot')
        dirs=sorted(p for p in parent.iterdir() if p.is_dir())
        for path in dirs[:-48]:
            if path!=current and path.name!=keep: shutil.rmtree(path)

    def view(self, now=None):
        now=now or utcnow(); cards=[]
        with self.lock:
            for source in self.sources:
                if source.get('hidden'): continue
                key=source['id']; state,rows=self.data(key); coverage=state['coverage']
                age=(now-timestamp(state['last_success_at'])).total_seconds() if state['last_success_at'] else None
                status='pending'
                if source.get('blocked'): status='blocked'
                elif not self.enabled: status='disabled'
                elif state['error'] or self.storage_error: status='error'
                elif age is not None: status='stale' if age>source['stale_after_seconds'] else 'fresh'
                latest=coverage.get('latest_publication')
                if status=='fresh' and latest and now-timestamp(latest)>timedelta(days=2): status='lagging'
                if key=='traffic' and status=='fresh':
                    status='pending' if not latest else 'stale' if (now-timestamp(latest)).total_seconds()>source['stale_after_seconds'] else 'fresh'
                if key=='weather' and status=='fresh' and rows and max(timestamp(r['valid_end']) for r in rows)<now: status='stale'
                if key=='changes' and status=='fresh' and coverage.get('window_end') and timestamp(coverage['window_end'])<=now: status='stale'
                preview=rows[:3]
                if key=='weather': preview=[r for r in rows if timestamp(r['valid_end'])>now][:1]
                cards.append({**source,**{k:state[k] for k in ['last_attempt_at','last_success_at','next_refresh_at','error','refreshing','coverage']},
                    'error':self.storage_error or state['error'],'status':status,'age_seconds':age,'record_count':len(rows),
                    'unknown_route_count':sum(r['route_link']['status']=='unknown' for r in rows),'preview':preview})
        return dict(schema_version='operational-monitor-v1',generated_at=iso(now),information_mode='operational',
                    automatic=self.enabled and not self.storage_error,forecast_effect='not_applied',sources=cards,
                    historical=dict(start='2025-11-01',end='2026-01-01',model='B2',external_live_join=False,
                        note='Исторический прогноз ноября–декабря 2025 отделён от текущих наблюдений.'))

    def records(self,key,offset=0,limit=50):
        with self.lock:
            _,rows=self.data(key)
            return dict(information_mode='operational',source_id=key,total=len(rows),offset=offset,records=rows[offset:offset+limit],
                        collection_status='not_connected' if key=='traffic' else 'connected')

    def data(self,key):
        if key!='traffic': return self.states[key],self.rows[key]
        # Retain the records endpoint's source ID, but never relabel calendar data as traffic.
        return self.states[key],[]
