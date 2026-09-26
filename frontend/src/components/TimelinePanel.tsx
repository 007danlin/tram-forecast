import type { CSSProperties } from "react";
import "./TimelinePanel.css";
import { format, useForecastData } from "../useForecast";
import { intervalLabel } from "../display";
import { Button, Icon } from "./ui";
export function TimelinePanel() {
  const f = useForecastData(),
    current = f.points[f.selected];
  const hasData = f.points.length > 0 && !f.busy;
  const label = current
    ? intervalLabel(
        current.start,
        current.end,
        f.current?.filters.resolution === "day",
      )
    : "";
  const peak = f.points.reduce((best, p, i) => p.value !== null && (best < 0 || p.value > f.points[best].value!) ? i : best, -1);
  return (
    <section className="timeline-panel" aria-label="Временная панель">
      <Button
        variant="ghost"
        className="timeline-panel__play icon-button"
        disabled={!hasData}
        aria-label={f.playing ? "Пауза" : "Воспроизвести"}
        aria-pressed={f.playing}
        onClick={() => {
          if (f.selected >= f.points.length - 1) f.setSelected(0);
          f.setPlaying((v) => !v);
        }}
      >
        <Icon name={f.playing ? "pause" : "play"} />
      </Button>
      <div className="timeline-panel__mid">
        <span className="timeline-panel__time">{label || "Нет данных"}</span>
        <input
          style={
            {
              "--progress": `${(f.selected / Math.max(1, f.points.length - 1)) * 100}%`,
            } as CSSProperties
          }
          type="range"
          min={0}
          max={Math.max(0, f.points.length - 1)}
          value={f.selected}
          disabled={!hasData}
          aria-label="Точка временного ряда"
          aria-valuetext={
            current
              ? `${label}, МСК, ${format(current.value)} успешных посадок`
              : "Нет данных"
          }
          onChange={(e) => {
            f.setPlaying(false);
            f.setSelected(Number(e.target.value));
          }}
        />
      </div>
      <Button variant="ghost" disabled={!hasData || peak < 0} onClick={() => { f.setPlaying(false); f.setSelected(peak); }}>Час пик</Button>
    </section>
  );
}
