import { useState } from 'react';
import { OVERVIEW } from '../handoff';
import { format, statusLabels, useForecastData } from '../useForecast';
import { dateLabel, intervalLabel } from '../display';
import { Button } from './ui';
import './DispatchTools.css';

export function ScenarioPanel() {
  const f = useForecastData();
  if (f.horizon === 'year' || !f.caps?.scenario_supported) return null;
  return <details className="scenario-panel"><summary>Сценарий · {f.layer === 'base' ? 'база' : 'ручные поправки'}</summary>
    <p>Допущение диспетчера на весь период. Это не переобучение и не доказанный эффект погоды или события.</p>
    <div className="dispatch-controls" role="group" aria-label="Слой прогноза">
      <Button aria-pressed={f.layer === 'base'} onClick={() => f.changeLayer('base')}>База</Button>
      <Button aria-pressed={f.layer === 'scenario'} onClick={() => f.changeLayer('scenario')}>Сценарий</Button>
    </div>
    {(['weather', 'event'] as const).map(key => <label className="coefficient" key={key}>
      <span>{key === 'weather' ? 'Погода' : 'Событие'} · {f.coefficients[key].toFixed(2)}</span>
      <input type="range" aria-label={key === 'weather' ? 'Коэффициент погоды' : 'Коэффициент события'}
        min="0.5" max="1.5" step="0.05" value={f.coefficients[key]}
        onChange={e => f.changeCoefficients({...f.coefficients, [key]: Number(e.target.value)})}/>
    </label>)}
    <Button onClick={f.resetScenario}>Сбросить сценарий</Button>
    {f.current && <dl className="scenario-comparison" data-testid="scenario-comparison">
      <div><dt>База</dt><dd data-base-total={f.current.total ?? ''}>{format(f.current.total)}</dd></div>
      {f.scenario && <><div><dt>Сценарий</dt><dd data-scenario-total={f.scenario.total ?? ''}>{format(f.scenario.total)}</dd></div>
      <div><dt>Разница</dt><dd>{format(f.scenario.delta_total)}</dd></div></>}
    </dl>}
    <p>Интервал сценария не оценён. Базовые интервалы относятся только к базе. CSV выгружает выбранный слой{f.overview ? ' для всего обзора' : ' для выбранного маршрута'}.</p>
  </details>;
}

export function YearView() {
  const f = useForecastData(), meta = f.caps?.year;
  const start = f.day ? `${f.day.slice(0, 7)}-01` : '';
  const end = start ? `${Number(start.slice(0,4)) + 1}${start.slice(4)}` : '';
  return <section className="dispatch-panel" aria-label="Качественный год">
    <h1>Год · качественно</h1>
    <p>{f.overview ? 'Обзор маршрутов' : f.route ? `Маршрут ${f.route}` : 'Маршрут не выбран'}</p>
    <p data-testid="year-period">{dateLabel(start, true)} — {dateLabel(end, true)} (конец не включён), МСК</p>
    {f.routeUnavailable && <p role="status">Маршрут только на схеме; обучаемого прогноза нет. Ниже общие допущения.</p>}
    {f.caps?.routes.find(r => r.route_id === f.route)?.method === 'baseline' && <p>№ 5 — нулевой baseline, нет успешной истории обучения. Это не означает отсутствия движения.</p>}
    {meta?.qualitative_available ? <>
      <p>Конец истории: {dateLabel(meta.history_end, true)}. {meta.reason}</p>
      {meta.scenarios.map(s => <article key={s.name}><h2>{s.title}</h2><p>{s.assumption}</p><p>{s.change}</p><p>{s.needed}</p></article>)}
      <p className="dispatch-muted">Описание {meta.version}, источник: {meta.source}.</p>
    </> : <p>Качественное описание недоступно в этой версии сервиса.</p>}
    <Button disabled aria-label="Скачать CSV">Численный CSV недоступен</Button>
    <p>Численный год не поддержан; годовая сумма и интервал не оценены. Ручные коэффициенты к этому описанию не применяются.</p>
  </section>;
}

export function RouteOverview() {
  const f = useForecastData();
  const [sort, setSort] = useState<'total' | 'selected'>('total');
  const times = [...new Set(f.rows.map(r => r.start))];
  const time = times[f.selected];
  const summaries = (f.caps?.routes ?? []).map(route => {
    const rows = f.rows.filter(r => r.route_id === route.route_id);
    const valid = rows.filter(r => r.value !== null);
    const total = valid.length ? valid.reduce((s, r) => s + r.value!, 0) : null;
    const expected = rows.reduce((s, r) => s + r.expected_hours, 0);
    const available = rows.reduce((s, r) => s + r.available_hours, 0);
    const coverage = expected ? available / expected : 0;
    const peak = valid.reduce<(typeof rows)[number] | null>((p, r) => !p || r.value! > p.value! ? r : p, null);
    const selected = rows.find(r => r.start === time);
    const category = route.method === 'baseline' ? 2 : coverage < 1 ? 1 : 0;
    const rank = sort === 'total' ? total : selected?.value;
    return {route, total, coverage, peak, selected, category, rank};
  }).sort((a,b) => a.category - b.category || (a.category === 0 ? (b.rank ?? -1) - (a.rank ?? -1) : 0)
    || a.route.route_id.localeCompare(b.route.route_id, 'ru', {numeric: true}));
  return <section className="dispatch-panel route-overview" aria-label="Обзор маршрутов">
    <h1>Обзор маршрутов</h1>
    <p>Спрос: успешные посадки, не заполненность. Слой: {f.layer === 'base' ? 'База' : `Сценарий · погода ${f.coefficients.weather}, событие ${f.coefficients.event}`}.</p>
    {f.current && <p>{dateLabel(f.current.filters.start, true)} — {dateLabel(f.current.filters.end, true)} (конец не включён), МСК.</p>}
    <ScenarioPanel/>
    {f.busy && <p role="status">Загружаем обзор…</p>}
    {f.error && <><p role="alert">{f.error}</p><Button onClick={f.retry}>Повторить запрос</Button></>}
    <label>Сортировать по спросу <select aria-label="Сортировка обзора" value={sort} onChange={e => setSort(e.target.value as 'total' | 'selected')}>
      <option value="total">За период</option><option value="selected">В выбранный интервал</option></select></label>
    <label>Интервал МСК <select aria-label="Интервал обзора" value={f.selected} disabled={!times.length} onChange={e => f.setSelected(Number(e.target.value))}>
      {times.map((t,i) => <option key={t} value={i}>{t.slice(0,16).replace('T',' ')}</option>)}</select></label>
    {f.current && <div className="forecast-table-wrap" role="region" tabIndex={0} aria-label="Сводная таблица спроса">
      <table className="forecast-table"><caption>Полный модельный спрос ранжируется отдельно от неполных данных и baseline.</caption>
        <thead><tr><th>Маршрут</th><th>Сумма</th><th>Выбранный интервал</th><th>Первый максимум</th><th>Покрытие / статус</th></tr></thead>
        <tbody>{summaries.map(s => <tr key={s.route.route_id} data-overview-route={s.route.route_id}>
          <td><Button onClick={() => f.changeRoute(s.route.route_id)}>№ {s.route.route_id}</Button></td>
          <td data-overview-total={s.total ?? ''}>{format(s.total)}</td><td data-overview-selected={s.selected?.value ?? ''}>{format(s.selected?.value ?? null)}</td>
          <td>{s.peak ? intervalLabel(s.peak.start, s.peak.end, f.current?.filters.resolution === 'day') : 'Нет данных'}</td>
          <td>{format(s.coverage * 100)}% · {s.route.method === 'baseline' ? 'Нулевой baseline' : s.coverage === 1 ? 'Полное покрытие' : s.coverage ? 'Неполные данные' : 'Нет данных'}</td>
        </tr>)}</tbody></table></div>}
    <p>№ 5 — технический baseline; отсутствие успешной истории не означает отсутствие движения. Пропуски не считаются нулевым спросом.</p>
    <Button disabled={!f.current || f.busy || !!f.error || f.exporting} onClick={() => void f.download()} aria-label="Скачать CSV">CSV всего обзора</Button>
    <p>Следующее действие: выберите маршрут, сравните соседние интервалы, проверьте фактический выпуск и расписание.</p>
  </section>;
}

export function DemandIndicator() {
  const f = useForecastData(), point = f.points[f.selected];
  const previous = f.points[f.selected - 1], next = f.points[f.selected + 1];
  if (!point || f.horizon === 'year') return null;
  return <section className="dispatch-panel demand-indicator" aria-label="Спрос выбранного маршрута">
    <h2>Маршрут {f.route} · {f.layer === 'base' ? 'База' : `Сценарий × ${f.coefficients.weather} × ${f.coefficients.event}`}</h2>
    <p>{intervalLabel(point.start, point.end, f.current?.filters.resolution === 'day')} · МСК</p>
    <strong data-testid="map-demand" data-raw-value={point.value ?? ''}>{format(point.value)} успешных посадок</strong>
    <p>{statusLabels[point.status]} · {format(point.coverage * 100)}%</p>
    {point.base_value !== undefined && <p>База: {format(point.base_value)} · разница: {format(point.delta ?? null)}</p>}
    <p>Соседние {f.current?.filters.resolution === 'day' ? 'дни' : 'часы'}: предыдущий — {format(previous?.value ?? null)}, следующий — {format(next?.value ?? null)}.</p>
    <p><b>Следующее действие:</b> проверьте фактический выпуск и интервалы в этом периоде. Перераспределение оценивается при наличии расписания, высадок и вместимости.</p>
    <p className="dispatch-muted">Уровень маршрута. Схема 2026, прогноз 2025; распределение по остановкам не оценено.</p>
  </section>;
}

export function OverviewButton() {
  const f = useForecastData();
  return <Button onClick={() => f.changeRoute(OVERVIEW)} disabled={!f.caps}>Обзор маршрутов</Button>;
}
