import './AnalyticsView.css';
import { ForecastLineChart, ForecastTable, type ForecastPoint } from './ForecastData';

export function AnalyticsView({
  points, unit, loading, error, onRetry, selectedIndex, onSelectIndex,
}: {
  points: ForecastPoint[];
  unit: string;
  loading: boolean;
  error: string;
  onRetry: () => void;
  selectedIndex: number | null;
  onSelectIndex: (i: number) => void;
}) {
  return (
    <div className="analytics-view">
      <div className="analytics-view__inner">
        <p className="analytics-view__notice">Исторический ML-прогноз по выбранному маршруту и периоду. Тот же результат, что в карточке; успешные посадки не равны заполненности вагона.</p>
        <section className="analytics-view__panel">
          <h2>Прогноз · {unit}</h2>
          <p>Расширенный вид того же временного ряда: график и полная таблица значений.</p>
          {loading && <p>Загружаем прогноз…</p>}
          {error && <><p role="alert" style={{ color: '#ac2121' }}>{error}</p><button type="button" className="analytics-view__retry" onClick={onRetry}>Повторить запрос</button></>}
          {!loading && !error && points.length > 0 && (
            <ForecastLineChart points={points} unit={unit} selectedIndex={selectedIndex} onSelectIndex={onSelectIndex} />
          )}
        </section>
        {!loading && !error && points.length > 0 && (
          <section className="analytics-view__panel">
            <h2>Таблица значений</h2>
            <ForecastTable points={points} unit={unit} selectedIndex={selectedIndex} onSelectIndex={onSelectIndex} />
          </section>
        )}
      </div>
    </div>
  );
}
