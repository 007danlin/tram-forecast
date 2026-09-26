import "./ForecastData.css";
import type { Row } from "../handoff";
import { format, statusLabels } from "../useForecast";
import { smoothChartPath } from "../chartPath";

export type ForecastPoint = Row & { timestamp: string };

function timeLabel(ts: string) {
  return ts.slice(5, 16).replace("T", " ");
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
  const scenario = points.some(p => p.base_value !== undefined);
  const max = Math.max(1, ...points.flatMap((p) => [p.value ?? 0, p.base_value ?? 0]));
  const x = (i: number) => 40 + (i * 520) / Math.max(1, points.length - 1);
  const y = (v: number) => 190 - (v / max) * 160;
  const line = smoothChartPath(points.map((p, i) =>
    p.value === null ? null : { x: x(i), y: y(p.value) },
  ));
  return (
    <div className="forecast-chart">
      {scenario && <p>Сплошная линия — сценарий; пунктир — база. Интервал сценария не оценён.</p>}
      <svg
        viewBox="0 0 600 230"
        role="img"
        aria-label={`Прогноз успешных посадок; пропуски показаны разрывами, единица «${unit}». Точные значения — в таблице.`}
      >
        <line
          x1="40"
          y1="190"
          x2="560"
          y2="190"
          stroke="var(--border-subtle)"
        />
        <text x="12" y="195">
          0
        </text>
        <text x="8" y="30">
          {format(max)}
        </text>
        {scenario && <path d={smoothChartPath(points.map((p, i) => p.base_value == null ? null : {x: x(i), y: y(p.base_value)}))}
          fill="none" stroke="var(--text-secondary)" strokeWidth="2" strokeDasharray="5 4" />}
        <path
          d={line}
          fill="none"
          stroke="var(--chart-line)"
          strokeWidth="3"
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
          <text x="40" y="218">
            {timeLabel(points[0].timestamp)}
          </text>
        )}
        {points.length > 1 && (
          <text x="560" y="218" textAnchor="end">
            {timeLabel(points[points.length - 1].timestamp)}
          </text>
        )}
      </svg>
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
  return (
    <div
      className="forecast-table-wrap"
      tabIndex={0}
      role="region"
      aria-label="Таблица прогноза, прокручивается горизонтально"
    >
      <table className="forecast-table">
        <caption>
          Время МСК (+03:00). Раскройте число для исходной точности.
        </caption>
        <thead>
          <tr>
            <th scope="col">Время (ISO 8601)</th>
            <th scope="col">Значение, {unit}</th>
            {scenario && <><th scope="col">База</th><th scope="col">Разница</th></>}
            <th scope="col">Покрытие</th>
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
                  <time dateTime={p.timestamp}>{p.timestamp}</time>
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
              <td>
                {p.available_hours}/{p.expected_hours} ·{" "}
                {statusLabels[p.status]}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
