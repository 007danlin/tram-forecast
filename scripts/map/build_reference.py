"""Build the cartographic vector surface from the verified reference PDF.

Only authors need PyMuPDF (tested 1.28.2). Runtime uses the generated local SVG;
network.json retains stable selectable lane geometry. PDF raster shadows are
intentionally excluded. All labels/route colours use original vector outlines.
Usage: python scripts/map/build_reference.py /path/to/trammap_15_04_26-2.pdf
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = '13bf11ade2d5a36bd3af8b4990e505e9692cf39eacbdb91f79e419f83bcf5c6f'
# Southern labels/arrows end at y=1307.553; the printed legend starts at 1310.05.
# Keep the complete MKAD and southern metro/MCD labels with a small clear margin.
BOUNDS = [62, 112, 1065, 1198]
# Poster decorations in this checksum-locked source; no network/station shapes.
HEART = tuple(range(14726, 14733))
HEART_BACK = 14608
EXCLUDE = {3058, 14609, HEART_BACK, *HEART}

def number(v):
    return f'{v:.2f}'.rstrip('0').rstrip('.') or '0'

def point(p):
    return f'{number(p[0])} {number(p[1])}'

def path(items):
    parts, last = [], None
    for item in items:
        kind = item[0]
        if kind == 're':
            # Keep signed rectangle coordinates: normalizing x0/x1 or y0/y1
            # reverses winding and fills holes in compound nonzero paths.
            r, orientation = pymupdf.Rect(item[1]), item[2]
            # PyMuPDF +1 means anticlockwise. Match line/curve subpaths too:
            # reversing every rectangle alone breaks mixed rectangle/line holes.
            pts = [r.tl, r.bl, r.br, r.tr] if orientation == 1 else [r.tl, r.tr, r.br, r.bl]
            parts.append('M' + point(pts[0]) + ''.join('L' + point(p) for p in pts[1:]) + 'Z')
            last = None
        elif kind == 'qu':
            q = pymupdf.Quad(item[1])
            parts.append('M'+point(q.ul)+'L'+point(q.ur)+'L'+point(q.lr)+'L'+point(q.ll)+'Z')
            last = None
        elif kind in ('l', 'c'):
            start = item[1]
            if last != start:
                if last is not None: parts.append('Z')
                parts.append('M'+point(start))
            if kind == 'l': parts.append('L'+point(item[2])); last = item[2]
            else: parts.append('C'+' '.join(point(p) for p in item[2:])); last = item[4]
        else:
            raise ValueError(f'Unsupported drawing item: {kind}')
    if last is not None: parts.append('Z')
    return ''.join(parts)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    args = parser.parse_args()
    digest = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    if digest != EXPECTED: raise SystemExit('Unexpected PDF checksum; do not substitute another edition.')
    page = pymupdf.open(args.pdf)[0]
    bounds = pymupdf.Rect(BOUNDS[0], BOUNDS[1], BOUNDS[0]+BOUNDS[2], BOUNDS[1]+BOUNDS[3])
    network=json.loads((ROOT/'frontend/public/map-local/network.json').read_text())
    labels=[label for label in network['labels'] if label.get('originalGlyphs')]
    glyphs={seq for label in labels for seq in label['originalGlyphs']}
    label_defs=''.join('<g id="station-label-'+label['id']+'">'+''.join(f'<use href="#glyph-{seq}"/>' for seq in label['originalGlyphs'])+'</g>' for label in labels)
    symbols = network.get('stationSymbols', [])
    glyphs.update(seq for group in symbols for seq in group['originalPaths'])
    symbol_defs = ''.join('<g id="station-symbol-'+group['id']+'">'+''.join(f'<use href="#glyph-{seq}"/>' for seq in group['originalPaths'])+'</g>' for group in symbols)
    # get_drawings() normalizes rectangles in PyMuPDF 1.28.2, losing part of
    # their winding information (e.g. the white frame around the Kremlin).
    drawings = page.get_cdrawings()
    icon = [d for d in drawings if d['seqno'] in (HEART_BACK, *HEART)]
    icon_paths = ''.join('<path fill="'+('#fff' if d['seqno']==HEART_BACK else '#46507d')+'" d="'+path(d['items'])+'"/>' for d in icon)
    favicon = ROOT/'frontend/public/favicon.svg'
    favicon.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="952 134 132 132"><title>TramFlow</title>'+icon_paths+'</svg>')
    elements = []
    for d in drawings:
        if d['seqno'] in EXCLUDE: continue
        if d['seqno'] == 0 or not pymupdf.Rect(d['rect']).intersects(bounds): continue
        if d['type'] != 'f': raise ValueError('This reference is expected to contain fill paths only')
        color = '#' + ''.join(f'{round(c*255):02x}' for c in d['fill'])
        rule = ' fill-rule="evenodd"' if d['even_odd'] else ''
        opacity = f' opacity="{number(d["fill_opacity"])}"' if d['fill_opacity'] != 1 else ''
        identifier=f' id="glyph-{d["seqno"]}"' if d['seqno'] in glyphs else ''
        elements.append(f'<path{identifier} fill="{color}"{rule}{opacity} d="{path(d["items"])}"/>')
    width,height=number(page.rect.width),number(page.rect.height)
    clip = ' '.join(f'{key}="{number(value)}"' for key, value in zip(('x', 'y', 'width', 'height'), BOUNDS))
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><title>Трамваи Москвы — векторная схема</title><defs><clipPath id="map"><rect {clip}/></clipPath>{label_defs}{symbol_defs}</defs><g clip-path="url(#map)">' + ''.join(elements) + '</g></svg>'
    out=ROOT/'frontend/public/map-local/schematic.svg'
    out.write_text(svg)
    subprocess.run(['npx', '--yes', '--package=svgo@4.0.0', '--', 'svgo', str(out), '-o', str(out), '--multipass', '--config', str(ROOT/'scripts/map/svgo-reference.mjs')], check=True)
    svg = out.read_text()
    metadata={'source':args.pdf.name,'source_sha256':digest,'bounds':BOUNDS,'paths':len(elements),'sha256':hashlib.sha256(svg.encode()).hexdigest(),'raster_images':0,'excluded_poster_paths':sorted(EXCLUDE),'favicon_sha256':hashlib.sha256(favicon.read_bytes()).hexdigest(),'station_label_count':len(labels),'optimizer':'svgo 4.0.0 --multipass','path_extraction':'get_cdrawings; signed rectangle coordinates preserve compound-path winding','note':'Original vector outlines; PDF raster shadows omitted. Interactive lane geometry stays in network.json.'}
    metadata['station_symbol_count'] = len(symbols)
    (out.parent/'schematic.meta.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(f'{len(elements)} vector paths; {out.stat().st_size} bytes; no images/scripts/external links')

if __name__=='__main__': main()
