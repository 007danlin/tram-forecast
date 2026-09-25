"""Достопримечательности и значки метро/МЦК из локального PDF.

Запуск из корня: python scripts/map/build_icons.py   (после build_stops.py)
- landmarks: иллюстрации в «кирпичной» палитре PDF вместе с подписями; кластеризуются по близости;
  каждый кластер — объект с контурами (d, fill) в координатах страницы.
- metro: логотип «М» (красный, 18 сегментов) + цепочка круглых значков линий/МЦК рядом с ним; название станции —
  ближайшая подпись из build_stops.py (если есть). Контуры сохраняются в порядке отрисовки PDF.
Дописывает "landmarks" и "metro" в frontend/public/map-local/network.json.
"""
import json, math, warnings
from pathlib import Path

import pymupdf
from shapely.geometry import Point, box
from shapely.ops import unary_union

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
NET = ROOT / "frontend/public/map-local/network.json"
net = json.loads(NET.read_text(encoding="utf-8"))
page = pymupdf.open(ROOT / "data/tram-map/trammap_15_04_26-2.pdf")[0]
drawings = [d for d in page.get_drawings() if d.get("fill")]
for i, d in enumerate(drawings): d["order"] = i


def hx(f): return "#%02x%02x%02x" % tuple(round(v * 255) for v in f)


def num(v):
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def path_d(items):
    d, cur = [], None
    for it in items:
        k = it[0]
        if k == "l":
            a, b = it[1], it[2]
            if cur != (a.x, a.y): d.append(f"M{num(a.x)} {num(a.y)}")
            d.append(f"L{num(b.x)} {num(b.y)}"); cur = (b.x, b.y)
        elif k == "c":
            a, c1, c2, b = it[1:5]
            if cur != (a.x, a.y): d.append(f"M{num(a.x)} {num(a.y)}")
            d.append(f"C{num(c1.x)} {num(c1.y)} {num(c2.x)} {num(c2.y)} {num(b.x)} {num(b.y)}"); cur = (b.x, b.y)
        elif k == "re":
            r = it[1]; d.append(f"M{num(r.x0)} {num(r.y0)}H{num(r.x1)}V{num(r.y1)}H{num(r.x0)}Z"); cur = None
        elif k == "qu":
            q = it[1]; d.append(f"M{num(q.ul.x)} {num(q.ul.y)}L{num(q.ur.x)} {num(q.ur.y)}L{num(q.lr.x)} {num(q.lr.y)}L{num(q.ll.x)} {num(q.ll.y)}Z"); cur = None
    return "".join(d)


def shape(d):
    out = {"d": path_d(d["items"]) + ("Z" if d.get("closePath", True) else ""), "f": hx(d["fill"])}
    if d.get("fill_opacity") is not None and d["fill_opacity"] < 0.999: out["o"] = round(d["fill_opacity"], 2)
    if d.get("even_odd"): out["eo"] = 1
    return out


# ---------- достопримечательности
LM = {"#ab6a57", "#b9715f", "#b0705f", "#894e35", "#b26f5f"}
lm_items = [d for d in drawings if hx(d["fill"]) in LM and 100 < d["rect"].y0 < 1290 and d["rect"].width < 90]
u = unary_union([box(*d["rect"]).buffer(3.0) for d in lm_items])
comps = list(u.geoms) if u.geom_type == "MultiPolygon" else [u]
landmarks = []
for c in sorted(comps, key=lambda c: (round(c.bounds[1] / 30), c.bounds[0])):
    ms = sorted([d for d in lm_items if c.contains(box(*d["rect"]).centroid)], key=lambda d: d["order"])
    if not ms: continue
    b = unary_union([box(*d["rect"]) for d in ms]).bounds
    landmarks.append({"id": f"lm-{len(landmarks):02d}", "x": round((b[0] + b[2]) / 2, 1), "y": round((b[1] + b[3]) / 2, 1),
                      "w": round(b[2] - b[0], 1), "h": round(b[3] - b[1], 1), "shapes": [shape(d) for d in ms]})
print("достопримечательностей:", len(landmarks), "| контуров:", sum(len(l["shapes"]) for l in landmarks))

# ---------- значки метро/МЦК
# В потоке PDF значок станции — подряд идущие мелкие контуры: белая подложка, цветной кружок линии, «М», кольцо МЦК, цифры.
logos = [d for d in drawings if d["fill"][0] > 0.8 and d["fill"][1] < 0.25 and d["fill"][2] < 0.25 and len(d["items"]) == 18
         and 3.4 < d["rect"].width < 6.0 and 2.2 < d["rect"].height < 4.2 and 100 < d["rect"].y0 < 1290]


def icon_like(d, ref):
    r = d["rect"]
    if r.width > 11 or r.height > 6.5: return False
    f = d["fill"]
    if all(v < 0.3 for v in f): return len(d["items"]) <= 24 and r.width < 3.2  # цифры «14» внутри кольца МЦК, не название
    if hx(f) in ("#edeeed", "#f2f2f2"): return False  # фоновые ореолы текста
    return box(*r).distance(box(*ref)) <= 6.0


metro = []
for lg in sorted(logos, key=lambda d: (d["rect"].y0, d["rect"].x0)):
    idx = lg["order"]; group = [lg]
    for step in (-1, 1):
        k = idx + step
        while 0 <= k < len(drawings) and abs(k - idx) <= 12 and icon_like(drawings[k], lg["rect"]):
            group.append(drawings[k]); k += step
    group.sort(key=lambda d: d["order"])
    gb = unary_union([box(*d["rect"]) for d in group]).bounds
    cx, cyy = (gb[0] + gb[2]) / 2, (gb[1] + gb[3]) / 2
    metro.append({"id": f"m-{len(metro):03d}", "x": round(cx, 1), "y": round(cyy, 1), "w": round(gb[2] - gb[0], 1),
                  "shapes": [shape(d) for d in group]})
print("значков метро:", len(metro), "| контуров в среднем:", round(sum(len(m["shapes"]) for m in metro) / max(1, len(metro)), 1))
net["landmarks"], net["metro"] = landmarks, metro
NET.write_text(json.dumps(net, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print("network.json:", round(NET.stat().st_size / 1e6, 2), "МБ")
