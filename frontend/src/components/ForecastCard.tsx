import { useState } from "react";
import { format, useForecastData } from "../useForecast";
import { intervalLabel } from "../display";
import { ForecastLineChart, ForecastTable } from "./ForecastData";
import { DataDetails } from "./DataDetails";
import { TimelinePanel } from "./TimelinePanel";
import { Button, Icon } from "./ui";
import { YearView, RouteOverview, NeighborValues } from "./DispatchTools";
import "./ForecastCard.css";

export function ForecastCard({ onClose }: { onClose: () => void }) {
  const f = useForecastData();
  const { current: result, points, busy, error } = f;
  const [chartMode, setChartMode] = useState<"chart" | "table">("chart");
  const point = points[f.selected];
  const daily = result?.filters.resolution === "day";
  const baseline = f.caps?.routes.find(r => r.route_id === f.route)?.method === 'baseline';
  const onSelect = (i: number) => { f.setPlaying(false); f.setSelected(i); };
  if (f.horizon === 'year') return <YearView />;
  if (f.overview) return <RouteOverview />;
  return <section className="forecast-card" aria-label="Карточка прогноза" tabIndex={-1}
    onKeyDown={e => { if (e.key === 'Escape') onClose(); }}>
    <div className="forecast-card__summary">
      <h1 className="forecast-card__interval">{point ? `${intervalLabel(point.start, point.end, !!daily)} · МСК` : `Маршрут ${f.route || 'не выбран'}`}</h1>
      <div className="forecast-card__value">
        <strong data-testid={point ? "map-demand" : undefined} data-raw-value={point?.value ?? ''}>{point ? format(point.value) : '—'}</strong>
        <span>успешных посадок</span>
      </div>
      {busy && <p className="forecast-message" role="status">Загружаем прогноз…</p>}
      {f.emptyReason && <p className="forecast-message" role="status">{f.emptyReason}</p>}
      {error && <p className="forecast-message forecast-message--error" role="alert">{error}</p>}
      {baseline && <p className="forecast-message">Нет истории обучения: модель возвращает 0. Движение по маршруту возможно.</p>}
      {result?.total_scope === 'available_only' && <p className="forecast-message" role="status">Есть пропуски · покрытие {format(result.coverage * 100)}%</p>}
      {result?.total_scope === 'no_data' && <p className="forecast-message" role="status">Нет данных за период. Выберите другую дату.</p>}
    </div>
    <div className="forecast-card__visual">
      <div className="forecast-card__view-toggle" role="group" aria-label="Вид данных">
        <Button variant="ghost" aria-pressed={chartMode === 'chart'} onClick={() => setChartMode('chart')}>График</Button>
        <Button variant="ghost" aria-pressed={chartMode === 'table'} onClick={() => setChartMode('table')}>Таблица</Button>
      </div>
      {!!points.length ? chartMode === 'chart'
        ? <ForecastLineChart points={points} unit="успешные посадки" selectedIndex={f.selected} onSelectIndex={onSelect} />
        : <ForecastTable points={points} unit="успешные посадки" selectedIndex={f.selected} onSelectIndex={onSelect} />
        : <div className="chart-placeholder" aria-hidden="true"><span/><span/><span/></div>}
      <TimelinePanel />
    </div>
    <NeighborValues />
    <div className="forecast-card__tools">
    <details className="service-check">
      <summary>Проверить выпуск</summary>
      <p>Маршрут {f.route}{point ? ` · ${intervalLabel(point.start, point.end, !!daily)} МСК` : ''}</p>
      <dl><div><dt>Рейсы по факту</dt><dd>Нет данных</dd></div><div><dt>Интервалы движения</dt><dd>Нет данных</dd></div><div><dt>Вместимость и высадки</dt><dd>Нет данных</dd></div></dl>
      <p>Сверьте с расписанием и отчётом о рейсах перед изменением выпуска.</p>
    </details>
    </div>
    {result && <div className="forecast-card__period-total">
      <span>{result.total_scope === 'available_only' ? 'По доступным данным' : f.horizon === 'day' ? 'За день' : 'За период'}</span>
      <strong data-testid="total" data-raw-value={f.displayTotal ?? ''}>{format(f.displayTotal)}</strong>
    </div>}
    <div className="forecast-card__actions">
      <Button variant="primary" disabled={!result || busy || !!error || f.exporting} onClick={() => void f.download()} aria-label="Скачать CSV">
        {f.exporting ? 'Скачиваем…' : 'CSV · прогноз'}
      </Button>
      {<Button variant="ghost" onClick={f.retry} disabled={busy || f.exporting || !!f.emptyReason}
        aria-label={f.errorStatus === 410 ? 'Обновить доступные данные' : error ? 'Повторить запрос' : 'Обновить прогноз'}>{error ? 'Повторить' : '↻'}</Button>}
    </div>
    <div className="forecast-card__footer">
      <details className="forecast-card__details"><summary>О данных</summary><DataDetails /></details>
      <button className="card-close" onClick={onClose} aria-label="Свернуть карточку"><Icon name="close" /></button>
    </div>
  </section>;
}
