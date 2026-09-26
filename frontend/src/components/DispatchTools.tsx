import { useState } from 'react';
import { OVERVIEW } from '../handoff';
import { format, useForecastData } from '../useForecast';
import { dateLabel, intervalLabel } from '../display';
import { Button } from './ui';
import './DispatchTools.css';

export function YearView() {
  const f = useForecastData(), meta = f.caps?.year;
  const start = f.day ? `${f.day.slice(0, 7)}-01` : '';
  const next = start ? `${Number(start.slice(0,4)) + 1}${start.slice(4)}T00:00:00+03:00` : '';
  const end = next ? new Date(Date.parse(next) - 1).toISOString().slice(0,10) : '';
  return <section className="dispatch-panel year-view" aria-label="Качественный год">
    <h1>Сценарии на год</h1>
    <p data-testid="year-period">{dateLabel(start, true)} — {dateLabel(end, true)} · МСК</p>
    {f.routeUnavailable && <p role="status">Маршрут только на схеме. Прогноза нет.</p>}
    {f.caps?.routes.find(r => r.route_id === f.route)?.method === 'baseline' && <p role="status">Нет истории обучения: модель возвращает 0. Движение по маршруту возможно.</p>}
    {meta?.qualitative_available ? <>
      <p className="year-view__notice">Для численного прогноза недостаточно истории: доступно {meta.history_months} месяцев, по {dateLabel(meta.history_end, true)}.</p>
      <div className="year-view__scenarios">{meta.scenarios.map(s => <article key={s.name}><h2>{s.title}</h2><p>{s.assumption}</p>
        <details><summary>Что проверить</summary><p>{s.change}</p><p>{s.needed}</p></details>
      </article>)}</div>
      <details className="year-view__source"><summary>О данных</summary><p>Годовая сезонность не проверена. Сумма за год и интервал неопределённости не рассчитаны.</p><p>Версия: {meta.version}. Источник: {meta.source}.</p></details>
    </> : <p>Годовые сценарии недоступны.</p>}
    <Button disabled aria-label="Скачать CSV">CSV недоступен без численного прогноза</Button>
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
<p className="dispatch-muted">Успешные посадки · МСК</p>
    {f.current && <p>{dateLabel(f.current.filters.start, true)} — {dateLabel(new Date(Date.parse(f.current.filters.end) - 1).toISOString().slice(0, 10), true)}</p>}
    {f.busy && <p role="status">Загружаем обзор…</p>}
    {f.error && <><p role="alert">{f.error}</p><Button onClick={f.retry}>Повторить запрос</Button></>}
    <label>Сортировать по спросу <select aria-label="Сортировка обзора" value={sort} onChange={e => setSort(e.target.value as 'total' | 'selected')}>
      <option value="total">За период</option><option value="selected">В выбранный интервал</option></select></label>
    <label>Интервал МСК <select aria-label="Интервал обзора" value={f.selected} disabled={!times.length} onChange={e => f.setSelected(Number(e.target.value))}>
      {times.map((t,i) => <option key={t} value={i}>{t.slice(0,16).replace('T',' ')}</option>)}</select></label>
    {f.current && <div className="forecast-table-wrap" role="region" tabIndex={0} aria-label="Сводная таблица спроса">
      <table className="forecast-table"><caption>Маршруты с неполными данными и без истории обучения — внизу.</caption>
        <thead><tr><th>Маршрут</th><th>Сумма</th><th>Выбранный интервал</th><th>Первый максимум</th><th>Покрытие / статус</th></tr></thead>
        <tbody>{summaries.map(s => <tr key={s.route.route_id} data-overview-route={s.route.route_id}>
          <td><Button onClick={() => f.changeRoute(s.route.route_id)}>№ {s.route.route_id}</Button></td>
          <td data-overview-total={s.total ?? ''}>{format(s.total)}</td><td data-overview-selected={s.selected?.value ?? ''}>{format(s.selected?.value ?? null)}</td>
          <td>{s.peak ? intervalLabel(s.peak.start, s.peak.end, f.current?.filters.resolution === 'day') : 'Нет данных'}</td>
          <td>{format(s.coverage * 100)}% · {s.route.method === 'baseline' ? 'Нет истории обучения' : s.coverage === 1 ? 'Полное покрытие' : s.coverage ? 'Неполные данные' : 'Нет данных'}</td>
        </tr>)}</tbody></table></div>}
    <p className="dispatch-muted">№ 5: нет истории обучения, модель возвращает 0. Движение по маршруту возможно.</p>
    <Button disabled={!f.current || f.busy || !!f.error || f.exporting} onClick={() => void f.download()} aria-label="Скачать CSV">CSV всего обзора</Button>

  </section>;
}

export function NeighborValues() {
  const f = useForecastData();
  if (!f.points.length) return null;
  return <div className="neighbor-values" aria-label="Соседние интервалы">{[-1, 1].map(offset => {
    const point = f.points[f.selected + offset];
    return <Button variant="ghost" key={offset} disabled={!point} onClick={() => {f.setPlaying(false); f.setSelected(f.selected + offset);}}>
      <span>{point ? intervalLabel(point.start, point.end, f.current?.filters.resolution === 'day') : offset < 0 ? 'Начало периода' : 'Конец периода'}</span>
      <strong>{point ? format(point.value) : '—'}</strong>
    </Button>;
  })}</div>;
}

export function DemandIndicator() {
  const f = useForecastData(), point = f.points[f.selected];
  if (!point || f.horizon === 'year') return null;
  return <section className="dispatch-panel demand-indicator" aria-label="Спрос выбранного маршрута">
    <h2>{intervalLabel(point.start, point.end, f.current?.filters.resolution === 'day')} · МСК</h2>
    <strong data-raw-value={point.value ?? ''}>{format(point.value)} успешных посадок</strong>
    {point.base_value !== undefined && <p>База {format(point.base_value)} · разница {format(point.delta ?? null)}</p>}
    {point.coverage < 1 && <p>Покрытие {format(point.coverage * 100)}%</p>}
  </section>;
}

export function OverviewButton() {
  const f = useForecastData();
  return <Button onClick={() => f.changeRoute(OVERVIEW)} disabled={!f.caps}>Обзор маршрутов</Button>;
}
