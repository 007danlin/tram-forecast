import { useRef, useState } from 'react';
import { format, useForecastData } from '../useForecast';
import { intervalLabel } from '../display';
import { ForecastLineChart, ForecastTable } from './ForecastData';
import { ForecastMetrics, ForecastNotices } from './ForecastSummary';
import { TimelinePanel } from './TimelinePanel';
import { DispatchAction } from './DispatchTools';
import { WeeklyComparisonCard } from './WeeklyComparison';
import { useWeeklyComparison } from '../useWeeklyComparison';
import { Button } from './ui';
import './ForecastCard.css';

export function ForecastCard({onOpenScenario, onOpenForecast, compact}: {onOpenScenario: () => void; onOpenForecast: () => void; compact: boolean}) {
  const f = useForecastData();
  const touchStart = useRef<{x:number; y:number; time:number} | null>(null);
  const [chartMode, setChartMode] = useState<'chart' | 'table'>('chart');
  const point = f.points[f.selected], daily = f.current?.filters.resolution === 'day';
  const weekly = useWeeklyComparison(f.route, f.caps, !daily ? (point ?? null) : null);
  const onSelect = (i: number) => {f.setPlaying(false); f.setSelected(i);};
  const openForecast = () => {setChartMode('chart'); onOpenForecast();};
  return <section className={`forecast-card${compact ? ' forecast-card--compact' : ''}`} aria-label="Карточка прогноза"
    onTouchStart={e => {
      touchStart.current = compact && e.touches.length === 1 && !(e.target as HTMLElement).closest('button, input, select, a')
        ? {x:e.touches[0].clientX, y:e.touches[0].clientY, time:Date.now()} : null;
    }}
    onTouchMove={e => {if (e.touches.length !== 1) touchStart.current = null;}}
    onTouchCancel={() => {touchStart.current = null;}}
    onTouchEnd={e => {
      const start = touchStart.current, end = e.changedTouches[0]; touchStart.current = null;
      if (start && end && Date.now()-start.time < 800 && start.y-end.clientY > 48 && Math.abs(start.x-end.clientX) < 60) openForecast();
    }}>
    <div className="forecast-card__handle" aria-hidden="true"><span/></div>
    <div className="forecast-card__summary">
      <h1><span className="forecast-card__route-label">Маршрут </span><span className="forecast-card__route-number">№ </span>{f.route || 'не выбран'}</h1>
      <p className="forecast-card__interval">{point ? intervalLabel(point.start, point.end, !!daily) : 'Выберите интервал'}<span className="forecast-card__zone"> · МСК</span></p>
      <div className="forecast-card__value"><strong data-testid={point ? 'map-demand' : undefined} data-raw-value={point?.value ?? ''}>{format(point?.value ?? null)}</strong><span>посадок за {daily ? 'день' : 'час'}</span></div>
    </div>
    <ForecastMetrics />
    <ForecastNotices />
    <div className="forecast-card__quick-actions">
      <Button variant="primary" onClick={openForecast}>График</Button>
      <Button variant="ghost" onClick={onOpenScenario} aria-haspopup="dialog" disabled={!f.caps?.scenario_supported || !f.route || f.routeUnavailable}>Поправки{f.scenarioActive ? ' •' : ''}</Button>
    </div>
    <p className="forecast-card__swipe-hint">Проведите вверх: прогноз по {daily ? 'дням' : 'часам'}</p>
    <div className="forecast-card__visual">
      <div className="forecast-card__view-toggle" role="group" aria-label="Вид данных">
        <Button variant="ghost" aria-pressed={chartMode === 'chart'} onClick={() => setChartMode('chart')}>График</Button>
        <Button variant="ghost" aria-pressed={chartMode === 'table'} onClick={() => setChartMode('table')}>Таблица</Button>
      </div>
      {f.points.length ? chartMode === 'chart'
        ? <ForecastLineChart points={f.points} unit="успешные посадки" selectedIndex={f.selected} onSelectIndex={onSelect} />
        : <ForecastTable points={f.points} unit="успешные посадки" selectedIndex={f.selected} onSelectIndex={onSelect} />
        : <div className="chart-placeholder" aria-hidden="true"><span/><span/><span/></div>}
    </div>
    {weekly && <WeeklyComparisonCard {...weekly} />}
    <div className="forecast-card__timeline"><TimelinePanel /></div>
    <div className="forecast-card__actions">
      <Button variant="ghost" onClick={onOpenScenario} aria-haspopup="dialog" disabled={!f.caps?.scenario_supported || !f.route || f.routeUnavailable}>Поправки{f.scenarioActive ? ' •' : ''}</Button>
      <Button variant="primary" disabled={!f.current || f.busy || !!f.error || f.exporting} onClick={() => void f.download()} aria-label="Скачать CSV">{f.exporting ? 'Скачиваем…' : 'CSV ↓'}</Button>
    </div>
    <DispatchAction />
    {f.error && <Button onClick={f.retry} disabled={f.busy || f.exporting} aria-label={f.errorStatus === 410 ? 'Обновить доступные данные' : 'Повторить запрос'}>Повторить запрос</Button>}
    <p className="forecast-card__note">Прогноз по историческим данным</p>
  </section>;
}
