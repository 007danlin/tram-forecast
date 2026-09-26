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
# Original map field; excludes the poster title, printed route legend and footer.
BOUNDS = [62, 112, 1065, 1178]

def number(v):
    return f'{v:.2f}'.rstrip('0').rstrip('.') or '0'

def point(p):
    return f'{number(p.x)} {number(p.y)}'

def path(items):
    parts, last = [], None
    for item in items:
        kind = item[0]
        if kind == 're':
            r, orientation = item[1:]
            pts = [r.tl, r.tr, r.br, r.bl] if orientation == 1 else [r.tl, r.bl, r.br, r.tr]
            parts.append('M' + point(pts[0]) + ''.join('L' + point(p) for p in pts[1:]) + 'Z')
            last = None
        elif kind == 'qu':
            q = item[1]
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
    elements = []
    for d in page.get_drawings():
        if d['seqno'] == 0 or not d['rect'].intersects(bounds): continue
        if d['type'] != 'f': raise ValueError('This reference is expected to contain fill paths only')
        color = '#' + ''.join(f'{round(c*255):02x}' for c in d['fill'])
        rule = ' fill-rule="evenodd"' if d['even_odd'] else ''
        opacity = f' opacity="{number(d["fill_opacity"])}"' if d['fill_opacity'] != 1 else ''
        identifier=f' id="glyph-{d["seqno"]}"' if d['seqno'] in glyphs else ''
        elements.append(f'<path{identifier} fill="{color}"{rule}{opacity} d="{path(d["items"])}"/>')
    width,height=number(page.rect.width),number(page.rect.height)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><title>Трамваи Москвы — векторная схема</title><defs><clipPath id="map"><rect x="62" y="112" width="1065" height="1178"/></clipPath>{label_defs}</defs><g clip-path="url(#map)">' + ''.join(elements) + '</g></svg>'
    out=ROOT/'frontend/public/map-local/schematic.svg'
    out.write_text(svg)
    subprocess.run(['npx', '--yes', '--package=svgo@4.0.0', '--', 'svgo', str(out), '-o', str(out), '--multipass', '--config', str(ROOT/'scripts/map/svgo-reference.mjs')], check=True)
    svg = out.read_text()
    metadata={'source':args.pdf.name,'source_sha256':digest,'bounds':BOUNDS,'paths':len(elements),'sha256':hashlib.sha256(svg.encode()).hexdigest(),'raster_images':0,'station_label_count':len(labels),'optimizer':'svgo 4.0.0 --multipass','note':'Original vector outlines; PDF raster shadows omitted. Interactive lane geometry stays in network.json.'}
    (out.parent/'schematic.meta.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(f'{len(elements)} vector paths; {out.stat().st_size} bytes; no images/scripts/external links')

if __name__=='__main__': main()
