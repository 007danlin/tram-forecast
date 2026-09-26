import { ForecastLineChart, ForecastTable } from "./ForecastData";
import { useForecastData } from "../useForecast";
import { Button } from "./ui";
import { OverviewButton, RouteOverview, ScenarioPanel, YearView, DemandIndicator } from "./DispatchTools";
import "./AnalyticsView.css";
export function AnalyticsView() {
  const f = useForecastData();
  if (f.horizon === 'year') return <YearView />;
  if (f.overview) return <RouteOverview />;
  const onSelect = (i: number) => {
    f.setPlaying(false);
    f.setSelected(i);
  };
  return (
    <section className="analytics-view" aria-labelledby="analytics-title">
      <div className="analytics-heading">
        <div>
          <p className="eyebrow">Тот же прогноз · расширенный вид</p>
          <h1 id="analytics-title">Аналитика маршрута {f.route}</h1>
        </div>
        <Button
          variant="primary"
          disabled={!f.current || f.busy || !!f.error || f.exporting}
          onClick={() => void f.download()}
        >
          Скачать CSV
        </Button>
      </div>
      <p className="analytics-view__notice">
        Исторический прогноз · МСК. Успешные посадки не равны заполненности
        вагона.
      </p>
      <OverviewButton />
      <ScenarioPanel />
      <DemandIndicator />
      {f.busy && <p role="status">Загружаем прогноз…</p>}
      {f.emptyReason && <p role="status">{f.emptyReason}</p>}
      {f.error && (
        <div className="forecast-message--error">
          <p role="alert">{f.error}</p>
          <Button onClick={f.retry}>Повторить запрос</Button>
        </div>
      )}
      {!!f.points.length && (
        <>
          <div className="analytics-view__panel">
            <h2>Динамика успешных посадок</h2>
            <ForecastLineChart
              points={f.points}
              unit="успешные посадки"
              selectedIndex={f.selected}
              onSelectIndex={onSelect}
            />
          </div>
          <div className="analytics-view__panel">
            <h2>Точные значения</h2>
            <ForecastTable
              points={f.points}
              unit="успешные посадки"
              selectedIndex={f.selected}
              onSelectIndex={onSelect}
            />
          </div>
        </>
      )}
    </section>
  );
}
