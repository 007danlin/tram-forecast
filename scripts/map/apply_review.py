"""Apply idempotent reviewed corrections without renumbering remaining entities."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def apply_review(network):
    review = json.loads((ROOT/'scripts/map/reviewed-corrections.json').read_text())
    if network['sha256'] != review['source_sha256']:
        raise ValueError('Review belongs to a different reference PDF')
    removed = set(review['exclude_stops'])
    network['stops'] = [stop for stop in network['stops'] if stop['id'] not in removed]
    for lane in network['lanes']:
        if lane['id'] in review['reference_verified_lanes']:
            lane['referenceVerified'] = True
    return network

if __name__ == '__main__':
    path = ROOT/'frontend/public/map-local/network.json'
    network = apply_review(json.loads(path.read_text()))
    path.write_text(json.dumps(network,ensure_ascii=False,separators=(',',':')))
    print(f'Review applied: {len(network["stops"])} stops, stable IDs retained')
