"""Bounded Open-Meteo acquisition; publishes only fully validated snapshots."""
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import http.client
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from ml.factors import (ALIGNMENTS, WEATHER_REQUIRED_COLUMNS, WEATHER_OPTIONAL_COLUMNS,
                        WEATHER_SOURCE_URL, NORMALIZER_VERSION, normalize_open_meteo_snapshot,
                        load_weather_factors, sha256_file, weather_coverage)

MAX_BYTES = 32 * 1024 * 1024
MAX_RETRY_WAIT = 30


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def transport(url):
    parsed = urlsplit(url)
    connection = http.client.HTTPSConnection(parsed.hostname, timeout=10)
    try:
        connection.connect()
        connection.sock.settimeout(120)
        connection.request('GET', parsed.path+'?'+parsed.query, headers={'Accept':'application/json','User-Agent':'TramFlow-weather/1'})
        response = connection.getresponse()
        length = response.getheader('Content-Length')
        if length is not None and int(length) > MAX_BYTES:
            raise ValueError('Weather response exceeds 32 MiB')
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Weather response exceeds 32 MiB')
        return response.status, dict(response.getheaders()), raw
    finally:
        connection.close()


def retry_delay(headers, attempt):
    value = next((v for k,v in headers.items() if k.lower() == 'retry-after'), None)
    if value is None:
        return 2 ** attempt
    try:
        seconds = float(value)
    except ValueError:
        seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
    if not math.isfinite(seconds):
        raise ValueError("Invalid provider Retry-After")
    if seconds > MAX_RETRY_WAIT:
        raise ValueError('Provider Retry-After exceeds 30s; try a new snapshot later, without bypassing the quota')
    return max(0, seconds)


def acquire(url, parameters, root, *, send=transport, sleep=time.sleep):
    receipt = {'url':url,'parameters':parameters,'started_at':utc_now(),'completed_at':None,'attempts':[]}
    for attempt in range(3):
        try:
            status, headers, raw = send(url)
            receipt['attempts'].append({'http_status':status,'at':utc_now()})
            receipt['http_status'] = status
            (root/'raw.json').write_bytes(raw)
            if len(raw) > MAX_BYTES:
                raise ValueError('Weather response exceeds 32 MiB')
            if status == 200:
                receipt.update(completed_at=utc_now(), raw_sha256=sha256_file(root/'raw.json'))
                write_json(root/'request.json',receipt)
                return
            if status != 429 and not 500 <= status < 600:
                raise ValueError(f'Weather HTTP {status}; this response is not retryable')
            if attempt == 2:
                raise ValueError(f'Weather HTTP {status} after three attempts')
            delay = retry_delay(headers,attempt)
        except (OSError, http.client.HTTPException) as error:
            receipt['attempts'].append({'error':type(error).__name__,'at':utc_now()})
            if attempt == 2:
                write_json(root/'request.json',receipt)
                raise ValueError('Weather network request failed after three attempts') from error
            delay = 2 ** attempt
        finally:
            write_json(root/'request.json',receipt)
        sleep(delay)


def coverage_report(normalized, start, end):
    frame = load_weather_factors(normalized)
    coverage = weather_coverage(frame, start, end)
    if coverage['coverage'] != 1:
        raise ValueError('Incomplete target weather coverage')
    report = {'passed':True,'target':coverage}
    if start == '2025-01-01' and end == '2025-12-31':
        report['splits'] = {name:weather_coverage(frame,a,b) for name,a,b in (
            ('training_early','2025-01-01','2025-08-31'),('holdout','2025-09-01','2025-10-31'),('forecast','2025-11-01','2025-12-31'))}
    return report


def fetch_weather(start: str, end: str, output_dir: str | Path, *, offline=False,
                  alignment=ALIGNMENTS[0], send=transport, sleep=time.sleep):
    output = Path(output_dir)
    first,last = date.fromisoformat(start),date.fromisoformat(end)
    if first > last or alignment not in ALIGNMENTS:
        raise ValueError('Invalid weather period/alignment')
    if offline:
        return verify_offline(output,start,end)
    if output.exists() or output.is_symlink():
        raise ValueError('Snapshot exists; use --offline or a new versioned directory')
    output.parent.mkdir(parents=True,exist_ok=True)
    lock = output.with_name('.'+output.name+'.lock')
    with lock.open('x'):
        pass
    root = Path(tempfile.mkdtemp(prefix='.weather-',dir=output.parent))
    try:
        requested_end = last + timedelta(days=int(alignment == ALIGNMENTS[1]))
        parameters = {'latitude':55.7558,'longitude':37.6173,'start_date':start,'end_date':requested_end.isoformat(),
                      'hourly':','.join((*WEATHER_REQUIRED_COLUMNS,*WEATHER_OPTIONAL_COLUMNS)),
                      'timezone':'Europe/Moscow','models':'era5','temperature_unit':'celsius','wind_speed_unit':'kmh',
                      'precipitation_unit':'mm','timeformat':'iso8601'}
        acquire(WEATHER_SOURCE_URL+'?'+urlencode(parameters),parameters,root,send=send,sleep=sleep)
        normalize_open_meteo_snapshot(root/'raw.json',root/'normalized.csv',root/'manifest.json',source_url=WEATHER_SOURCE_URL,
                                      start=start,end=end,receipt_path=root/'request.json',alignment=alignment)
        report = coverage_report(root/'normalized.csv',start,end)
        write_json(root/'coverage.json',report)
        manifest = json.loads((root/'manifest.json').read_text())
        manifest.update(target_start=start,target_end=end,request_sha256=sha256_file(root/'request.json'),coverage_sha256=sha256_file(root/'coverage.json'))
        write_json(root/'manifest.json',manifest)
        if output.exists():
            raise ValueError('Snapshot appeared during acquisition; refusing overwrite')
        root.rename(output)
        return report
    except Exception as error:
        write_json(root/'coverage.json',{'passed':False,'error':str(error)})
        failure = output.with_name(output.name+'.failed-'+uuid4().hex[:8])
        root.rename(failure)
        raise ValueError(f'{error}; diagnostic response retained in {failure}') from error
    finally:
        if root.exists(): shutil.rmtree(root)
        lock.unlink()


def verify_offline(root: Path, start: str, end: str):
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest.get('normalizer_version') != NORMALIZER_VERSION or manifest.get('target_start') != start or manifest.get('target_end') != end:
        raise ValueError('Offline normalizer version or target period mismatch')
    for name, expected in (('raw.json',manifest['raw_snapshot']['sha256']),('normalized.csv',manifest['normalized']['sha256']),
                           ('request.json',manifest['request_sha256']),('coverage.json',manifest['coverage_sha256'])):
        if sha256_file(root/name) != expected:
            raise ValueError(f'Offline checksum mismatch: {name}')
    with tempfile.TemporaryDirectory(prefix='weather-offline-') as tmp:
        regenerated = Path(tmp)/'normalized.csv'
        normalize_open_meteo_snapshot(root/'raw.json',regenerated,Path(tmp)/'manifest.json',source_url=manifest['source_url'],
                                      start=start,end=end,receipt_path=root/'request.json',alignment=manifest['alignment'])
        if sha256_file(regenerated) != manifest['normalized']['sha256']:
            raise ValueError('Offline normalized checksum mismatch')
        report = coverage_report(regenerated,start,end)
        if report != json.loads((root/'coverage.json').read_text()):
            raise ValueError('Offline coverage mismatch')
        return report
