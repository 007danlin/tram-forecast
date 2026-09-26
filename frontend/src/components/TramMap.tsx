import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MAP_BASE, type Network } from "../map/loadMap";
import { smoothRoute } from "../map/smoothRoutes";
import { Icon } from "./ui";
import {
  groupRouteLanes,
  routeFeatures,
  routeSelectionName,
} from "../map/routeSelection";
import "./tram-map.css";

type View = { cx: number; cy: number; zoom: number };
const DEFAULT_CENTER = { cx: 562.3, cy: 646.4 },
  DEFAULT_ZOOM = 4,
  MAX_ZOOM = 14;
const BOUNDS = { x: 62, y: 112, w: 1065, h: 1198 };
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

type Props = {
  map: Network | null;
  mapProblem: string;
  selectedRoute: string;
  onRouteChange: (route: string) => void;
};
export const TramMap = memo(function TramMap({
  map,
  mapProblem,
  selectedRoute,
  onRouteChange,
}: Props) {
  const [visualProblem, setVisualProblem] = useState("");
  const problem = mapProblem || visualProblem;
  const [visualReady, setVisualReady] = useState(false);
  const [size, setSize] = useState({ w: 0, h: 0 }),
    [view, setView] = useState<View>({ ...DEFAULT_CENTER, zoom: DEFAULT_ZOOM });
  const [candidates, setCandidates] = useState<string[]>([]);
  const viewportRef = useRef<HTMLDivElement>(null),
    pointers = useRef(new Map<number, { x: number; y: number }>());
  const down = useRef<{ x: number; y: number } | null>(null),
    moved = useRef(false),
    gesture = useRef<{ dist: number; zoom: number } | null>(null);
  const features = useMemo(
    () => (map ? routeFeatures(map, selectedRoute) : null),
    [map, selectedRoute],
  );
  const selection = features?.selection;
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
  const focusRoute = useCallback(() => {
    if (!selection || !size.w || !size.h) return;
    const points = selection.lanes.flatMap((lane) => lane.points);
    for (const stop of features?.stops ?? []) points.push([stop.x, stop.y]);
    for (const group of features?.stationSymbols ?? []) {
      const [x0, y0, x1, y1] = group.bounds;
      points.push([x0, y0], [x1, y1]);
    }
    for (const label of features?.labels ?? []) {
      const angle = (label.angle * Math.PI) / 180;
      for (const line of label.lines)
        for (const dx of [-line.w / 2, line.w / 2])
          for (const dy of [-label.fs / 2, label.fs / 2]) {
            const x = line.dx + dx,
              y = line.dy + dy;
            points.push([
              label.x + x * Math.cos(angle) - y * Math.sin(angle),
              label.y + x * Math.sin(angle) + y * Math.cos(angle),
            ]);
          }
    }
    const xs = points.map((p) => p[0]),
      ys = points.map((p) => p[1]);
    const x = Math.min(...xs),
      y = Math.min(...ys),
      w = Math.max(...xs) - x,
      h = Math.max(...ys) - y;
    setView(
      constrain({
        cx: x + w / 2,
        cy: y + h / 2,
        zoom:
          Math.min(
            Math.max(1, size.w - 112) / (w + 18),
            Math.max(1, size.h - 100) / (h + 18),
          ) / fit,
      }),
    );
  }, [selection, features, size, constrain, fit]);
  const lastFocused = useRef<string | null>(null);
  const initialSelection = useRef(true);
  useEffect(() => {
    if (!map || !size.w || !size.h || lastFocused.current === selectedRoute)
      return;
    const showMobileNetwork = initialSelection.current && window.matchMedia('(max-width:699px)').matches;
    if (selectedRoute) initialSelection.current = false;
    lastFocused.current = selectedRoute;
    setCandidates([]);
    if (showMobileNetwork) {
      setView({cx:BOUNDS.x + BOUNDS.w / 2, cy:BOUNDS.y + BOUNDS.h / 2, zoom:minimum});
    } else focusRoute();
  }, [map, size, selectedRoute, focusRoute, minimum]);
  const reset = () =>
    selection
      ? focusRoute()
      : setView({ ...DEFAULT_CENTER, zoom: DEFAULT_ZOOM });
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
  const routeGroups = useMemo(() => groupRouteLanes(map?.lanes ?? []), [map]);
  const curves = useMemo(
    () =>
      new Map(
        routeGroups
          .flatMap((group) => smoothRoute(group.lanes))
          .map((lane) => [lane.id, lane]),
      ),
    [routeGroups],
  );
  const groupsByLane = useMemo(
    () =>
      new Map(
        routeGroups.flatMap((group) =>
          group.lanes.map((lane) => [lane.id, group] as const),
        ),
      ),
    [routeGroups],
  );
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
    const hits = routeGroups
      .map((group) => ({
        id: group.id,
        d:
          Math.min(
            ...group.lanes.map((l) => distance(x, y, curves.get(l.id)!.points)),
          ) * scale,
      }))
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
    const hit = groupsByLane.get(hits[0]?.id);
    onRouteChange(
      hit?.routes.includes(selectedRoute)
        ? selectedRoute
        : (hit?.routes[0] ?? ""),
    );
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
      onRouteChange("");
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
  const hitLines = useMemo(
    () =>
      map?.lanes.map((l) => (
        <path
          key={l.id}
          data-lane={l.id}
          d={curves.get(l.id)!.d}
          fill="none"
          stroke="transparent"
          strokeWidth="12"
          vectorEffect="non-scaling-stroke"
        />
      )),
    [map, curves],
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
          aria-label="Схема трамваев. Стрелки — перемещение, плюс и минус — масштаб, 0 — исходный вид. Выбор маршрута также доступен в верхнем списке."
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
            <g
              className="map-layer map-layer--reference"
              data-focused={!!selection}
            >
              <image
                href={`${MAP_BASE}schematic.svg`}
                x="0"
                y="0"
                width={pageW}
                height={pageH}
                onLoad={() => setVisualReady(true)}
                onError={() =>
                  setVisualProblem(
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
                {/* All halos first: an end cap must not erase the next segment. */}
                {selection.lanes.map((lane) => (
                  <path
                    key={`halo-${lane.id}`}
                    d={curves.get(lane.id)!.d}
                    stroke="#fff"
                    strokeWidth="4.6"
                  />
                ))}
                {selection.lanes.map((lane) => (
                  <path
                    key={lane.id}
                    data-selected-lane={lane.id}
                    d={curves.get(lane.id)!.d}
                    stroke={lane.color}
                    strokeWidth="3.2"
                  />
                ))}
                {features?.stops.map((stop) => (
                  <circle
                    key={stop.id}
                    data-selected-stop={stop.id}
                    cx={stop.x}
                    cy={stop.y}
                    r="0.8"
                    fill="#fff"
                    stroke="none"
                  />
                ))}
                {features?.stationSymbols.map((group) => (
                  <use
                    key={group.id}
                    data-selected-symbol={group.id}
                    href={`${MAP_BASE}schematic.svg#station-symbol-${group.id}`}
                    stroke="none"
                  />
                ))}
                {features?.labels.map((label) => (
                  <use
                    key={label.id}
                    data-selected-label={label.id}
                    href={`${MAP_BASE}schematic.svg#station-label-${label.id}`}
                    stroke="none"
                  />
                ))}
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
                className="tram-map__btn tram-map__home"
                aria-label="Восстановить исходный вид"
                onClick={reset}
              >
                <Icon name="home" />
              </button>
              <button
                className="tram-map__btn tram-map__fit"
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
                <span className="tram-map__fit-label" aria-hidden="true">Вся</span>
              </button>
            </div>
            {!!candidates.length && (
              <div
                className="tram-map__candidates"
                role="group"
                aria-label="Уточните линию"
              >
                <p>Рядом несколько линий</p>
                {candidates.map((id) => {
                  const group = groupsByLane.get(id)!;
                  return (
                    <button
                      key={id}
                      onClick={() => {
                        onRouteChange(
                          group.routes.includes(selectedRoute)
                            ? selectedRoute
                            : group.routes[0],
                        );
                        setCandidates([]);
                      }}
                    >
                      {routeSelectionName(group)}
                    </button>
                  );
                })}
                <button onClick={() => setCandidates([])}>Отмена</button>
              </div>
            )}
            {selection && (
              <p className="tram-map__selected" role="status">
                <span className="tram-map__mobile-title">Схема трамваев · </span>
                {routeSelectionName(selection)}
                <button
                  aria-label="Снять выделение линии"
                  onClick={() => onRouteChange("")}
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
