"""Распознавание номеров маршрутов на линиях.

Запуск из корня: python scripts/map/label_lanes.py   (после extract_lanes.py)
Эталоны цифр берутся из бейджей легенды PDF, затем сопоставляются с белыми контурами цифр
вдоль линий (с поворотом по направлению линии). Пишет data/tram-map/lane-labels.json (локально).
"""
import json, math, sys, warnings
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageChops
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data/tram-map/trammap_15_04_26-2.pdf"
NET = ROOT / "frontend/public/map-local/network.json"
OUT = ROOT / "data/tram-map/lane-labels.json"

# Строки легенды: (колонка x, y бейджа) → номер. Порядок сверен с изображением легенды.
LEGEND = {
    150: [(1310, "Т1"), (1331, "Т2")],
    114: [(1351, "А"), (1371, "1"), (1392, "2"), (1412, "4"), (1433, "5"), (1453, "6"), (1474, "6к"), (1494, "7")],
    378: [(1310, "10"), (1330, "11"), (1351, "12"), (1371, "13"), (1392, "14"), (1412, "15"), (1433, "16"), (1453, "17"), (1473, "21"), (1494, "23")],
    608: [(1311, "25"), (1331, "26"), (1352, "27"), (1372, "28"), (1393, "29"), (1413, "30"), (1433, "31"), (1454, "32"), (1474, "36"), (1493, "38")],
    871: [(1311, "39"), (1332, "43"), (1352, "46"), (1372, "47"), (1393, "49"), (1413, "50")],
}
GW, GH = 56, 28  # растр эталона


def subpaths(items, steps=6):
    subs, cur, last = [], [], None
    for it in items:
        if it[0] == "re":
            r = it[1]; subs.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]); continue
        a = (it[1].x, it[1].y)
        if last is None or abs(a[0] - last[0]) > 1e-3 or abs(a[1] - last[1]) > 1e-3:
            if len(cur) > 2: subs.append(cur)
            cur = [a]
        if it[0] == "l":
            cur.append((it[2].x, it[2].y)); last = cur[-1]
        else:
            p0, p1, p2, p3 = it[1:5]
            for i in range(1, steps + 1):
                t = i / steps; u = 1 - t
                cur.append((u**3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t**3 * p3.x,
                            u**3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t**3 * p3.y)); last = cur[-1]
    if len(cur) > 2: subs.append(cur)
    return subs


def raster(subs, angle=0.0):
    """Нормированный растр глифа: поворот на -angle, масштаб по высоте, центрирование по bbox."""
    c, s = math.cos(-angle), math.sin(-angle)
    rot = [[(x * c - y * s, x * s + y * c) for x, y in sp] for sp in subs]
    xs = [p[0] for sp in rot for p in sp]; ys = [p[1] for sp in rot for p in sp]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    h = max(y1 - y0, 1e-6); k = (GH - 4) / h
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    img = Image.new("L", (GW, GH), 0)
    for sp in rot:
        layer = Image.new("L", (GW, GH), 0)
        ImageDraw.Draw(layer).polygon([((x - cx) * k + GW / 2, (y - cy) * k + GH / 2) for x, y in sp], fill=255)
        img = ImageChops.logical_xor(img.convert("1"), layer.convert("1")).convert("L")
    return np.array(img) > 0


def iou(a, b):
    u = np.logical_or(a, b).sum()
    return np.logical_and(a, b).sum() / u if u else 0


def is_white(f):
    return f is not None and all(v > 0.99 for v in f)


def is_ink(f):  # белые или тёмные контуры: номера на цветных линиях и в бейджах
    return f is not None and (all(v > 0.99 for v in f) or all(v < 0.3 for v in f))


page = pymupdf.open(SRC)[0]
drawings = [d for d in page.get_drawings() if d.get("fill")]

# --- эталоны из легенды: белый контур номера внутри цветного бейджа (целиком, многозначные — один контур)
badges = [d for d in drawings if d["rect"].y0 > 1290 and d["rect"].y1 < 1540 and 25 < d["rect"].width < 29 and 12 < d["rect"].height < 16 and not is_white(d["fill"])]
templates, num_color = {}, {}
for col, rows in LEGEND.items():
    for y, num in rows:
        bd = next((b for b in badges if abs(b["rect"].x0 - col) < 4 and abs(b["rect"].y0 - y) < 4), None)
        if not bd: print("no badge", num); continue
        gl = [d for d in drawings if is_ink(d["fill"]) and bd["rect"].contains(d["rect"]) and d["rect"].width < 20]
        if len(gl) != 1: print("legend", num, "glyphs", len(gl)); continue
        templates[num] = raster(subpaths(gl[0]["items"]))
        num_color[num] = tuple(round(v * 255) for v in bd["fill"])
print("templates:", sorted(templates))


def cdist(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


# --- глифы на линиях
net = json.loads(NET.read_text(encoding="utf-8"))
lines = [LineString(l["points"]) for l in net["lanes"]]
tree = STRtree(lines)
glyphs = []
for d in drawings:
    r = d["rect"]
    if not is_ink(d["fill"]) or r.y0 > 1290 or not (0.8 < r.width < 12 and 0.8 < r.height < 12): continue
    if abs(r.width - r.height) < 0.3 and r.width < 3.4: continue  # точки остановок
    pt = Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
    i = tree.nearest(pt)
    if lines[i].distance(pt) >= 2.0: continue
    ln = lines[i]; s = ln.project(pt)
    a, b = ln.interpolate(max(0, s - 2)), ln.interpolate(min(ln.length, s + 2))
    ang = math.atan2(b.y - a.y, b.x - a.x)
    lane_rgb = tuple(int(net["lanes"][i]["color"][k:k + 2], 16) for k in (1, 3, 5))
    cands = [n for n, c in num_color.items() if cdist(c, lane_rgb) <= 1]
    scores = {}
    for cand in (ang, ang + math.pi):
        ras = raster(subpaths(d["items"]), cand)
        for n in cands:
            scores[n] = max(scores.get(n, 0), iou(ras, templates[n]))
    rank = sorted(scores.items(), key=lambda kv: -kv[1])
    best = (rank[0][1], rank[0][0]) if rank else (0, None)
    glyphs.append({"lane": net["lanes"][i]["id"], "x": pt.x, "y": pt.y, "s": s, "num": best[1], "score": round(best[0], 2), "second": [rank[1][0], round(rank[1][1], 2)] if len(rank) > 1 else None})

json.dump({"glyphs": glyphs}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
print("глифов на линиях:", len(glyphs))
import collections
print(collections.Counter(g["num"] for g in glyphs))
print("низкая уверенность (<0.55):", sum(1 for g in glyphs if g["score"] < 0.55))

# --- сводка по линиям: принимаем глифы с уверенностью >= 0.6
MIN = 0.6
by_lane = {}
for g in glyphs:
    if g["num"] and g["score"] >= MIN:
        by_lane.setdefault(g["lane"], collections.Counter())[g["num"]] += 1
summary = {ln["id"]: dict(by_lane.get(ln["id"], {})) for ln in net["lanes"]}
json.dump({"glyphs": glyphs, "lanes": summary}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
labeled = {k: v for k, v in summary.items() if v}
print("линий с номером:", len(labeled), "из", len(summary))
print("неоднозначные:", {k: v for k, v in labeled.items() if len(v) > 1})
print("без номера:", [k for k, v in summary.items() if not v])

# --- распространение по соседям: конец линии рядом с концом линии того же цвета (<= 4 пт)
ends = {ln["id"]: (Point(ln["points"][0]), Point(ln["points"][-1])) for ln in net["lanes"]}
color_of = {ln["id"]: ln["colorKey"] for ln in net["lanes"]}
routes = {k: sorted(v) for k, v in labeled.items()}
inferred = set()
for _ in range(3):
    for lid in [k for k in summary if k not in routes]:
        nbrs = {o for o in routes if color_of[o] == color_of[lid] and any(a.distance(b) <= 4 for a in ends[lid] for b in ends[o])}
        nums = {n for o in nbrs for n in routes[o]}
        if len(nums) == 1:
            routes[lid] = sorted(nums); inferred.add(lid)
# Ручные решения по исключению: у номера нет других линий, цвет и положение совпадают. Проверить глазами.
OVERRIDES = {"brown-9": "11", "brown-12": "11", "lime-0": "23", "amber-3": "А", "orange-3": "31", "green2-0": "Т1", "green2-2": "21",
             "gray-0": "12", "gray-1": "28"}
# Красные линии у Новогиреево идут парой без пересечений: Т2 — верхняя (внешняя), 36 — нижняя (по образцу заказчика).
# Перемычку red-13 у излома скелет склеил в одну линию — заменяется двумя параллельными (см. ниже).
FORCED = {"red-2": ["Т2"], "red-10": ["Т2"], "red-15": ["Т2"], "red-1": ["36"], "red-6": ["36"]}
for lid, num in OVERRIDES.items():
    if lid in summary and lid not in routes:
        routes[lid] = [num]; inferred.add(lid)
for lid, nums in FORCED.items():
    if lid in summary:
        routes[lid] = nums; inferred.discard(lid)
missing = [k for k in summary if k not in routes]
print("выведено по соседям:", len(inferred), "| без номера:", missing)
def isolated_stub(ln):  # цветные «бирки» номеров на концах: короткие и ни с чем не соединены
    ls = LineString(ln["points"])
    if ls.length >= 15: return False
    return not any(o["id"] != ln["id"] and any(Point(e).distance(Point(p)) <= 4 for e in (ln["points"][0], ln["points"][-1]) for p in (o["points"][0], o["points"][-1])) for o in net["lanes"])


stubs = [ln["id"] for ln in net["lanes"] if isolated_stub(ln)]
net["lanes"] = [ln for ln in net["lanes"] if ln["id"] not in stubs]
print("убрано коротких бирок:", len(stubs))
# Излом у Новогиреево: скелет склеил пару в одну точку. Обрезаем склеенные концы и соединяем
# каждую линию своей перемычкой (Т2 снаружи, 36 внутри), чтобы они шли параллельно и не пересекались.
def trim(lid, start=0, end=0):
    ln = next(l for l in net["lanes"] if l["id"] == lid)
    ln["points"] = ln["points"][start:len(ln["points"]) - end or None]


if any(l["id"] == "red-13" for l in net["lanes"]):
    trim("red-10", start=2); trim("red-1", start=3); trim("red-15", end=1); trim("red-6", end=2)
    net["lanes"] = [l for l in net["lanes"] if l["id"] != "red-13"]
    red = next(l["color"] for l in net["lanes"] if l["id"] == "red-10")
    n = (0.71, -0.70)
    link = {"red-13t2": ("Т2", [[974.5, 545.0], [984.6, 554.9], [1001.1, 571.9], [1006.5, 573.8]]),
            "red-1336": ("36", [[972.0, 548.8], [982.4, 557.1], [998.9, 574.1], [1004.8, 578.0]])}
    for lid, (num, pts) in link.items():
        net["lanes"].append({"id": lid, "colorKey": "red", "color": red, "points": pts})
        routes[lid] = [num]
for ln in net["lanes"]:
    ln["routes"] = routes.get(ln["id"], [])
    if ln["id"] in inferred: ln["inferred"] = True
net["legend"] = {n: "#%02x%02x%02x" % c for n, c in num_color.items()}
net["legend"].update({"Т1": "#4bb85e", "Т2": "#ef4046", "12": "#a1a2a3", "28": "#a1a2a3"})  # нет собственного эталона: цвета сверены по легенде
NET.write_text(json.dumps(net, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
lab = [{"lane": g["lane"], "x": round(g["x"], 1), "y": round(g["y"], 1), "num": g["num"]} for g in glyphs if g["num"] and g["score"] >= MIN]
(OUT.parent / "lane-glyphs.json").write_text(json.dumps(lab, ensure_ascii=False), encoding="utf-8")
