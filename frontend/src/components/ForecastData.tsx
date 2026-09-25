import './ForecastData.css';

export type ForecastPoint = { timestamp: string; value: number };

function timeLabel(ts: string) {
  return ts.slice(11, 16);
}

export function ForecastLineChart({
  points, unit, selectedIndex, onSelectIndex,
}: {
  points: ForecastPoint[];
  unit: string;
  selectedIndex: number | null;
  onSelectIndex: (i: number) => void;
}) {
  const max = Math.max(1, ...points.map(p => p.value));
  const x = (i: number) => 40 + i * 520 / Math.max(1, points.length - 1);
  const y = (v: number) => 190 - (v / max) * 160;
  const line = points.map((p, i) => `${x(i)},${y(p.value)}`).join(' ');
  return (
    <div className="forecast-chart">
      <svg viewBox="0 0 600 230" role="img" aria-label={`График тестового ряда, единица «${unit}». Точные значения — в таблице.`}>
        <line x1="40" y1="190" x2="560" y2="190" stroke="#adb8c8" />
        <text x="12" y="195">0</text>
        <text x="8" y="30">{max}</text>
        <polyline points={line} fill="none" stroke="#2456ca" strokeWidth="3" />
        {points.map((p, i) => (
          <circle
            key={`${p.timestamp}-${i}`}
            className={`forecast-chart__point${selectedIndex === i ? ' forecast-chart__point--selected' : ''}`}
            cx={x(i)} cy={y(p.value)} r={selectedIndex === i ? 5.5 : 4}
            fill={selectedIndex === i ? undefined : '#2456ca'}
            aria-hidden="true"
            onClick={() => onSelectIndex(i)}
          >
            <title>{`${p.timestamp} — ${p.value} ${unit}`}</title>
          </circle>
        ))}
        {points[0] && <text x="40" y="218">{timeLabel(points[0].timestamp)}</text>}
        {points.length > 1 && <text x="560" y="218" textAnchor="end">{timeLabel(points[points.length - 1].timestamp)}</text>}
      </svg>
    </div>
  );
}

export function ForecastTable({
  points, unit, selectedIndex, onSelectIndex,
}: {
  points: ForecastPoint[];
  unit: string;
  selectedIndex: number | null;
  onSelectIndex: (i: number) => void;
}) {
  return (
    <div className="forecast-table-wrap">
      <table className="forecast-table">
        <caption>Время с исходным часовым смещением, без перевода в часовой пояс браузера</caption>
        <thead><tr><th scope="col">Время (ISO 8601)</th><th scope="col">Значение, {unit}</th></tr></thead>
        <tbody>
          {points.map((p, i) => (
            <tr key={i} aria-selected={selectedIndex === i} onClick={() => onSelectIndex(i)}>
              <td><time dateTime={p.timestamp}>{p.timestamp}</time></td>
              <td>{p.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
