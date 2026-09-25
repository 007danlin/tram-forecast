import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { TramMap } from './components/TramMap';
import { addDays, ApiError, buildFilters, exportResult, getCapabilities, getResult, sameFilters } from './handoff';
import type { Capabilities, Horizon, Result, Row } from './handoff';

const format = (value: number | null) => value === null ? 'Нет данных' : value.toLocaleString('ru-RU', {maximumFractionDigits: 2});
const labels = {ok: 'Полное покрытие', cold_start_zero_baseline: 'Нулевой baseline', partial: 'Неполное покрытие', no_data: 'Нет данных'};
const message = (error: unknown) => error instanceof Error ? error.name === 'AbortError' ? 'Время ожидания истекло. Повторите запрос.' : error.message : 'Не удалось получить данные.';

function Chart({rows, selected}: {rows: Row[]; selected: number}) {
  const max = Math.max(1, ...rows.map(row => row.value ?? 0));
  const x = (i: number) => 45 + i * 510 / Math.max(1, rows.length - 1);
  const y = (n: number) => 160 - n / max * 130;
  // A missing value starts a new segment instead of joining across the gap.
  let drawing = false;
  const path = rows.map((row, i) => {
    if (row.value === null) { drawing = false; return ''; }
    const part = `${drawing ? 'L' : 'M'}${x(i)},${y(row.value)}`; drawing = true; return part;
  }).join(' ');
  return <svg className="forecast-chart" viewBox="0 0 600 200" role="img" aria-label="Прогноз успешных посадок; пропуски показаны разрывами. Значения доступны в таблице.">
    <line x1="45" y1="160" x2="555" y2="160" stroke="#c9d1de" />
    <text x="0" y="30">{format(max)}</text><text x="20" y="165">0</text>
    <path d={path} fill="none" stroke="#2456ca" strokeWidth="2.5" />
    {rows.map((row, i) => row.value !== null && <circle key={row.start} cx={x(i)} cy={y(row.value)} r={selected === i ? 5 : 2.5} fill={selected === i ? '#c48000' : '#2456ca'}><title>{row.start}: {row.value} успешных посадок</title></circle>)}
    <text x="45" y="190">{rows[0]?.start.slice(5, 16).replace('T', ' ')}</text>
    <text x="555" y="190" textAnchor="end">{rows.at(-1)?.start.slice(5, 16).replace('T', ' ')}</text>
  </svg>;
}

function App() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [route, setRoute] = useState('');
  const [day, setDay] = useState('');
  const [horizon, setHorizon] = useState<Horizon>('day');
  const [bootstrap, setBootstrap] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [loadingCaps, setLoadingCaps] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [errorStatus, setErrorStatus] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [exporting, setExporting] = useState(false);
  const [tab, setTab] = useState<'chart' | 'table'>('chart');
  const [selected, setSelected] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [closed, setClosed] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const card = useRef<HTMLElement>(null);
  const exportController = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const filtersState = useMemo(() => {
    if (!caps) return {filters: null, problem: ''};
    try { return {filters: buildFilters(caps, route, day, horizon), problem: ''}; }
    catch (e) { return {filters: null, problem: message(e)}; }
  }, [caps, route, day, horizon]);
  const filters = filtersState.filters;
  const current = result && filters && sameFilters(result.filters, filters) ? result : null;
  const busy = loadingCaps || loading;
  const changeContext = () => {
    generation.current += 1; exportController.current?.abort(); setPlaying(false); setExporting(false);
  };
  const showError = (e: unknown) => {setError(message(e)); setErrorStatus(e instanceof ApiError ? e.status : 0);};

  useEffect(() => {
    const controller = new AbortController(); let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    setLoadingCaps(true); setCaps(null); setResult(null); setError(''); setErrorStatus(0);
    void getCapabilities(controller.signal).then(value => {
      if (!active) return;
      setCaps(value); setRoute((value.routes.find(r => r.method === 'model') ?? value.routes[0]).route_id);
      setDay(value.start.slice(0, 10)); setHorizon(value.resolutions.includes('hour') ? 'day' : 'week');
    }).catch(e => {if (active) showError(e);}).finally(() => {window.clearTimeout(timeout); if (active) setLoadingCaps(false);});
    return () => {active = false; controller.abort(); window.clearTimeout(timeout);};
  }, [bootstrap]);

  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setResult(null); setSelected(0); setPlaying(false); setLoading(false);
    if (!filters) return;
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    setLoading(true); setError(''); setErrorStatus(0);
    void getResult(filters, controller.signal).then(value => {if (active) setResult(value);})
      .catch(e => {if (active) showError(e);}).finally(() => {window.clearTimeout(timeout); if (active) setLoading(false);});
    return () => {active = false; controller.abort(); window.clearTimeout(timeout);};
  }, [filters, attempt]);

  useEffect(() => () => exportController.current?.abort(), []);
  useEffect(() => {
    if (!playing || !current || busy || error) return;
    const timer = window.setInterval(() => setSelected(i => {
      if (i >= current.rows.length - 1) {setPlaying(false); return i;}
      return i + 1;
    }), 1000);
    return () => window.clearInterval(timer);
  }, [playing, current, busy, error]);

  async function download() {
    if (!current || busy || error || exporting) return;
    const version = generation.current;
    const controller = new AbortController(); exportController.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    setExporting(true); setPlaying(false);
    try {
      const blob = await exportResult(current, controller.signal);
      if (controller.signal.aborted || generation.current !== version) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = `tramflow-${current.filters.start.slice(0, 10)}.csv`;
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {if (generation.current === version) showError(e);}
    finally {window.clearTimeout(timeout); if (generation.current === version) setExporting(false);}
  }
  function retry() {
    changeContext(); setError('');
    if (!caps || errorStatus === 410) {setCaps(null); setBootstrap(v => v + 1);}
    else setAttempt(v => v + 1);
  }
  function openCard(table = false) {
    setClosed(false); if (table) setTab('table');
    window.setTimeout(() => {card.current?.focus(); card.current?.scrollIntoView({behavior: 'smooth', block: 'nearest'});}, 0);
  }
  const point = current?.rows[selected];
  return <div className="forecast-app">
    <header className="forecast-header"><div><strong>TRAMFLOW</strong><span>Прогноз успешных посадок</span></div><span className="forecast-badge">Исторический прогноз, ноябрь–декабрь 2025</span><nav aria-label="Разделы"><a href="#map">Карта</a><button onClick={() => openCard(true)}>Аналитика</button></nav></header>
    <section className="forecast-filters" aria-label="Фильтры прогноза">
      <label>Маршрут<select aria-label="Маршрут" value={route} disabled={!caps} onChange={e => {changeContext(); setRoute(e.target.value);}}>{caps?.routes.map(r => <option key={r.route_id} value={r.route_id}>№ {r.route_id}{r.method === 'baseline' ? ' · нулевой baseline' : ''}</option>)}</select></label>
      <label>Дата (МСК)<input aria-label="Дата (МСК)" type="date" value={day} min={caps?.start.slice(0, 10)} max={caps ? addDays(caps.end.slice(0, 10), -1) : undefined} disabled={!caps} onChange={e => {changeContext(); setDay(e.target.value);}} /></label>
      <label>Период<select aria-label="Период" value={horizon} disabled={!caps} onChange={e => {changeContext(); setHorizon(e.target.value as Horizon);}}><option value="day" disabled={!caps?.resolutions.includes('hour')}>День</option><option value="week" disabled={!caps?.resolutions.includes('day')}>Неделя</option><option value="month" disabled={!caps?.resolutions.includes('day')}>Месяц</option></select></label>
      <button disabled={!caps} onClick={() => {if (caps) {changeContext(); setRoute((caps.routes.find(r => r.method === 'model') ?? caps.routes[0]).route_id); setDay(caps.start.slice(0, 10)); setHorizon('day');}}}>Сбросить</button>
      <p className="forecast-filter-note">Остановки, направления, сценарии и прогноз на год недоступны. {caps && `Доступно: ${caps.start.slice(0, 10)} — ${addDays(caps.end.slice(0, 10), -1)}.`}</p>
    </section>
    <div className="forecast-workspace">
      <div id="map" className="forecast-map"><TramMap /></div>
      <div className="forecast-bottom">
        {closed ? <button ref={opener} className="forecast-open" onClick={() => openCard()}>Открыть прогноз</button> : <section ref={card} tabIndex={-1} className="forecast-card" aria-label="Прогноз успешных посадок" onKeyDown={e => {if (e.key === 'Escape') {setClosed(true); window.setTimeout(() => opener.current?.focus(), 0);}}}>
          <div className="forecast-card-heading"><h1>Прогноз успешных посадок</h1><button aria-label="Свернуть прогноз" onClick={() => {setClosed(true); window.setTimeout(() => opener.current?.focus(), 0);}}>×</button></div>
          {caps && <p>Маршрут № {route} · {day} · МСК</p>}
          {caps?.routes.find(r => r.route_id === route)?.method === 'baseline' && <p className="forecast-warning">Нулевой baseline: нет успешной истории обучения. Это не означает отсутствия движения.</p>}
          <p role="status">{loadingCaps ? 'Проверяем готовность пакета…' : loading ? 'Загружаем прогноз…' : current ? `Покрытие: ${format(current.coverage * 100)}%` : 'Прогноз не получен'}</p>
          {(error || filtersState.problem) && <p role="alert">{error || filtersState.problem}</p>}
          {current && <>
            <p className="forecast-total-label">{current.total_scope === 'available_only' ? 'Сумма доступных значений' : current.total_scope === 'no_data' ? 'Нет данных за период' : 'Всего успешных посадок'}</p>
            <p className="forecast-total" title={String(current.total)} data-testid="total" data-raw-value={current.total ?? ''}>{format(current.total)}</p>
            {current.total_scope === 'available_only' && <p className="forecast-warning">Неполное покрытие (partial): пропуски не заменены нулями.</p>}
            {current.total_scope === 'no_data' && <p className="forecast-warning">Нет данных (no_data): выберите другой период или повторите запрос.</p>}
            <div className="forecast-tabs" aria-label="Представление"><button aria-pressed={tab === 'chart'} onClick={() => setTab('chart')}>График</button><button aria-pressed={tab === 'table'} onClick={() => setTab('table')}>Таблица</button></div>
            {tab === 'chart' ? <Chart rows={current.rows} selected={selected} /> : <div className="forecast-table"><table><caption>Время МСК (+03:00). Раскройте число для исходной точности.</caption><thead><tr><th scope="col">Интервал</th><th scope="col">Посадки</th><th scope="col">Покрытие</th></tr></thead><tbody>{current.rows.map((row, i) => <tr key={row.start} aria-selected={i === selected} data-start={row.start} data-route={row.route_id}><th scope="row"><time dateTime={row.start}>{row.start.slice(5, 16).replace('T', ' ')}</time></th><td data-raw-value={row.value ?? ''}>{row.value === null ? 'Нет данных' : <details><summary>{format(row.value)}</summary><span>{String(row.value)}</span></details>}</td><td title={labels[row.status]}>{row.available_hours}/{row.expected_hours} · {labels[row.status]}</td></tr>)}</tbody></table></div>}
            <details className="forecast-details"><summary>Версия и ограничения</summary><p>Run: <code data-testid="run">{current.forecast_run_id}</code></p><p>Метод интервала: {current.interval_method}. Номинальная граница не гарантирует фактическое покрытие. Дневные границы не вычисляются суммой почасовых.</p><p>Модель: <code>{current.model_version}</code></p><p>CSV SHA-256: <code>{current.csv_sha256}</code></p><p>Импорт пакета: {current.imported_at} (не время обучения).</p><ul>{[...new Set([...current.warnings, ...current.limitations])].map(w => <li key={w}>{w}</li>)}</ul></details>
          </>}
          <div className="forecast-actions"><button disabled={busy || exporting} onClick={retry}>{errorStatus === 410 ? 'Обновить доступные данные' : error ? 'Повторить запрос' : 'Обновить прогноз'}</button><button disabled={!current || busy || !!error || exporting} onClick={() => void download()}>{exporting ? 'Скачиваем…' : 'Скачать CSV'}</button></div>
          <p className="forecast-fine">CSV содержит показанный прогноз без округления. Это диспетчерский экспорт, не конкурсный submission. Посадки не равны заполненности вагона.</p>
        </section>}
        <section className="forecast-time" aria-label="Просмотр интервалов"><h2>Время · МСК (UTC+03:00)</h2><p>{point ? `${point.start.slice(0, 16).replace('T', ' ')} — ${point.end.slice(11, 16)}` : 'Выберите доступный период'}</p><div><button disabled={!current || busy || !!error} onClick={() => {if (current && selected >= current.rows.length - 1) setSelected(0); setPlaying(v => !v);}}>{playing ? 'Пауза' : 'Воспроизвести'}</button><input aria-label="Текущий интервал" type="range" min="0" max={Math.max(0, (current?.rows.length ?? 1) - 1)} value={selected} disabled={!current || busy || !!error} onChange={e => {setPlaying(false); setSelected(Number(e.target.value));}} /></div><p>{point ? `${format(point.value)} посадок · ${labels[point.status]}` : 'Данные не загружены'} · шаг {filters?.resolution === 'day' ? '1 сутки' : '1 час'}</p><p className="forecast-fine">Схема самостоятельна: линии карты не связаны с маршрутом прогноза.</p></section>
      </div>
    </div>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
