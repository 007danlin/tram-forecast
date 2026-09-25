"""Create load controls directly from the immutable source batch, outside Git."""
import argparse
from datetime import timedelta
import json
import math
from pathlib import Path

from backend.handoff.store import load_snapshot


def generate(release):
    snapshot = load_snapshot(release)
    if snapshot.start.isoformat() != '2025-11-01T00:00:00+03:00' or snapshot.end.isoformat() != '2026-01-01T00:00:00+03:00' or len(snapshot.cells) != 14640 or len(snapshot.routes) != 10:
        raise ValueError('Load acceptance requires the complete 61-day, 10-route package')
    def control(routes, start, end, resolution):
        step = timedelta(hours=1) if resolution == 'hour' else timedelta(days=1)
        rows = []
        for route in sorted(routes, key=int):
            stamp = start
            while stamp < end:
                cells = [snapshot.cells[(route, stamp + timedelta(hours=h))] for h in range(int(step.total_seconds()/3600))]
                rows.append({'route_id': route, 'start': stamp.isoformat(), 'value': math.fsum(c.prediction for c in cells)})
                stamp += step
        return {'filters': {'route_ids':routes,'start':start.isoformat(),'end':end.isoformat(),'resolution':resolution,'forecast_run_id':snapshot.run_id}, 'rows':rows, 'total':math.fsum(r['value'] for r in rows)}
    days, months = [], []
    for i, route in enumerate(snapshot.routes):
        for d in (0, 30, 60):
            start = snapshot.start + timedelta(days=d)
            days.append(control([route], start, start+timedelta(days=1), 'hour'))
        for d, length in ((0,30),(30,31)):
            start = snapshot.start+timedelta(days=d)
            months.append(control([route],start,start+timedelta(days=length),'day'))
    for routes in (list(snapshot.routes), ['1','5']):
        days.append(control(routes,snapshot.start,snapshot.start+timedelta(days=1),'hour'))
        months.append(control(routes,snapshot.start+timedelta(days=30),snapshot.end,'day'))
    return {'forecast_run_id':snapshot.run_id,'csv_sha256':snapshot.csv_sha256,'days':days,'months':months,'export':control(list(snapshot.routes),snapshot.start+timedelta(days=30),snapshot.end,'hour')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    controls = generate(args.release)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as output:
        json.dump(controls, output, separators=(',',':'))


if __name__ == '__main__':
    main()
