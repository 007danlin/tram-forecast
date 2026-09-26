"""One local collection pass. Never touches model/handoff/competition files."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from .service import Monitor

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--directory',type=Path,default=Path('artifacts/monitoring/live'))
parser.add_argument('--source',choices=['weather','closures','changes','events'])
parser.add_argument('--weather-provider',choices=['met','open_meteo'],default='met')
args=parser.parse_args()
monitor=Monitor(args.directory,weather_provider=args.weather_provider)
if not monitor.acquire(): raise SystemExit(monitor.storage_error)
try:
    keys=[args.source] if args.source else ['weather','closures','changes','events']
    with ThreadPoolExecutor(4) as pool: list(pool.map(monitor.refresh,keys))
    print(json.dumps(monitor.view(),ensure_ascii=False,indent=2))
finally: monitor.owner.close()
