import { format, useForecastData } from '../useForecast';
import { intervalLabel, dateLabel } from '../display';

export function ForecastNotices() {
  const f = useForecastData(), point = f.points[f.selected];
  const baseline = f.caps?.routes.find(r => r.route_id === f.route)?.method === 'baseline';
  return <div className="forecast-notices">
    {f.scenarioActive && <p className="scenario-active">{point ? `Без поправок ${format(point.base_value ?? null)} · разница ${format(point.delta ?? null)}` : 'Применяем поправки…'}</p>}
    {f.busy && <p role="status">Загружаем прогноз…</p>}
    {f.emptyReason && <p role="status">{f.emptyReason}</p>}
    {f.error && <p className="forecast-message--error" role="alert">{f.error}</p>}
    {baseline && <p>Нет истории обучения: модель возвращает 0. Движение по маршруту возможно.</p>}
    {f.current?.total_scope === 'available_only' && <p role="status">Есть пропуски · покрытие {format(f.current.coverage * 100)}%</p>}
    {f.current?.total_scope === 'no_data' && <p role="status">Нет данных за период. Выберите другую дату.</p>}
  </div>;
}

export function ForecastMetrics({includeSelected = false}: {includeSelected?: boolean}) {
  const f = useForecastData(), point = f.points[f.selected];
  const daily = f.current?.filters.resolution === 'day';
  const peak = f.points.reduce<(typeof f.points)[number] | null>((best, p) => p.value !== null && (!best || p.value > best.value!) ? p : best, null);
  return <dl className={`forecast-metrics${includeSelected ? ' forecast-metrics--three' : ''}`}>
    {includeSelected && <div><dt>{point ? intervalLabel(point.start, point.end, !!daily) : 'Выбранный интервал'} · МСК</dt><dd data-testid="analytics-demand" data-raw-value={point?.value ?? ''}>{format(point?.value ?? null)}<span className="forecast-metrics__unit">посадок</span></dd></div>}
    <div><dt><span className="forecast-metrics__full-label">{f.current?.total_scope === 'available_only' ? 'По доступным данным' : f.horizon === 'day' ? (includeSelected ? 'За день' : 'Посадок за день') : (includeSelected ? 'За период' : 'Посадок за период')}</span><span className="forecast-metrics__short-label">{f.current?.total_scope === 'available_only' ? 'Доступно' : f.horizon === 'day' ? 'За день' : 'За период'}</span></dt><dd data-testid={f.current ? "total" : undefined} data-raw-value={f.displayTotal ?? ''}>{format(f.displayTotal)}{includeSelected && <span className="forecast-metrics__unit">посадок</span>}</dd></div>
    <div><dt><span className="forecast-metrics__full-label">{daily ? 'Пиковый день' : 'Пиковый час'}</span><span className="forecast-metrics__short-label">пик{daily ? '' : ' в'}</span></dt><dd>{peak ? daily ? dateLabel(peak.start, true).replace(/ \d{4} г\./, '') : peak.start.slice(11,16) : '—'}</dd></div>
  </dl>;
}
