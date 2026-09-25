"""Осевые линии «полос» маршрутов из локального PDF.

Запуск из корня: python scripts/map/extract_lanes.py [путь_к_pdf]
Для каждого цвета маршрутов из легенды растеризует залитые контуры, скелетизирует и
упрощает до полилиний. Результат — data/tram-map/lanes.json (локально, не в Git)
и data/tram-map/lanes-preview.png для визуальной проверки.
Полоса ≠ маршрут: один цвет разделяют несколько маршрутов, привязка к номерам — отдельный шаг.
"""
import json, sys, warnings
warnings.filterwarnings('ignore')
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw
from shapely.geometry import LineString
from scipy.ndimage import distance_transform_edt
from skimage.morphology import skeletonize, remove_small_holes, remove_small_objects

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/tram-map/trammap_15_04_26-2.pdf"
OUT = ROOT / "data/tram-map"
S = 4  # пикселей на пункт PDF
MIN_GRAY_W = 2.3
LEGEND_Y = 1290  # ниже — легенда, не трогаем
COLORS = {  # цвета маршрутов из легенды (измерены по бейджам)
    "brown": "#96534b", "gray": "#a1a2a3", "red": "#ef4046", "orange": "#f6861f", "amber": "#faa619", "yellow": "#ffcb04",
    "lime": "#b2d33f", "green": "#4bb860", "green2": "#4bb85e", "teal": "#07b89d", "cyan": "#00c1f3",
    "blue": "#0083c8", "purple": "#8f499c", "pink": "#ee4d9b", "lilac": "#c78fbf",
}


def hex2rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def flatten(items, steps=8):
    pts = []
    for it in items:
        if it[0] == "l":
            pts += [(it[1].x, it[1].y), (it[2].x, it[2].y)]
        elif it[0] == "c":
            p0, p1, p2, p3 = it[1:5]
            for i in range(steps + 1):
                t = i / steps; u = 1 - t
                pts.append((u**3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t**3 * p3.x,
                            u**3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t**3 * p3.y))
        elif it[0] == "re":
            r = it[1]; pts += [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
    return pts


def trace(skel):
    """Скелет → полилинии между узлами (концы/развилки), координаты в пикселях (x, y)."""
    ys, xs = np.nonzero(skel)
    pix = set(zip(xs.tolist(), ys.tolist()))
    nb = lambda p: [(p[0] + dx, p[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy) and (p[0] + dx, p[1] + dy) in pix]
    deg = {p: len(nb(p)) for p in pix}
    nodes = {p for p, d in deg.items() if d != 2}
    seen, lines = set(), []
    for n in nodes:
        for m in nb(n):
            if (n, m) in seen:
                continue
            path, prev, cur = [n, m], n, m
            seen.add((n, m))
            while cur not in nodes:
                nxt = [q for q in nb(cur) if q != prev and (cur, q) not in seen]
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
                seen.add((prev, cur)); path.append(cur)
            seen.add((path[-1], path[-2]))
            lines.append(path)
    return lines


page = pymupdf.open(SRC)[0]
W, H = int(page.rect.width * S) + 1, int(page.rect.height * S) + 1
drawings = [d for d in page.get_drawings() if d.get("fill")]
result, preview = {}, Image.new("RGB", (W, H), "white")
pd = ImageDraw.Draw(preview)
for name, hx in COLORS.items():
    want = hex2rgb(hx)
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    n = 0
    for d in drawings:
        f = tuple(round(v * 255) for v in d["fill"])
        r = d["rect"]
        if max(abs(a - b) for a, b in zip(f, want)) > 1 or r.y0 > LEGEND_Y or r.width * r.height < 40:
            continue
        pts = flatten(d["items"])
        if len(pts) >= 3:
            md.polygon([(x * S, y * S) for x, y in pts], fill=255); n += 1
    m = np.array(mask) > 0
    m = remove_small_objects(m, 30 * S)
    m = remove_small_holes(m, 40 * S * S)
    skel = skeletonize(m)
    dt = distance_transform_edt(m)
    lines = []
    for path in trace(skel):
        ls = LineString([(x / S, y / S) for x, y in path]).simplify(0.6)
        width = 2 * float(np.mean([dt[y, x] for x, y in path])) / S  # ширина полосы, пт
        if name == "gray" and (width < MIN_GRAY_W or ls.length < 25):
            continue  # серый цвет делают и фоновые линии: берём только полосы ширины маршрутов
        if ls.length >= 3:
            lines.append([[round(x, 1), round(y, 1)] for x, y in ls.coords])
    result[name] = {"color": hx, "shapes": n, "lanes": lines}
    for ln in lines:
        pd.line([(x * S, y * S) for x, y in ln], fill=want, width=6)
    print(name, hx, "shapes", n, "polylines", len(lines), "points", sum(len(l) for l in lines))
(OUT / "lanes.json").write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
# Сеть для frontend: только геометрия, отрисовывается самим приложением.
import hashlib
web = ROOT / "frontend/public/map-local"
web.mkdir(parents=True, exist_ok=True)
network = {"source": SRC.name, "sha256": hashlib.sha256(SRC.read_bytes()).hexdigest(),
           "viewBox": [0, 0, round(page.rect.width, 2), round(page.rect.height, 2)],
           "lanes": [{"id": f"{k}-{i}", "colorKey": k, "color": v["color"], "points": ln}
                     for k, v in result.items() for i, ln in enumerate(v["lanes"])]}
(web / "network.json").write_text(json.dumps(network, separators=(",", ":")), encoding="utf-8")
print("network.json lanes:", len(network["lanes"]))
preview.resize((W // 2, H // 2)).save(OUT / "lanes-preview.png")
