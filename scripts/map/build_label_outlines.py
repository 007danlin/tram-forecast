"""Attach original PDF glyph outlines to existing stop-label IDs for route focus.

Author-only: PyMuPDF 1.28.2. No OCR text is re-typeset and no station IDs are created.
Run after build_stops/apply_review with the same verified PDF.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import pymupdf
from build_reference import EXPECTED

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    args=parser.parse_args()
    if hashlib.sha256(args.pdf.read_bytes()).hexdigest()!=EXPECTED:
        raise SystemExit('Unexpected source PDF')
    target=ROOT/'frontend/public/map-local/network.json'
    network=json.loads(target.read_text())
    if network['sha256']!=EXPECTED:raise SystemExit('Network and PDF editions differ')
    labels=network['labels'];assigned={label['id']:[] for label in labels}
    page=pymupdf.open(args.pdf)[0]
    for drawing in page.get_drawings():
        rect=drawing['rect'];fill=drawing.get('fill')
        if not fill or not all(c<.2 for c in fill) or not 100<rect.y0<1290 or max(rect.width,rect.height)>100:
            continue
        x,y=(rect.x0+rect.x1)/2,(rect.y0+rect.y1)/2
        candidates=[]
        for label in labels:
            angle=math.radians(label['angle']);c,s=math.cos(angle),math.sin(angle)
            dx,dy=x-label['x'],y-label['y'];u,v=dx*c+dy*s,-dx*s+dy*c
            for line in label['lines']:
                a,b=abs(u-line['dx']),abs(v-line['dy'])
                if a<=line['w']/2+1.3 and b<=label['fs']/2+0.8:
                    candidates.append((b+a*.001,label['id']))
        if candidates:
            label_id=min(candidates)[1]
            assigned[label_id].append(drawing['seqno'])
    # Five horizontal continuation lines were omitted by the original OCR grouping.
    # Reuse only unassigned outlines that share a left edge and an ordinary line gap.
    drawings={d['seqno']:d for d in page.get_drawings()}
    used={g for group in assigned.values() for g in group}
    for label in labels:
        if abs(label['angle'])>5:continue
        for glyph in list(assigned[label['id']]):
            r=drawings[glyph]['rect']
            if r.height>8 or r.width<5:continue
            for seq,drawing in drawings.items():
                q=drawing['rect'];fill=drawing.get('fill')
                if seq in used or not fill or not all(c<.2 for c in fill) or not 100<q.y0<1290 or not 2<q.height<5 or q.width<5:continue
                if abs(q.x0-r.x0)<.6 and (0<q.y0-r.y1<1.8 or 0<r.y0-q.y1<1.8):
                    assigned[label['id']].append(seq);used.add(seq)
    # Reviewed against this exact PDF: the second line of Club Rusakova belongs
    # to the same stop as its first line; the adjacent bundle is Semyonovskaya.
    by_id={label['id']:label for label in labels}
    for identifier, text in {'l317':'Русакова','l318':'Мельников','l358':'Семёновская'}.items():
        if text not in by_id.get(identifier,{}).get('text',''):
            raise SystemExit(f'Unexpected label identity: {identifier}')
    by_id['l318']['lanes']=by_id['l317']['lanes'].copy()
    by_id['l358']['lanes']=['brown-12','gray-0','red-18','lime-7','cyan-2']
    for stop in network['stops']:
        if stop['label']=='l318' and stop['lane'] in by_id['l358']['lanes']:
            stop['label']='l358'
    missing=[]
    for label in labels:
        label.pop('outline', None)
        label['originalGlyphs']=assigned[label['id']]
        if not label['originalGlyphs']:missing.append(label['id'])
    if missing:raise SystemExit(f'Labels without original glyphs: {missing}')
    network['label_outline_source']='Original dark vector glyphs from the verified PDF; existing label IDs/route associations retained.'
    target.write_text(json.dumps(network,ensure_ascii=False,separators=(',',':')))
    print(f'{len(labels)} label glyph groups / {sum(map(len,assigned.values()))} original glyph paths / {target.stat().st_size} network bytes')

if __name__=='__main__':main()
