import { useState } from 'react';
import { format, useForecastData } from '../useForecast';
import { dateLabel, intervalLabel } from '../display';
import { Button } from './ui';
import './DispatchTools.css';

const yearCopy: Record<string, {title: string; action: string; review: string}> = {
  recent_level: {title: 'Без изменений', action: 'Ежемесячно сверять почасовые посадки с расписанием и фактическими рейсами.', review: 'Пересмотреть при изменении расписания или устойчивом расхождении факта с прежним профилем.'},
  lower_service: {title: 'Меньше рейсов', action: 'После подтверждения сокращения проверить затронутые часы и соседние маршруты.', review: 'Пересмотреть после изменения выпуска или появления факта за затронутый период.'},
  higher_demand: {title: 'Выше спрос', action: 'Для подтверждённого события проверить выпуск и интервалы; сопоставить посадки до и после.', review: 'Пересмотреть при отмене события либо неподтверждённом росте по новым наблюдениям.'},
};
export function YearView() {
  const f = useForecastData(), meta = f.caps?.year;
  const start = f.day ? `${f.day.slice(0, 7)}-01` : '';
  const monthAt = (offset: number) => new Date(Date.UTC(Number(start.slice(0,4)), Number(start.slice(5,7)) - 1 + offset, 1)).toISOString().slice(0,10);
  const end = start ? new Date(Date.parse(monthAt(12)) - 86400000).toISOString().slice(0,10) : '';
  const route = f.caps?.routes.find(r => r.route_id === f.route);
  const supported = route?.method === 'model';
  const basePeak = supported && f.current?.total_scope === 'complete'
    ? f.current.rows.reduce<(typeof f.rows)[number] | null>((best, row) => row.value !== null && (!best || row.value > best.value!) ? row : best, null) : null;
  const quarters = [
    ['Зафиксировать основу', 'Получить почасовой факт, действующее расписание и выполненные рейсы. Сопоставлять одинаковые типы дней.'],
    ['Проверить изменения', 'Ежемесячно сравнивать новые наблюдения с основой. При смене расписания отделить периоды до и после.'],
    ['Обновить оценку', 'Проверить накопленный факт и полноту выгрузки. Новую модель принимать только после временной проверки качества.'],
    ['Пересмотреть год', 'Проверить, накоплен ли полный сезонный цикл. Если данных по-прежнему мало, сохранить качественные сценарии.'],
  ];
  return <section className="dispatch-panel year-view" aria-label="Качественный год">
    <p className="year-view__lead">{route || f.routeUnavailable ? `Маршрут № ${f.route}` : 'Выберите отдельный маршрут'}</p>
    <p>Численного прогноза пока нет</p>
    <p data-testid="year-period">{dateLabel(start, true)} — {dateLabel(end, true)} · МСК</p>
    {f.routeUnavailable && <p role="status">Маршрут только на схеме. Прогноза нет.</p>}
    {route?.method === 'baseline' && <p role="status">Нет истории обучения: модель возвращает 0. Движение по маршруту возможно. Для годового плана нужны фактические посадки этого маршрута.</p>}
    {supported && meta?.qualitative_available ? <>
      <div className="year-view__basis" data-testid="year-basis">
        <h2>Основа и границы</h2>
        <p>В паспорте модели: {meta.history_months} месяцев истории, по {dateLabel(meta.history_end, true)}. Проверенный исторический профиль отдельно для этого маршрута в сервис не передан.</p>
        {basePeak ? <p>В выбранном базовом прогнозе первый максимум — {intervalLabel(basePeak.start, basePeak.end, f.current?.filters.resolution === 'day')}, {format(basePeak.value)} посадок. Это ориентир для ближайшей проверки, а не сезонный профиль на год.</p>
          : <p>Полного базового прогноза за выбранный период нет. Интервалы для проверки пока не определены.</p>}
        {f.scenarioActive && <p>Текущие ручные поправки сохранены. На будущие месяцы они не переносятся.</p>}
        <p>Годовые допущения ниже условны. Даты и часы будущих изменений нужно подтвердить отдельно.</p>
      </div>
      <div className="year-view__scenarios">{meta.scenarios.map(s => <article key={s.name}><h2>{yearCopy[s.name]?.title ?? s.title}</h2><p>{s.assumption}</p>
        <p>{s.change}</p><details><summary>Действие и пересмотр</summary><p>{yearCopy[s.name]?.action}</p><p>{s.needed}</p><p>{yearCopy[s.name]?.review}</p></details>
      </article>)}</div>
      {start && <section className="year-view__plan" aria-label="План на 12 месяцев"><h2>План проверки · № {f.route}</h2>{quarters.map(([title, action], i) => <article key={title}>
        <h3>{dateLabel(monthAt(i * 3), true)} — {dateLabel(new Date(Date.parse(monthAt(i * 3 + 3)) - 86400000).toISOString().slice(0,10), true)}</h3>
        <p><strong>{title}.</strong> {action}</p>
      </article>)}</section>}
      <details className="year-view__source"><summary>О данных</summary><p>Годовая сезонность не проверена. Сумма за год и интервал неопределённости не рассчитаны.</p><p>Версия: {meta.version}. Источник допущений: {meta.source}. {f.current && <>Источник ближайшего прогноза: {f.current.model_version}; run {f.current.forecast_run_id}.</>}</p></details>
    </> : supported ? <p>Годовые сценарии недоступны: метаданные не переданы.</p> : <p>Персональный годовой сценарий недоступен без истории выбранного маршрута.</p>}
    <p className="panel-note">CSV за год недоступен: значения не рассчитаны.</p>
  </section>;
}

export function DispatchAction() {
  const f = useForecastData(), point = f.points[f.selected];
  if (!f.current || !point || f.overview || point.method === 'baseline') return null;
  const daily = f.current.filters.resolution === 'day';
  const complete = f.current.total_scope === 'complete' && point.status === 'ok';
  return <details className="dispatch-action" data-testid="dispatch-action">
    <summary>Проверить выпуск</summary>
    <p>№ {f.route} · {intervalLabel(point.start, point.end, daily)} · МСК</p>
    <p>{f.scenarioActive ? 'С ручными поправками' : 'Базовый прогноз'} · посадки за {daily ? 'день' : 'час'}.</p>
    {!complete && <p role="status">Данные неполные: сравнение не подтверждает спрос за весь период. Сначала проверьте полноту выгрузки.</p>}
    <dl>{[f.selected - 1, f.selected, f.selected + 1].filter(i => i >= 0 && i < f.points.length).map(i => {
      const row = f.points[i];
      const difference = complete && row.status === 'ok' && row.value !== null && point.value !== null ? point.value - row.value : null;
      return <div key={row.start}><dt>{intervalLabel(row.start, row.end, daily)}</dt><dd><span data-dispatch-value={row.value ?? ''}>{format(row.value)}</span>
        {f.scenarioActive && <span> · без поправок {format(row.base_value ?? null)}</span>}
        {i !== f.selected && difference !== null && <span> · выбранный {difference >= 0 ? '+' : '−'}{format(Math.abs(difference))}</span>}</dd></div>;
    })}</dl>
    <p>{complete ? 'Сверьте выпуск и интервалы в выбранное время с расписанием и отчётом о выполненных рейсах.' : 'После проверки данных сверьте расписание и выполненные рейсы.'} Для решения о числе вагонов нужны вместимость и высадки.</p>
    <p>Сохраните выбранный период кнопкой CSV. {f.scenarioActive ? 'Экспорт содержит базу, поправки и результат сценария.' : 'Экспорт содержит тот же базовый прогноз.'}</p>
  </details>;
}

export function RouteOverview({onOpenScenario, onSelectRoute}: {onOpenScenario: () => void; onSelectRoute: (route: string) => void}) {
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
    <div className="overview-heading"><h1>Сравнение маршрутов</h1><div><Button variant="ghost" className="overview-scenario" onClick={onOpenScenario} disabled={!f.caps?.scenario_supported}>Поправки</Button><Button disabled={!f.current || f.busy || !!f.error || f.exporting} onClick={() => void f.download()} aria-label="Скачать CSV">CSV ↓</Button></div></div>
    {f.scenarioActive && <p className="scenario-active" role="status">Ручные поправки для всех маршрутов</p>}
    <p className="dispatch-muted">Посадки · {f.current ? `${dateLabel(f.current.filters.start, true)} · ` : ''}МСК</p>
    {f.busy && <p role="status">Загружаем обзор…</p>}
    {f.error && <><p role="alert">{f.error}</p><Button onClick={f.retry}>Повторить запрос</Button></>}
    <div className="overview-controls">
      <label>Сортировка<select aria-label="Сортировка обзора" value={sort} onChange={e => setSort(e.target.value as 'total' | 'selected')}><option value="total">За период</option><option value="selected">В выбранный интервал</option></select></label>
      <label>Интервал · МСК<select aria-label="Интервал обзора" value={f.selected} disabled={!times.length} onChange={e => f.setSelected(Number(e.target.value))}>{times.map((t,i) => <option key={t} value={i}>{f.horizon === 'day' ? t.slice(11,16) : dateLabel(t, true)}</option>)}</select></label>
    </div>
    {f.current && <div className="forecast-table-wrap" role="region" tabIndex={0} aria-label="Сводная таблица спроса">
      <table className="forecast-table"><caption>Маршруты с неполными данными и без истории обучения — внизу.</caption>
        <thead><tr><th>Маршрут</th><th>За период</th><th>Выбранный<br/>интервал</th><th className="overview-extra">Первый максимум</th><th className="overview-extra">Покрытие / статус</th></tr></thead>
        <tbody>{summaries.map(s => <tr key={s.route.route_id} data-overview-route={s.route.route_id}>
          <td><Button onClick={() => onSelectRoute(s.route.route_id)}>№ {s.route.route_id}</Button>{s.category > 0 && <span className="overview-route-note">{s.category === 2 ? "Нет истории" : `Покрытие ${format(s.coverage * 100)}%`}</span>}</td>
          <td data-overview-total={s.total ?? ''}>{format(s.total)}</td><td data-overview-selected={s.selected?.value ?? ''}>{format(s.selected?.value ?? null)}</td>
          <td className="overview-extra">{s.peak ? intervalLabel(s.peak.start, s.peak.end, f.current?.filters.resolution === 'day') : 'Нет данных'}</td>
          <td className="overview-extra">{format(s.coverage * 100)}% · {s.route.method === 'baseline' ? 'Нет истории обучения' : s.coverage === 1 ? 'Полное покрытие' : s.coverage ? 'Неполные данные' : 'Нет данных'}</td>
        </tr>)}</tbody></table></div>}

  </section>;
}
