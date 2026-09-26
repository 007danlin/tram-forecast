import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { loadNetwork, MAP_BASE, type Lane, type Network } from "../map/loadMap";
import { Icon } from "./ui";
import "./tram-map.css";

type View = { cx: number; cy: number; zoom: number };
const DEFAULT_CENTER = { cx: 562.3, cy: 646.4 },
  DEFAULT_ZOOM = 4,
  MAX_ZOOM = 14;
const BOUNDS = { x: 62, y: 112, w: 1065, h: 1178 };
const clamp = (v: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, v));
function distance(px: number, py: number, points: [number, number][]) {
  let best = Infinity;
  for (let i = 1; i < points.length; i++) {
    const [x, y] = points[i - 1],
      [xx, yy] = points[i],
      dx = xx - x,
      dy = yy - y;
    const t = clamp(
      ((px - x) * dx + (py - y) * dy) / (dx * dx + dy * dy || 1),
      0,
      1,
    );
    best = Math.min(best, Math.hypot(px - x - t * dx, py - y - t * dy));
  }
  return best;
}
const laneName = (l: Lane, index: number) =>
  `${l.routes?.map((n) => "№ " + n).join(", ") || "Линия"} · участок ${index + 1}${l.inferred && !l.referenceVerified ? " · номер уточняется" : ""}`;

export const TramMap = memo(function TramMap() {
  const [map, setMap] = useState<Network | null>(null),
    [problem, setProblem] = useState(""),
    [visualReady, setVisualReady] = useState(false);
  const [size, setSize] = useState({ w: 0, h: 0 }),
    [view, setView] = useState<View>({ ...DEFAULT_CENTER, zoom: DEFAULT_ZOOM });
  const [selected, setSelected] = useState<string | null>(null),
    [candidates, setCandidates] = useState<string[]>([]),
    [listOpen, setListOpen] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null),
    pointers = useRef(new Map<number, { x: number; y: number }>());
  const down = useRef<{ x: number; y: number } | null>(null),
    moved = useRef(false),
    gesture = useRef<{ dist: number; zoom: number } | null>(null);
  useEffect(() => {
    const c = new AbortController();
    loadNetwork(c.signal)
      .then(setMap)
      .catch((e) => {
        if (!c.signal.aborted)
          setProblem(
            e.message === "MISSING"
              ? "Карта временно недоступна. Прогноз и CSV продолжают работать."
              : e.message,
          );
      });
    return () => c.abort();
  }, []);
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const measure = () => {
      if (el.clientWidth && el.clientHeight)
        setSize({ w: el.clientWidth, h: el.clientHeight });
    };
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, []);
  const pageW = map?.viewBox[2] ?? 1190.55,
    pageH = map?.viewBox[3] ?? 1683.78;
  const fit = size.w && size.h ? Math.max(size.w / pageW, size.h / pageH) : 1;
  const minimum =
    size.w && size.h
      ? Math.min(size.w / BOUNDS.w, size.h / BOUNDS.h) / fit
      : 0.1;
  const constrain = useCallback(
    (v: View) => {
      const zoom = clamp(v.zoom, minimum, MAX_ZOOM),
        w = size.w / (fit * zoom),
        h = size.h / (fit * zoom);
      return {
        zoom,
        cx:
          w >= BOUNDS.w
            ? BOUNDS.x + BOUNDS.w / 2
            : clamp(v.cx, BOUNDS.x + w / 2, BOUNDS.x + BOUNDS.w - w / 2),
        cy:
          h >= BOUNDS.h
            ? BOUNDS.y + BOUNDS.h / 2
            : clamp(v.cy, BOUNDS.y + h / 2, BOUNDS.y + BOUNDS.h - h / 2),
      };
    },
    [size, fit, minimum],
  );
  const zoomAround = useCallback(
    (v: View, factor: number, x: number, y: number) => {
      const zoom = clamp(v.zoom * factor, minimum, MAX_ZOOM),
        k0 = fit * v.zoom,
        k1 = fit * zoom;
      return constrain({
        cx: v.cx + (x - size.w / 2) / k0 - (x - size.w / 2) / k1,
        cy: v.cy + (y - size.h / 2) / k0 - (y - size.h / 2) / k1,
        zoom,
      });
    },
    [fit, size, constrain, minimum],
  );
  const viewBox = useMemo(() => {
    const w = size.w / (fit * view.zoom),
      h = size.h / (fit * view.zoom);
    return `${view.cx - w / 2} ${view.cy - h / 2} ${w || 1} ${h || 1}`;
  }, [view, size, fit]);
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      setView((v) =>
        zoomAround(
          v,
          Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)),
          e.clientX - r.left,
          e.clientY - r.top,
        ),
      );
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [zoomAround]);
  const step = (factor: number) =>
    setView((v) => zoomAround(v, factor, size.w / 2, size.h / 2));
  const reset = () => setView({ ...DEFAULT_CENTER, zoom: DEFAULT_ZOOM });
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    if (!pointers.current.size) {
      down.current = { x: e.clientX, y: e.clientY };
      moved.current = false;
    }
    e.currentTarget.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      gesture.current = {
        dist: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
        zoom: view.zoom,
      };
      moved.current = true;
    }
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const prev = pointers.current.get(e.pointerId);
    if (!prev) return;
    if (
      down.current &&
      Math.hypot(e.clientX - down.current.x, e.clientY - down.current.y) > 5
    )
      moved.current = true;
    const cur = { x: e.clientX, y: e.clientY };
    pointers.current.set(e.pointerId, cur);
    if (pointers.current.size === 1) {
      setView((v) =>
        constrain({
          ...v,
          cx: v.cx - (cur.x - prev.x) / (fit * v.zoom),
          cy: v.cy - (cur.y - prev.y) / (fit * v.zoom),
        }),
      );
    } else if (gesture.current) {
      const [a, b] = [...pointers.current.values()],
        r = e.currentTarget.getBoundingClientRect();
      const target =
        (gesture.current.zoom * Math.hypot(a.x - b.x, a.y - b.y)) /
        gesture.current.dist;
      setView((v) =>
        zoomAround(
          v,
          target / v.zoom,
          (a.x + b.x) / 2 - r.left,
          (a.y + b.y) / 2 - r.top,
        ),
      );
    }
  };
  const onPointerUp = (e: React.PointerEvent) => {
    const wasTracked = pointers.current.delete(e.pointerId);
    gesture.current = null;
    if (pointers.current.size) return;
    const d = down.current;
    down.current = null;
    if (!wasTracked || e.type !== "pointerup" || !d || moved.current || !map)
      return;
    const rect = e.currentTarget.getBoundingClientRect(),
      scale = fit * view.zoom;
    const x = view.cx + (e.clientX - rect.left - size.w / 2) / scale,
      y = view.cy + (e.clientY - rect.top - size.h / 2) / scale;
    const radius = e.pointerType === "touch" ? 22 : 10;
    const hits = map.lanes
      .map((l) => ({ id: l.id, d: distance(x, y, l.points) * scale }))
      .filter((l) => l.d <= radius)
      .sort((a, b) => a.d - b.d);
    const ambiguous = hits.filter(
      (l) => l.d - (hits[0]?.d ?? 0) < (e.pointerType === "touch" ? 4 : 1.5),
    );
    if (ambiguous.length > 1) {
      setCandidates(ambiguous.map((l) => l.id));
      return;
    }
    setCandidates([]);
    setSelected(hits[0]?.id ?? null);
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    const pan = 60 / (fit * view.zoom);
    if (e.key === "+" || e.key === "=") {
      e.preventDefault();
      step(1.4);
    } else if (e.key === "-") {
      e.preventDefault();
      step(1 / 1.4);
    } else if (e.key === "0") {
      e.preventDefault();
      reset();
    } else if (e.key === "Escape") {
      if (e.currentTarget.closest("[aria-modal=true]")) return;
      setSelected(null);
      setCandidates([]);
    } else if (
      ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)
    ) {
      e.preventDefault();
      setView((v) =>
        constrain({
          ...v,
          cx:
            v.cx +
            (e.key === "ArrowLeft" ? -pan : e.key === "ArrowRight" ? pan : 0),
          cy:
            v.cy +
            (e.key === "ArrowUp" ? -pan : e.key === "ArrowDown" ? pan : 0),
        }),
      );
    }
  };
  const selection = map?.lanes.find((l) => l.id === selected);
  const hitLines = useMemo(
    () =>
      map?.lanes.map((l) => (
        <polyline
          key={l.id}
          data-lane={l.id}
          points={l.points.join(" ")}
          fill="none"
          stroke="transparent"
          strokeWidth="12"
          vectorEffect="non-scaling-stroke"
        />
      )),
    [map],
  );
  return (
    <section className="tram-map" aria-labelledby="tram-map-title">
      <h2 id="tram-map-title" className="sr-only">
        Схема трамваев Москвы
      </h2>
      <div className="tram-map__stage">
        <div
          ref={viewportRef}
          className="tram-map__viewport"
          tabIndex={0}
          role="application"
          aria-label="Схема трамваев. Стрелки — перемещение, плюс и минус — масштаб, 0 — исходный вид. Выбор линии также доступен в списке."
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onKeyDown={onKeyDown}
        >
          <svg
            viewBox={viewBox}
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
          >
            <g className="map-layer map-layer--reference">
              <image
                href={`${MAP_BASE}schematic.svg`}
                x="0"
                y="0"
                width={pageW}
                height={pageH}
                onLoad={() => setVisualReady(true)}
                onError={() =>
                  setProblem(
                    "Не удалось загрузить векторную схему. Обновите страницу; прогноз остаётся доступен.",
                  )
                }
              />
            </g>
            {selection && (
              <g
                className="map-layer map-layer--selection"
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
                pointerEvents="none"
              >
                <polyline
                  points={selection.points.join(" ")}
                  stroke="#fff"
                  strokeWidth="7.4"
                />
                <polyline
                  points={selection.points.join(" ")}
                  stroke={selection.color}
                  strokeWidth="5"
                />
              </g>
            )}
            <g className="map-layer map-layer--hit">{hitLines}</g>
          </svg>
        </div>
        {(!map || !visualReady || problem) && (
          <div className="tram-map__state" role={problem ? "alert" : "status"}>
            {problem || "Загружаем векторную схему…"}
          </div>
        )}
        {map && !problem && (
          <>
            <div className="tram-map__controls">
              <button
                className="tram-map__btn"
                aria-label="Увеличить"
                onClick={() => step(1.5)}
              >
                +
              </button>
              <button
                className="tram-map__btn"
                aria-label="Уменьшить"
                onClick={() => step(1 / 1.5)}
              >
                −
              </button>
              <button
                className="tram-map__btn"
                aria-label="Восстановить исходный вид"
                onClick={reset}
              >
                <Icon name="home" />
              </button>
              <button
                className="tram-map__btn"
                aria-label="Вся схема"
                onClick={() =>
                  setView({
                    cx: BOUNDS.x + BOUNDS.w / 2,
                    cy: BOUNDS.y + BOUNDS.h / 2,
                    zoom: minimum,
                  })
                }
              >
                <Icon name="expand" />
              </button>
            </div>
            <div className="tram-map__selection-tools">
              <button
                className="map-list-toggle"
                aria-expanded={listOpen}
                aria-controls="map-line-list"
                onClick={() => setListOpen((v) => !v)}
              >
                Линии схемы <Icon name="chevron" />
              </button>
              {listOpen && (
                <div className="tram-map__list" id="map-line-list">
                  <label>
                    Выбрать линию
                    <select
                      aria-label="Выбрать линию"
                      value={selected ?? ""}
                      onChange={(e) => {
                        setSelected(e.target.value || null);
                        setCandidates([]);
                      }}
                    >
                      <option value="">Без выделения</option>
                      {map.lanes.map((l, i) => (
                        <option key={l.id} value={l.id}>
                          {laneName(l, i)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p>
                    Схема 2026 года. Выбор линии пока не связан с прогнозом.
                  </p>
                </div>
              )}
            </div>
            {!!candidates.length && (
              <div
                className="tram-map__candidates"
                role="group"
                aria-label="Уточните линию"
              >
                <p>Рядом несколько линий</p>
                {candidates.map((id) => {
                  const index = map.lanes.findIndex((l) => l.id === id);
                  return (
                    <button
                      key={id}
                      onClick={() => {
                        setSelected(id);
                        setCandidates([]);
                      }}
                    >
                      {laneName(map.lanes[index], index)}
                    </button>
                  );
                })}
                <button onClick={() => setCandidates([])}>Отмена</button>
              </div>
            )}
            {selection && (
              <p className="tram-map__selected" role="status">
                {selection.routes?.map((n) => "№ " + n).join(", ")}
                {selection.inferred && !selection.referenceVerified
                  ? " · номер уточняется"
                  : ""}
                <button
                  aria-label="Снять выделение линии"
                  onClick={() => setSelected(null)}
                >
                  <Icon name="close" />
                </button>
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
});
