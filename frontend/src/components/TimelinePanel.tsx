import './TimelinePanel.css';
import type { ForecastPoint } from './ForecastData';

export function TimelinePanel({
  points, selectedIndex, onSelectIndex, playing, onTogglePlay,
}: {
  points: ForecastPoint[];
  selectedIndex: number | null;
  onSelectIndex: (i: number) => void;
  playing: boolean;
  onTogglePlay: () => void;
}) {
  const hasData = points.length > 0;
  const index = selectedIndex ?? 0;
  const current = points[index];

  return (
    <div className="timeline-panel">
      <button
        type="button"
        className="timeline-panel__play"
        onClick={onTogglePlay}
        disabled={!hasData}
        aria-label={playing ? 'Пауза' : 'Воспроизвести'}
        aria-pressed={playing}
      >
        {playing ? '⏸' : '▶'}
      </button>
      <div className="timeline-panel__mid">
        <input
          type="range"
          className="timeline-panel__slider"
          min={0}
          max={Math.max(0, points.length - 1)}
          value={index}
          disabled={!hasData}
          onChange={e => onSelectIndex(Number(e.target.value))}
          aria-label="Точка временного ряда"
          aria-valuetext={current ? `${current.timestamp.slice(0, 10)} ${current.timestamp.slice(11, 16)}, ${current.value}` : undefined}
        />
        <span className="timeline-panel__label">
          {current
            ? <>Дата <strong>{current.timestamp.slice(0, 10)}</strong>, время <strong>{current.timestamp.slice(11, 16)}</strong> ({current.timestamp.slice(19)}) — {current.value}</>
            : 'Нет доступных точек'}
        </span>
      </div>
      <div className="timeline-panel__step">
        <label htmlFor="timeline-step">Шаг</label>
        <select id="timeline-step" defaultValue="15m">
          <option value="15m">15 мин</option>
          <option value="1h" disabled title="Требуются подтверждённые часовые данные">1 ч</option>
        </select>
      </div>
    </div>
  );
}
