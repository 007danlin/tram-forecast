"""Attach reviewed PDF station symbols to route selection (author-only PyMuPDF).

Run after build_label_outlines.py and before build_reference.py. The checked-in
review names each label explicitly; runtime never guesses the nearest station.
"""
import argparse
import hashlib
import json
from pathlib import Path
import pymupdf
from build_reference import EXPECTED

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    args = parser.parse_args()
    if hashlib.sha256(args.pdf.read_bytes()).hexdigest() != EXPECTED:
        raise SystemExit('Unexpected source PDF')
    target = ROOT / 'frontend/public/map-local/network.json'
    network = json.loads(target.read_text())
    review = json.loads((ROOT / 'scripts/map/reviewed-station-symbols.json').read_text())
    if network['sha256'] != EXPECTED or review['source_sha256'] != EXPECTED:
        raise SystemExit('Network, review and PDF editions differ')
    labels = {label['id']: label for label in network['labels']}
    drawings = {d['seqno']: d for d in pymupdf.open(args.pdf)[0].get_drawings()}
    groups = []
    for item in review['groups']:
        lane_ids = set()
        for label in item['labels']:
            current = labels[label['id']]
            if current['text'] != label['text']:
                raise SystemExit(f"Changed label identity: {label['id']}")
            lane_ids.update(current['lanes'])
        for route in item.get('routes', []):
            matches = [lane['id'] for lane in network['lanes'] if route in lane['routes']]
            if not matches:
                raise SystemExit(f'Unknown diagram route: {route}')
            lane_ids.update(matches)
        served_routes = {route for lane in network['lanes'] if lane['id'] in lane_ids
                         for route in lane['routes']}
        if not set(item.get('routePlateNumbers', [])).issubset(served_routes):
            raise SystemExit(f"Station omits a printed terminal route: {item['name']}")
        # Include each icon/plate's paper halo and numeral cutouts separately.
        # A box around a whole row would also capture unrelated neighbouring text.
        seed_paths = item['seedPaths'] + item.get('routePlatePaths', [])
        seeds = [drawings[seq]['rect'] + (-.7, -.7, .7, .7) for seq in seed_paths]
        paths = {seq for seq, d in drawings.items()
                 if seq >= 7000 and any(r.contains(d['rect']) for r in seeds)}
        if 'textBounds' in item:
            bounds = pymupdf.Rect(item['textBounds'])
            text = {seq for seq, d in drawings.items() if bounds.contains(d['rect'])
                    and all(c < .2 for c in d['fill'])}
            if not text:
                raise SystemExit(f"Missing original station name: {item['name']}")
            paths.update(text)
        if not lane_ids or not set(seed_paths).issubset(paths):
            raise SystemExit(f"Incomplete station symbols: {item['id']}")
        bounds = pymupdf.Rect()
        for seq in paths:
            bounds |= drawings[seq]['rect']
        groups.append({
            'id': item['id'], 'name': item['name'],
            'labels': [label['id'] for label in item['labels']],
            'lanes': sorted(lane_ids), 'originalPaths': sorted(paths),
            'bounds': [round(v, 3) for v in bounds],
        })
    # Audit every original M logo, including duplicate source paths and rotated
    # logos. Standalone MCC/MCD/railway symbols are also covered by the review.
    covered = {seq for group in groups for seq in group['originalPaths']}
    logos = {seq for seq, d in drawings.items() if d['fill'][0] > .8
             and d['fill'][1] < .25 and d['fill'][2] < .25
             and len(d['items']) == 18 and 3.4 < d['rect'].width < 6
             and 2.2 < d['rect'].height < 4.2 and 100 < d['rect'].y0 < 1290}
    if logos - covered:
        raise SystemExit(f'Uncovered metro logos: {sorted(logos - covered)}')
    # All 72 terminal number plates (76 paths including T1/T2 interiors).
    # 10326 is an inline T2 label on the diagonal track, not a station plate.
    plate_paths = {seq for seq, d in drawings.items() if seq >= 7000
                   and 100 < d['rect'].y0 < 1290 and 9 < d['rect'].width < 13
                   and 5 < d['rect'].height < 6.5 and not all(c > .85 for c in d['fill'])
                   and seq != 10326}
    reviewed_plates = {seq for item in review['groups'] for seq in item.get('routePlatePaths', [])}
    if plate_paths != reviewed_plates or not plate_paths.issubset(covered):
        raise SystemExit(f'Unreviewed terminal plates: {sorted(plate_paths ^ reviewed_plates)}')
    network['stationSymbols'] = groups
    network['station_symbol_source'] = 'Reviewed original PDF station symbols and terminal route-number plates; diagram-only lane associations.'
    target.write_text(json.dumps(network, ensure_ascii=False, separators=(',', ':')))
    print(f'{len(groups)} station symbol groups; {len(covered)} original paths; {len(logos)} metro logos; {len(plate_paths)} terminal plate paths covered')


if __name__ == '__main__':
    main()
