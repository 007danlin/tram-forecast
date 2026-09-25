"""Остановки всех линий: точки и подписи из PDF, тексты подписей — OCR (Windows, русский).

Запуск из корня: python scripts/map/build_stops.py   (после extract_lanes.py и label_lanes.py)
Требуется Windows 10/11 с языком OCR «ru» и: pip install winocr shapely pillow pymupdf
Шаги:
  1. точки остановок — круги 1.4–2.1 пт (белые/красные/зелёные) на осевых линиях;
  2. подписи — тёмные контуры текста, склеенные в строки; угол — по минимальному повёрнутому прямоугольнику;
  3. подпись привязывается к точке, если точка лежит на оси текста рядом с его концом;
  4. текст — OCR строки, повёрнутой в горизонталь (пробуются угол и угол+180);
  5. необязательные исправления OCR: data/tram-map/stop-overrides.json {"text": {"как распознано": "как правильно"}, "at": [[x, y, "текст"]]}.
Пишет labels и stops в frontend/public/map-local/network.json и отчёт data/tram-map/stops-report.json.
"""
import asyncio, json, math, re, warnings
from pathlib import Path

import pymupdf, winocr
from PIL import Image, ImageChops, ImageDraw
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
NET = ROOT / "frontend/public/map-local/network.json"
OVR = ROOT / "data/tram-map/stop-overrides.json"
K = 10  # пикселей на пункт для OCR
net = json.loads(NET.read_text(encoding="utf-8"))
page = pymupdf.open(ROOT / "data/tram-map/trammap_15_04_26-2.pdf")[0]
drawings = [d for d in page.get_drawings() if d.get("fill") and 100 < d["rect"].y0 < 1290]
lanes = [LineString(l["points"]) for l in net["lanes"]]
ltree = STRtree(lanes)


def rgb(f): return tuple(round(v * 255) for v in f)
def is_dark(f): return all(v < 0.2 for v in f)


# ---------- 1. точки остановок
DOT_COLORS = {(255, 255, 255), (239, 64, 70), (75, 184, 94), (75, 184, 96)}
dots = []
for d in drawings:
    r = d["rect"]
    if rgb(d["fill"]) not in DOT_COLORS or not (1.4 < r.width < 2.1 and abs(r.width - r.height) < 0.3) or len(d["items"]) not in (4, 6):
        continue
    c = Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
    i = ltree.nearest(c)
    if lanes[i].distance(c) < 1.2:
        dots.append({"lane": i, "pt": c, "s": lanes[i].project(c)})
print("точек на линиях:", len(dots))


# ---------- 2. подписи: тёмный текст вне полос линий
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
                cur.append((u**3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t**3 * p3.x, u**3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t**3 * p3.y)); last = cur[-1]
    if len(cur) > 2: subs.append(cur)
    return subs


glyphs = []  # (Polygon для группировки, subpaths)
for d in drawings:
    r = d["rect"]
    if not is_dark(d["fill"]) or r.height > 100 or r.width > 100 or max(r.width, r.height) < 1.2:
        continue
    c = Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
    if lanes[ltree.nearest(c)].distance(c) < 2.2:  # текст внутри полосы (номер маршрута) — не подпись
        continue
    subs = subpaths(d["items"])
    polys = [Polygon(s).buffer(0) for s in subs if len(s) > 2]
    poly = unary_union([p for p in polys if not p.is_empty])
    if not poly.is_empty:
        glyphs.append((poly, subs))
def rect_of(poly):
    rect = poly.minimum_rotated_rectangle
    if rect.geom_type != "Polygon": return None
    pts = list(rect.exterior.coords)[:4]
    e = [(pts[(i + 1) % 4][0] - pts[i][0], pts[(i + 1) % 4][1] - pts[i][1]) for i in range(2)]
    ex = max(e, key=lambda v: math.hypot(*v)); L = math.hypot(*ex); H = min(math.hypot(*e[0]), math.hypot(*e[1]))
    th = math.degrees(math.atan2(ex[1], ex[0]))
    while th > 90: th -= 180
    while th <= -90: th += 180
    return {"c": rect.centroid, "th": th, "L": L, "H": H}


# слова: близкие контуры (зазор < 1.2 пт); затем слова одной подписи — соосные, на одной линии текста, зазор < 3.2 пт
word_geoms = unary_union([g[0].buffer(0.6) for g in glyphs])
word_geoms = list(word_geoms.geoms) if isinstance(word_geoms, MultiPolygon) else [word_geoms]
words = []
for wg in word_geoms:
    members = [g for g in glyphs if g[0].representative_point().within(wg)]
    if not members: continue
    raw = unary_union([g[0] for g in members]); r0 = rect_of(raw)
    if r0: words.append({**r0, "members": members, "poly": raw})
parent = list(range(len(words)))
def find(i):
    while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
    return i
wtree = STRtree([w["poly"] for w in words])
for i, wi in enumerate(words):
    for j in wtree.query(wi["poly"].buffer(3.2)):
        if j <= i: continue
        wj = words[j]
        if wi["poly"].distance(wj["poly"]) > 3.2: continue
        ref = wi if wi["L"] >= wj["L"] else wj
        u = (math.cos(math.radians(ref["th"])), math.sin(math.radians(ref["th"])))
        vx, vy = wj["c"].x - wi["c"].x, wj["c"].y - wi["c"].y
        if abs(vx * u[1] - vy * u[0]) <= 1.6 and abs(wi["H"] - wj["H"]) <= 1.8:
            parent[find(i)] = find(j)
groups = {}
for i, w in enumerate(words): groups.setdefault(find(i), []).append(w)
labels = []
for ws in groups.values():
    members = [m for w in ws for m in w["members"]]
    raw = unary_union([w["poly"] for w in ws]); r0 = rect_of(raw)
    if not r0 or r0["L"] < 6 or r0["H"] > 8: continue
    labels.append({**r0, "members": members, "text": None, "lanes": set()})
print("кандидатов в подписи:", len(labels))


# ---------- 4. OCR
def render(lb, angle):
    c, s = math.cos(math.radians(-angle)), math.sin(math.radians(-angle))
    cx, cy = lb["c"].x, lb["c"].y
    w, h = int(lb["L"] * K) + 60, int(lb["H"] * K) + 60
    img = Image.new("1", (w, h), 0)
    for _, subs in lb["members"]:  # внутри одного контура дырки — XOR, разные контуры (в т.ч. дубли) — OR
        one = Image.new("1", (w, h), 0)
        for sp in subs:
            pts = [((x - cx) * c - (y - cy) * s) * K + w / 2 for x, y in sp], [((x - cx) * s + (y - cy) * c) * K + h / 2 for x, y in sp]
            layer = Image.new("1", (w, h), 0)
            ImageDraw.Draw(layer).polygon(list(zip(*pts)), fill=1)
            one = ImageChops.logical_xor(one, layer)
        img = ImageChops.logical_or(img, one)
    return ImageChops.invert(img.convert("L"))  # чёрный текст на белом


def plausible(t):
    letters = re.findall(r"[А-Яа-яЁё]", t)
    junk = re.findall(r"[^А-Яа-яЁё0-9 ,.\-«»()/–—\"'№A-Za-z]", t)
    return len(letters) - 3 * len(junk) - 2 * len(re.findall(r"[A-Za-z]", t))


async def ocr_all(items):
    out = {}
    for k in items:
        lb = labels[k]; best = ("", -99, 0, [])
        for delta in (0, -4, 4, -8, 8):  # угол минимального прямоугольника бывает неточным на несколько градусов
            # текст не бывает вверх ногами: разворот на 180° пробуем только для вертикальных подписей
            for ang in ((lb["th"] + delta, lb["th"] + delta + 180) if abs(lb["th"]) > 80 else (lb["th"] + delta,)):
                img = render(lb, ang)
                r = await winocr.recognize_pil(img, "ru")
                text = " ".join(l.text for l in r.lines).strip()
                sc = plausible(text)
                if sc > best[1]:
                    W, H = img.size
                    info = []
                    for l in r.lines:  # строка: текст и рамка по словам, в пунктах PDF относительно центра подписи (вдоль текста, поперёк)
                        rs = [w.bounding_rect for w in l.words]
                        if not rs: continue
                        x0, x1 = min(q.x for q in rs), max(q.x + q.width for q in rs)
                        y0, y1 = min(q.y for q in rs), max(q.y + q.height for q in rs)
                        info.append({"t": l.text, "dx": ((x0 + x1) / 2 - W / 2) / K, "dy": ((y0 + y1) / 2 - H / 2) / K, "w": (x1 - x0) / K})
                    best = (text, sc, ang, info)
            if best[1] >= 4: break
        out[k] = best
    return out


# ---------- 4а. OCR всех кандидатов ДО привязки: пустые и нечитаемые (стрелки, значки, обрывки) отбрасываем
def clean(t):
    t = re.sub(r"\s+", " ", t).strip(" •·,'\"").lstrip(".")
    t = re.sub(r"(?<=[а-яё])- (?=[а-яё])", "-", t)
    t = t.replace("««", "«").replace("»»", "»")
    t = re.sub(r"^(?:\d{1,2}|[a-zа-я]) (?=[А-ЯЁ])", "", t)  # значок метро/линии, прочитанный как цифра/буква
    t = re.sub(r" [a-zа-я]$", "", t)
    return t


ovr_all = json.loads(OVR.read_text(encoding="utf-8")) if OVR.exists() else {}
overrides, at_fix = ovr_all.get("text", {}), ovr_all.get("at", [])
res = asyncio.run(ocr_all(list(range(len(labels)))))
review = []
keep = []
for k, lb in enumerate(labels):
    text, sc, ang, info = res[k]
    raw_text = clean(text)
    text = overrides.get(raw_text, raw_text)
    lb["fixed"] = text != raw_text
    for fx, fy, ft in at_fix:
        if abs(fx - lb["c"].x) < 3 and abs(fy - lb["c"].y) < 3: text = ft
    if not text or re.fullmatch(r"[\d\s]+", text) or sc < 2:
        if lb["L"] > 8 and lb["H"] > 2.5: review.append({"text": text, "score": sc, "x": round(lb["c"].x, 1), "y": round(lb["c"].y, 1)})
        continue
    lb["text"], lb["angle"], lb["info"] = text, ang, info
    keep.append(lb)
labels = keep
print("подписей после OCR:", len(labels), "| отброшено нечитаемых:", len(res) - len(labels))


# ---------- 3. привязка точек к подписям
# 3а. Подпись стоит у края ряда точек: ближайшая к её торцу точка — «первичная».
# 3б. Остальные линии пучка получают ту же подпись по ряду (точки в одном поперечном ряду).
def tangent(dt):
    ls = lanes[dt["lane"]]
    a, b = ls.interpolate(max(0, dt["s"] - 1.5)), ls.interpolate(min(ls.length, dt["s"] + 1.5))
    n = math.hypot(b.x - a.x, b.y - a.y) or 1
    return ((b.x - a.x) / n, (b.y - a.y) / n)


for dt in dots: dt["label"], dt["lscore"] = None, 1e9
def attach(gap, only_free_labels, only_free_dots):
    for k, lb in enumerate(labels):
        if only_free_labels and lb["lanes"]: continue
        u = (math.cos(math.radians(lb["th"])), math.sin(math.radians(lb["th"])))
        ends = [Point(lb["c"].x + sg * u[0] * lb["L"] / 2, lb["c"].y + sg * u[1] * lb["L"] / 2) for sg in (-1, 1)]
        cand = [(min(e.distance(dt["pt"]) for e in ends), dt) for dt in dots if not (only_free_dots and dt["label"] is not None)]
        cand = [(d, dt) for d, dt in cand if d <= gap]
        if not cand: continue
        dist0, prim = min(cand, key=lambda c: c[0])
        lb["lanes"].add(prim["lane"])
        if dist0 < prim["lscore"]: prim["label"], prim["lscore"] = k, dist0
        tau = tangent(prim); nrm = (-tau[1], tau[0])
        for dt in dots:
            if dt is prim or dt["lane"] == prim["lane"] or (only_free_dots and dt["label"] is not None): continue
            vx, vy = dt["pt"].x - prim["pt"].x, dt["pt"].y - prim["pt"].y
            along, perp = vx * tau[0] + vy * tau[1], abs(vx * nrm[0] + vy * nrm[1])
            if abs(along) <= 1.8 and perp <= 34:
                sc = dist0 + perp * 0.3
                lb["lanes"].add(dt["lane"])
                if sc < dt["lscore"]: dt["label"], dt["lscore"] = k, sc


for dt in dots: dt["label"], dt["lscore"] = None, 1e9
attach(6.0, False, False)
attach(18.0, True, True)  # подписи со значками метро: текст отстоит от точек дальше
attach(30.0, False, True)  # конечные с плашками номеров: подпись ещё дальше; только для точек, оставшихся без подписи
used = [i for i, lb in enumerate(labels) if lb["lanes"]]
print("подписей, привязанных к точкам:", len(used), "| точек без подписи:", sum(1 for d in dots if d["label"] is None))


out_labels, remap = [], {}
for k in used:
    lb = labels[k]; ang = lb["angle"]
    fs = 5.2 if 4.0 <= lb["H"] <= 4.7 else 4.1  # жирные крупные — конечные; высота включает надстрочные знаки, поэтому только две ступени
    remap[k] = f"l{len(out_labels):03d}"
    lines = [] if lb.get("fixed") and chr(10) not in lb["text"] else lb["info"]
    lines = lines or [{"t": lb["text"], "dx": 0.0, "dy": 0.0, "w": lb["L"]}]
    txt = lb["text"]
    if len(lines) == 1:
        lines[0]["t"] = txt.replace(chr(10), " ")
    elif chr(10) in txt and len(txt.split(chr(10))) == len(lines):
        for ln, t in zip(lines, txt.split(chr(10))): ln["t"] = t
    name = re.sub(r"(?<=[а-яё])- (?=[а-яё])", "", txt.replace(chr(10), " "))
    out_labels.append({"id": remap[k], "text": name, "x": round(lb["c"].x, 1), "y": round(lb["c"].y, 1), "angle": round(ang if ang <= 180 else ang - 360, 1),
                       "lines": [{"t": ln["t"], "dx": round(ln["dx"], 1), "dy": round(ln["dy"], 1), "w": round(ln["w"], 1)} for ln in lines],
                       "fs": fs, "bold": fs >= 5.0, "lanes": [net["lanes"][i]["id"] for i in sorted(lb["lanes"])]})
stops = []
for dt in sorted(dots, key=lambda d: (d["lane"], d["s"])):
    ln = net["lanes"][dt["lane"]]
    n_on = sum(1 for s in stops if s["lane"] == ln["id"]) + 1
    stops.append({"id": f"s-{ln['id']}-{n_on:02d}", "routes": ln.get("routes", []), "lane": ln["id"], "x": round(dt["pt"].x, 1), "y": round(dt["pt"].y, 1),
                  "label": remap.get(dt["label"])})
net["labels"], net["stops"] = out_labels, stops
NET.write_text(json.dumps(net, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
(ROOT / "data/tram-map/stops-report.json").write_text(json.dumps({"review": review, "unlabeled_stops": [s["id"] for s in stops if not s["label"]]}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"подписей: {len(out_labels)}, остановок: {len(stops)}, без подписи: {sum(1 for s in stops if not s['label'])}, на проверку: {len(review)}")
