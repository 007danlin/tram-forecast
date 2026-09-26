import { useState } from 'react';
import { ForecastLineChart, ForecastTable } from './ForecastData';
import { ForecastMetrics, ForecastNotices } from './ForecastSummary';
import { TimelinePanel } from './TimelinePanel';
import { useForecastData } from '../useForecast';
import { Button } from './ui';
import './AnalyticsView.css';
export function AnalyticsView() {
  const f = useForecastData();
  const [pane, setPane] = useState<'chart' | 'table'>('chart');
  const onSelect = (i: number) => {f.setPlaying(false); f.setSelected(i);};
  return <section className="analytics-view" aria-labelledby="analytics-title">
    <div className="analytics-heading"><h1 id="analytics-title">Прогноз маршрута {f.route || 'не выбран'}</h1><div>
      <Button disabled={!f.current || f.busy || !!f.error || f.exporting} onClick={() => void f.download()} aria-label="Скачать CSV">{f.exporting ? 'Скачиваем…' : 'CSV ↓'}</Button>
    </div></div>
    <ForecastMetrics includeSelected />
    <ForecastNotices />
    {f.error && <Button onClick={f.retry}>Повторить запрос</Button>}
    <div className="analytics-toggle" role="group" aria-label="Вид аналитики"><Button aria-pressed={pane === 'chart'} onClick={() => setPane('chart')}>График</Button><Button aria-pressed={pane === 'table'} onClick={() => setPane('table')}>Таблица</Button></div>
    <div className={`analytics-panels analytics-panels--${pane}`}>
      <div className="analytics-view__panel analytics-chart"><h2>Посадки по {f.horizon === 'day' ? 'часам' : 'дням'}</h2>
        {f.points.length ? <ForecastLineChart points={f.points} unit="успешные посадки" selectedIndex={f.selected} onSelectIndex={onSelect} /> : <div className="analytics-empty">{f.busy ? 'Загружаем…' : 'Нет данных для графика'}</div>}
        <TimelinePanel />
      </div>
      <div className="analytics-view__panel analytics-table"><h2>Значения</h2><ForecastTable points={f.points} unit="успешные посадки" selectedIndex={f.selected} onSelectIndex={onSelect} /></div>
    </div>
  </section>;
}
