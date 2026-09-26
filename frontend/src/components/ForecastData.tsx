import "./ForecastData.css";
import { useLayoutEffect, useRef, useState } from "react";
import type { Row } from "../handoff";
import { format, statusLabels } from "../useForecast";
import { smoothChartPath } from "../chartPath";

export type ForecastPoint = Row & { timestamp: string };

function timeLabel(ts: string, daily: boolean) {
  return daily ? new Date(ts).toLocaleDateString("ru-RU", {timeZone: "Europe/Moscow", day: "numeric", month: "short"}) : ts.slice(11, 16);
}

export function ForecastLineChart({
  points,
  unit,
  selectedIndex,
  onSelectIndex,
}: {
  points: ForecastPoint[];
  unit: string;
  selectedIndex: number | null;
  onSelectIndex: (i: number) => void;
}) {
  const plot = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 600, height: 230 });
  useLayoutEffect(() => {
    const element = plot.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize(previous =>
        previous.width === width && previous.height === height ? previous : { width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const scenario = points.some(p => p.base_value !== undefined);
  const max = Math.max(1, ...points.flatMap((p) => [p.value ?? 0, p.base_value ?? 0]));
  const left = Math.max(42, format(max).length * 6.5 + 12);
  const right = size.width - 12;
  const bottom = size.height - 26;
  const x = (i: number) => left + (i * (right - left)) / Math.max(1, points.length - 1);
  const y = (v: number) => bottom - (v / max) * Math.max(1, bottom - 16);
  const line = smoothChartPath(points.map((p, i) =>
    p.value === null ? null : { x: x(i), y: y(p.value) },
  ));
  return (
    <div className="forecast-chart">
      {scenario && <div className="forecast-chart__legend"><span>━ С поправками</span><span>┄ Без поправок</span></div>}
      <div className="forecast-chart__plot" ref={plot}>
      <svg
        viewBox={`0 0 ${size.width} ${size.height}`}
        role="img"
        aria-label={`Прогноз успешных посадок; пропуски показаны разрывами, единица «${unit}». Точные значения — в таблице.`}
      >
        <line
          x1={left}
          y1={bottom}
          x2={right}
          y2={bottom}
          stroke="var(--border-subtle)"
        />
        <text x={left - 10} y={bottom + 4} textAnchor="end">
          0
        </text>
        <text x={left - 10} y="20" textAnchor="end">
          {format(max)}
        </text>
        {scenario && <path d={smoothChartPath(points.map((p, i) => p.base_value == null ? null : {x: x(i), y: y(p.base_value)}))}
          fill="none" stroke="var(--text-secondary)" strokeWidth="2" strokeDasharray="5 4" />}
        <path
          d={line}
          fill="none"
          stroke="var(--chart-line)"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {points.map(
          (p, i) =>
            p.value !== null && (
              <circle
                key={`${p.timestamp}-${i}`}
                className={`forecast-chart__point${selectedIndex === i ? " forecast-chart__point--selected" : ""}`}
                cx={x(i)}
                cy={y(p.value)}
                r={selectedIndex === i ? 5 : 2}
                fill={selectedIndex === i ? undefined : "var(--chart-line)"}
                aria-hidden="true"
                onClick={() => onSelectIndex(i)}
              >
                <title>{`${p.timestamp} — ${p.value} ${unit}`}</title>
              </circle>
            ),
        )}
        {points[0] && (
          <text x={left} y={size.height - 6}>
            {timeLabel(points[0].timestamp, points[0].expected_hours > 1)}
          </text>
        )}
        {points.length > 1 && (
          <text x={right} y={size.height - 6} textAnchor="end">
            {timeLabel(points[points.length - 1].timestamp, points[0].expected_hours > 1)}
          </text>
        )}
      </svg>
      </div>
    </div>
  );
}

export function ForecastTable({
  points,
  unit,
  selectedIndex,
  onSelectIndex,
}: {
  points: ForecastPoint[];
  unit: string;
  selectedIndex: number | null;
  onSelectIndex: (i: number) => void;
}) {
  const scenario = points.some(p => p.base_value !== undefined);
  const partial = points.some(p => p.coverage < 1);
  const daily = points.some(p => p.expected_hours > 1);
  return (
    <div
      className="forecast-table-wrap"
      tabIndex={0}
      role="region"
      aria-label="Таблица прогноза, прокручивается горизонтально"
    >
      <table className="forecast-table">
        <caption>
          Значения — посадки. Время МСК (+03:00). Раскройте число для исходной точности.
        </caption>
        <thead>
          <tr>
            <th scope="col">Время · МСК</th>
            <th scope="col" title={unit}>Посадки</th>
            {scenario && <><th scope="col">Без поправок</th><th scope="col">Разница</th></>}
            {partial && <th scope="col">Покрытие</th>}
          </tr>
        </thead>
        <tbody>
          {points.map((p, i) => (
            <tr
              key={i}
              data-start={p.timestamp}
              data-route={p.route_id}
              aria-selected={selectedIndex === i}
              onClick={() => onSelectIndex(i)}
            >
              <td>
                <button
                  className="table-select"
                  aria-label={`Выбрать ${p.timestamp}`}
                  onClick={() => onSelectIndex(i)}
                >
                  <time dateTime={p.timestamp} title={p.timestamp}>{daily ? new Date(p.timestamp).toLocaleDateString("ru-RU", {timeZone: "Europe/Moscow", day: "numeric", month: "short"}) : p.timestamp.slice(11,16)}</time>
                </button>
              </td>
              <td data-raw-value={p.value ?? ""}>
                {p.value === null ? (
                  "Нет данных"
                ) : (
                  <details>
                    <summary>{format(p.value)}</summary>
                    <span>{String(p.value)}</span>
                  </details>
                )}
              </td>
              {scenario && <><td>{format(p.base_value ?? null)}</td><td>{format(p.delta ?? null)}</td></>}
              {partial && <td>
                {p.available_hours}/{p.expected_hours} ·{" "}
                {statusLabels[p.status]}
              </td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
