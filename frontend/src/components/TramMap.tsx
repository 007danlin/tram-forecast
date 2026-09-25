import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { byRouteNumber, inkFor, laneLabels, loadNetwork, type IconGroup, type Network } from '../map/loadMap';
import './tram-map.css';

type View = { cx: number; cy: number; zoom: number };
const MIN_ZOOM = 1;
const MAX_ZOOM = 14;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

const shapeEls = (g: IconGroup) => g.shapes.map((s, i) => <path key={i} d={s.d} fill={s.f} fillOpacity={s.o} fillRule={s.eo ? 'evenodd' : undefined} />);

export function TramMap() {
  const [map, setMap] = useState<Network | null>(null);
  const [problem, setProblem] = useState<'loading' | 'missing' | string>('loading');
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<View | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ dist: number; zoom: number } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    loadNetwork(controller.signal)
      .then(m => { setMap(m); setView({ cx: m.viewBox[2] / 2, cy: m.viewBox[3] / 2, zoom: 1 }); setProblem(''); })
      .catch(e => { if (!controller.signal.aborted) setProblem(e.message === 'MISSING' ? 'missing' : e.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, [map]);

  const [selected, setSelected] = useState<string | null>(null);
  const labels = useMemo(() => (map ? map.lanes.flatMap((l, i) => laneLabels(l, i).map(lb => ({ ...lb, lane: l }))) : []), [map]);
  const legend = useMemo(() => {
    const groups = new Map<string, string[]>();
    for (const [n, c] of Object.entries(map?.legend ?? {})) groups.set(c, [...(groups.get(c) ?? []), n]);
    return [...groups].map(([color, nums]) => ({ color, nums: nums.sort(byRouteNumber) }));
  }, [map]);
  const down = useRef<{ x: number; y: number } | null>(null);
  const pageW = map?.viewBox[2] ?? 1;
  const pageH = map?.viewBox[3] ?? 1;
  const fit = size.w && size.h ? Math.min(size.w / pageW, size.h / pageH) : 1;

  // Центр вида остаётся внутри страницы; при полном вписывании страница стоит по центру.
  const constrain = useCallback((v: View): View => {
    const zoom = clamp(v.zoom, MIN_ZOOM, MAX_ZOOM);
    const vw = size.w / (fit * zoom), vh = size.h / (fit * zoom);
    const cx = vw >= pageW ? pageW / 2 : clamp(v.cx, vw / 2, pageW - vw / 2);
    const cy = vh >= pageH ? pageH / 2 : clamp(v.cy, vh / 2, pageH - vh / 2);
    return { cx, cy, zoom };
  }, [size, fit, pageW, pageH]);

  // Масштаб вокруг точки экрана (px, py): точка под курсором остаётся на месте.
  const zoomAround = useCallback((v: View, factor: number, px: number, py: number): View => {
    const zoom = clamp(v.zoom * factor, MIN_ZOOM, MAX_ZOOM);
    const k0 = fit * v.zoom, k1 = fit * zoom;
    return constrain({
      cx: v.cx + (px - size.w / 2) / k0 - (px - size.w / 2) / k1,
      cy: v.cy + (py - size.h / 2) / k0 - (py - size.h / 2) / k1,
      zoom,
    });
  }, [fit, size, constrain]);

  const viewBox = useMemo(() => {
    if (!view || !size.w) return `0 0 ${pageW} ${pageH}`;
    const w = size.w / (fit * view.zoom), h = size.h / (fit * view.zoom);
    return `${view.cx - w / 2} ${view.cy - h / 2} ${w} ${h}`;
  }, [view, size, fit, pageW, pageH]);

  useEffect(() => { // wheel с preventDefault требует не-passive слушателя
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015));
      setView(v => v && zoomAround(v, factor, e.clientX - r.left, e.clientY - r.top));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomAround, map]);

  const onPointerDown = (e: React.PointerEvent) => {
    down.current = { x: e.clientX, y: e.clientY };
    e.currentTarget.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      gesture.current = { dist: Math.hypot(a.x - b.x, a.y - b.y), zoom: view?.zoom ?? 1 };
    }
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const prev = pointers.current.get(e.pointerId);
    if (!prev) return;
    const cur = { x: e.clientX, y: e.clientY };
    pointers.current.set(e.pointerId, cur);
    if (pointers.current.size === 1) {
      setView(v => v && constrain({ ...v, cx: v.cx - (cur.x - prev.x) / (fit * v.zoom), cy: v.cy - (cur.y - prev.y) / (fit * v.zoom) }));
    } else if (pointers.current.size === 2 && gesture.current) {
      const [a, b] = [...pointers.current.values()];
      const r = e.currentTarget.getBoundingClientRect();
      const target = gesture.current.zoom * Math.hypot(a.x - b.x, a.y - b.y) / gesture.current.dist;
      setView(v => v && zoomAround(v, target / v.zoom, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top));
    }
  };
  const onPointerUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId); gesture.current = null;
    const d = down.current; down.current = null;
    if (e.type !== 'pointerup' || !d || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 5) return; // перетаскивание — не выбор
    const hit = document.elementsFromPoint(e.clientX, e.clientY).find(el => el instanceof SVGElement && el.dataset.lane);
    setSelected(hit instanceof SVGElement ? hit.dataset.lane! : null);
  };

  const step = (factor: number) => setView(v => v && zoomAround(v, factor, size.w / 2, size.h / 2));
  const reset = () => setView({ cx: pageW / 2, cy: pageH / 2, zoom: 1 });
  const onKeyDown = (e: React.KeyboardEvent) => {
    const pan = 60 / (fit * (view?.zoom ?? 1));
    if (e.key === '+' || e.key === '=') step(1.4);
    else if (e.key === '-') step(1 / 1.4);
    else if (e.key === '0') reset();
    else if (e.key === 'Escape') setSelected(null);
    else if (e.key.startsWith('Arrow')) {
      e.preventDefault();
      const dx = e.key === 'ArrowLeft' ? -pan : e.key === 'ArrowRight' ? pan : 0;
      const dy = e.key === 'ArrowUp' ? -pan : e.key === 'ArrowDown' ? pan : 0;
      setView(v => v && constrain({ ...v, cx: v.cx + dx, cy: v.cy + dy }));
    }
  };

  return <section className="tram-map" aria-labelledby="tram-map-title">
    <h2 id="tram-map-title">Схема трамваев Москвы</h2>
    <p className="tram-map__note">Схема из предоставленного PDF; актуальность движения не проверяется. Линии перерисованы приложением; сейчас показаны только линии маршрутов (без остановок и подписей).</p>
    <div className="tram-map__stage">
      {problem === 'loading' && <div className="tram-map__state" role="status"><p>Загружаем схему…</p></div>}
      {problem === 'missing' && <div className="tram-map__state" role="status"><p>Ресурсы карты не подготовлены. Положите PDF в <code>data/tram-map/</code> и выполните <code>python scripts/map/extract_lanes.py</code>, затем перезагрузите страницу.</p></div>}
      {problem && problem !== 'loading' && problem !== 'missing' && <div className="tram-map__state" role="alert"><p>{problem}</p></div>}
      {map && <>
        <div ref={viewportRef} className="tram-map__viewport" tabIndex={0} role="application"
          aria-label="Схема трамваев. Стрелки — перемещение, плюс и минус — масштаб, 0 — показать целиком."
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onKeyDown={onKeyDown}>
          <svg viewBox={viewBox} preserveAspectRatio="xMidYMid meet" aria-hidden="true" style={{ background: "#4a4f80" }}>
            <rect x="0" y="0" width={pageW} height={pageH} fill="#eef0ee" />
            <g style={{ pointerEvents: 'none' }}>{(map.landmarks ?? []).map(g => <g key={g.id}>{shapeEls(g)}</g>)}</g>
            <g fill="none" strokeLinecap="round" strokeLinejoin="round">
              {map.lanes.map(l => <polyline key={l.id + 'c'} points={l.points.join(' ')} stroke="#fff" strokeWidth={5.2} />)}
              {map.lanes.map(l => <polyline key={l.id} points={l.points.join(' ')} stroke={l.color} strokeWidth={3}
                opacity={selected && selected !== l.id ? 0.25 : 1} />)}
              {map.lanes.map(l => <polyline key={l.id + 'h'} data-lane={l.id} points={l.points.join(' ')} stroke="transparent" strokeWidth={8} style={{ pointerEvents: 'stroke', cursor: 'pointer' }} />)}
            </g>
            <g style={{ pointerEvents: 'none' }}>
              {(map.labels ?? []).map(lb => <g key={lb.id} transform={`translate(${lb.x} ${lb.y}) rotate(${lb.angle})`}
                opacity={selected && !lb.lanes.includes(selected) ? 0.25 : 1}>
                {lb.lines.map((ln, i) => <text key={i} x={ln.dx} y={ln.dy} textAnchor="middle" dominantBaseline="central" textLength={ln.w} lengthAdjust="spacingAndGlyphs"
                  style={{ fontFamily: 'system-ui, sans-serif', fontSize: lb.fs, fontWeight: lb.bold ? 700 : 500, fill: '#231f20' }}>{ln.t}</text>)}
              </g>)}
              {(map.stops ?? []).map(st => <circle key={st.id} cx={st.x} cy={st.y} r={0.85} fill="#fff" opacity={selected && selected !== st.lane ? 0.25 : 1} />)}
            </g>
            <g style={{ pointerEvents: 'none' }}>{(map.metro ?? []).map(g => <g key={g.id}>{shapeEls(g)}</g>)}</g>
            <g fontFamily="system-ui, sans-serif" fontWeight="700" textAnchor="middle" style={{ pointerEvents: 'none' }}>
              {labels.map(lb => {
                const w = lb.text.length * 2.3 + 2.4;
                return <g key={lb.key} opacity={selected && selected !== lb.lane.id ? 0.25 : 1}>
                  <rect x={lb.x - w / 2} y={lb.y - 2.1} width={w} height={4.2} rx={1.2} fill={lb.lane.color} stroke="#fff" strokeWidth={0.5} />
                  <text x={lb.x} y={lb.y + 1.4} style={{ fontSize: 3.6, fill: inkFor(lb.lane.color) }}>{lb.text}</text>
                </g>;
              })}
            </g>
          </svg>
        </div>
        <div className="tram-map__controls">
          <button type="button" className="tram-map__btn" aria-label="Увеличить" onClick={() => step(1.5)}>+</button>
          <button type="button" className="tram-map__btn" aria-label="Уменьшить" onClick={() => step(1 / 1.5)}>−</button>
          <button type="button" className="tram-map__btn tram-map__btn--fit" aria-label="Показать схему целиком" onClick={reset}>⤢</button>
        </div>
        <div className="tram-map__hint">Колесо — масштаб, перетаскивание — перемещение</div>
      </>}
    </div>
    {legend.length > 0 && <div className="tram-map__legend" aria-label="Цвета линий и номера трамваев">
      <h3>Какой цвет — какой трамвай</h3>
      <ul>{legend.map(g => <li key={g.color}>
        <span className="tram-map__swatch" style={{ background: g.color }} aria-hidden="true" />
        <span className="tram-map__nums">{g.nums.map(n => <span key={n} className="tram-map__chip" style={{ background: g.color, color: inkFor(g.color) }}>{n}</span>)}</span>
      </li>)}</ul>
      {map?.lanes.some(l => l.inferred) && <p className="tram-map__note">Часть линий (отмечена в данных как «выведено») получила номер по исключению, а не по надписи на схеме; требуется проверка.</p>}
    </div>}
  </section>;
}
