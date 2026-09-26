import { useEffect, useState } from 'react';
import './SourceMonitor.css';

type RecordItem = {
  id: string; title: string; source_url: string; fetched_at: string;
  valid_start: string | null; valid_end: string | null; published_at: string | null;
  location: {name: string | null; address?: string};
  route_link: {status: string; route_ids: string[]};
  values: {temperature_c?: number; precipitation_mm?: number; wind_ms?: number}; note: string | null;
};
type Source = {
  id: string; title: string; provider: string; url: string; description: string;
  status: 'fresh' | 'stale' | 'lagging' | 'error' | 'pending' | 'disabled' | 'blocked';
  last_success_at: string | null; last_attempt_at: string | null; next_refresh_at: string | null;
  error: string | null; refreshing: boolean; record_count: number; unknown_route_count: number;
  coverage: {scope?: string; latest_publication?: string; complete?: boolean};
  preview: RecordItem[]; attribution?: string; license_url?: string;
};
type Monitor = {schema_version: string; generated_at: string; sources: Source[]; automatic: boolean};
const labels = {fresh: 'Обновляется', stale: 'Данные устарели', lagging: 'Лента давно не обновлялась', error: 'Ошибка обновления', pending: 'Первое обновление', disabled: 'Мониторинг выключен', blocked: 'Не подключено'};
const date = (value: string | null) => value ? new Date(value).toLocaleString('ru-RU', {timeZone: 'Europe/Moscow',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : 'ещё не получены';
const number = (value: number | undefined) => value === undefined ? '—' : value.toLocaleString('ru-RU', {maximumFractionDigits:1});
const safeLink = (value: string) => {try {return new URL(value).protocol === 'https:' ? value : undefined;} catch {return undefined;}};

function SourceIcon({kind}: {kind: string}) {
  const paths: {[key: string]: React.ReactNode} = {
    weather: <><path d="M8 17a4 4 0 1 1 2-7.5A5 5 0 1 1 18 17H8Z"/><path d="M8 20v1m5-1v1m5-1v1M7 3v2M2 8h2m0-5 1.5 1.5"/></>,
    closures: <><path d="m3 10 3-5h12l3 5v7H3Z M6 17v4m12-4v4M7 5l4 5m2-5 4 5M3 13h18"/></>,
    changes: <><rect x="6" y="3" width="12" height="15" rx="3"/><path d="M6 11h12M9 6h6m-6 9h.01M15 15h.01M9 18l-2 3m8-3 2 3M9 1h6"/></>,
    events: <><rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 3v4m8-4v4M4 10h16m-8 3 1 2 2 .3-1.5 1.4.4 2-1.9-1-1.9 1 .4-2L9 15.3l2-.3Z"/></>,
    traffic: <><rect x="8" y="2" width="8" height="17" rx="3"/><path d="M12 19v3"/><circle cx="12" cy="6" r="1"/><circle cx="12" cy="10.5" r="1"/><circle cx="12" cy="15" r="1"/></>,
  };
  return <span className={`source-icon source-icon--${kind}`}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[kind] ?? paths.events}</svg></span>;
}

export function SourceMonitor() {
  const [data,setData]=useState<Monitor|null>(null), [error,setError]=useState('');
  useEffect(() => {
    let active=true; let timer: ReturnType<typeof setTimeout>; let controller: AbortController;
    async function read() {
      controller=new AbortController(); const timeout=setTimeout(()=>controller.abort(),10000);
      try {
        const response=await fetch('/api/v2/monitoring/status',{signal:controller.signal,cache:'no-store'});
        if (!response.ok) throw new Error('Мониторинг временно недоступен');
        const value: Monitor=await response.json();
        if(value.schema_version!=='operational-monitor-v1' || !Array.isArray(value.sources) || value.sources.some(s=>!(s.status in labels) || !Array.isArray(s.preview))) throw new Error('Не удалось прочитать состояние источников');
        if(active){setData(value);setError('');}
      } catch {if(active) setError('Нет связи с мониторингом. Показаны последние известные сведения.');}
      finally {clearTimeout(timeout);if(active) timer=setTimeout(()=>void read(),30000);}
    }
    void read();
    return ()=>{active=false;clearTimeout(timer);controller?.abort();};
  },[]);
  return <section className="source-monitor" aria-labelledby="monitor-title" data-testid="source-monitor">
    <div className="source-monitor__heading"><div><p className="eyebrow">Город сейчас</p><h3 id="monitor-title">Источники под наблюдением</h3></div><span className="source-monitor__auto">{error ? 'Нет связи' : data ? data.automatic ? 'Автоматически' : 'Остановлен' : 'Проверяем'}</span></div>
    <p className="source-monitor__intro">Сервис сам проверяет погоду, ограничения и городские события. Время указано по Москве.</p>
    {error && <p role="alert" className="source-monitor__error">{error}</p>}
    {!data && !error && <p role="status">Проверяем состояние источников…</p>}
    <div className="source-grid">
      {data?.sources.map(source=> <article className="source-card" key={source.id} data-source={source.id} data-status={error ? 'error' : source.status}>
        <header><SourceIcon kind={source.id}/><div><h4>{source.title}</h4><a href={safeLink(source.url)} target="_blank" rel="noopener noreferrer">{source.provider} <span aria-hidden="true">↗</span></a></div></header>
        <span className="source-status"><i aria-hidden="true"/>{error ? 'Нет связи' : labels[source.status]}</span>
        <p className="source-card__description">{source.description}</p>
        {source.id==='weather' && source.preview[0] && <div className="source-weather"><strong>{number(source.preview[0].values.temperature_c)}°</strong><span>Прогноз на {date(source.preview[0].valid_start)}<br/>{number(source.preview[0].values.precipitation_mm)} мм · ветер {number(source.preview[0].values.wind_ms)} м/с</span></div>}
        {source.id!=='weather' && source.status!=='blocked' && <p className="source-card__count">{source.record_count.toLocaleString('ru-RU')} записей <span>в последнем снимке</span></p>}
        {source.status!=='blocked' && <p className="source-card__time">Получено: <time>{date(source.last_success_at)}</time>{source.refreshing && <span> · проверяем…</span>}</p>}
        {source.coverage.latest_publication && <p className="source-card__time">Последняя публикация: {date(source.coverage.latest_publication)}</p>}
        {source.error && <p className="source-monitor__error">{source.error}</p>}
        <details><summary>Об источнике и свежести</summary>
          {source.status==='blocked' ? <p>Ключ и покрытие Москвы пока не проверены. Данные о пробках не собираются.</p> : <>
            <p>Последняя попытка: {date(source.last_attempt_at)}. Следующая проверка: {date(source.next_refresh_at)}.</p>
            <p>{source.coverage.scope || 'Ожидается первый проверенный снимок.'}</p>
            {source.record_count>0 && <p>Связь с трамвайным маршрутом неизвестна для {source.unknown_route_count} из {source.record_count} записей.</p>}
            {source.preview.map(item=><div className="source-record" key={item.id}>
              <a href={safeLink(item.source_url)} target="_blank" rel="noopener noreferrer">{item.title}</a>
              <p>{item.location.name || 'Место не установлено'}{item.location.address ? ` · ${item.location.address}` : ''}</p>
              <p>{item.valid_start ? date(item.valid_start) : 'Начало неизвестно'} — {item.valid_end ? date(item.valid_end) : 'Окончание неизвестно'}</p>
              <p>{item.route_link.status==='explicit' ? `Трамвайные маршруты: ${item.route_link.route_ids.join(', ')}` : 'Связь с трамвайным маршрутом не установлена'}</p>
              <p>{item.note}</p>
            </div>)}
          </>}
          {source.attribution && <p>{source.attribution}{source.license_url && <> · <a href={source.license_url} target="_blank" rel="noopener noreferrer">Лицензия</a></>}</p>}
        </details>
      </article>)}
    </div>
    <div className="source-monitor__boundary"><span aria-hidden="true">◷</span><p><b>Прогноз и мониторинг — разные периоды.</b><br/>Модель B2 прогнозирует ноябрь–декабрь 2025. Новые онлайн-данные сохраняются отдельно; их влияние на числа ещё не подтверждено проверкой.</p></div>
  </section>;
}
