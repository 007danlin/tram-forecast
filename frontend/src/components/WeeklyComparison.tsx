import { format } from "../useForecast";
import type { WeeklyComparison } from "../useWeeklyComparison";
import "./WeeklyComparison.css";

export function WeeklyComparisonCard({ currentValue, averageValue, history }: WeeklyComparison) {
  if (averageValue <= 0) return null;
  const deviation = ((currentValue - averageValue) / averageValue) * 100;
  const tone = Math.abs(deviation) <= 3 ? "neutral" : deviation > 0 ? "above" : "below";
  const sign = deviation > 0 ? "+" : deviation < 0 ? "−" : "";
  const max = Math.max(1, ...history);
  const spark = history
    .map((v, i) => `${(i / Math.max(1, history.length - 1)) * 100},${26 - (v / max) * 22}`)
    .join(" ");
  return (
    <div className="weekly-comparison" data-tone={tone}>
      <div className="weekly-comparison__text">
        <p className="weekly-comparison__title">Относительно среднего за неделю</p>
        <p className="weekly-comparison__value">
          {tone !== "neutral" && (
            <span className="weekly-comparison__arrow" aria-hidden="true">{deviation > 0 ? "▲" : "▼"}</span>
          )}
          {sign}{Math.abs(deviation).toFixed(0)}%
        </p>
        <p className="weekly-comparison__caption">{format(currentValue)} сейчас · {format(averageValue)} в среднем</p>
      </div>
      {history.length > 1 && (
        <svg className="weekly-comparison__spark" viewBox="0 0 100 26" preserveAspectRatio="none" aria-hidden="true">
          <polyline points={spark} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </div>
  );
}
