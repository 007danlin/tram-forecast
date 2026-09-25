import { useState } from 'react';
import './ForecastCard.css';
import { ForecastLineChart, ForecastTable, type ForecastPoint } from './ForecastData';

type Tab = 'forecast' | 'segments' | 'about';

export function ForecastCard({
  points, unit, isMock, loading, error, onRetry, fetchedAt,
  selectedIndex, onSelectIndex, onClose,
}: {
  points: ForecastPoint[];
  unit: string;
  isMock: boolean;
  loading: boolean;
  error: string;
  onRetry: () => void;
  fetchedAt: Date | null;
  selectedIndex: number | null;
  onSelectIndex: (i: number) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>('forecast');
  const [chartMode, setChartMode] = useState<'chart' | 'table'>('chart');
  const hasData = points.length > 0;
  const maxPoint = hasData ? points.reduce((a, b) => (b.value > a.value ? b : a)) : null;

  return (
    <div
      className="forecast-card"
      role="dialog"
      aria-label="Карточка прогноза"
      onKeyDown={e => { if (e.key === 'Escape') onClose(); }}
    >
      <div className="forecast-card__head">
        <img className="forecast-card__head-icon" src="/tram-icon.png" alt="" aria-hidden="true" />
        <h2 className="forecast-card__head-title">Синтетический пример</h2>
        <button type="button" className="forecast-card__icon-btn" disabled title="Избранное недоступно: у демо-примера нет ID маршрута" aria-label="Добавить в избранное">☆</button>
        <button type="button" className="forecast-card__icon-btn" onClick={onClose} aria-label="Свернуть карточку">✕</button>
      </div>
      <div className="forecast-card__body">
        <p className="forecast-card__meta">
          Прогноз не привязан к маршруту или остановке.
          {hasData && <> Ряд: {points[0].timestamp.slice(0, 10)}, {points[0].timestamp.slice(11, 16)}–{points[points.length - 1].timestamp.slice(11, 16)} ({points[0].timestamp.slice(19)}).</>}
        </p>

        <dl className="forecast-card__stats">
          <div className="forecast-card__stat">
            <dt>Точек в ряду</dt>
            <dd>{hasData ? points.length : '—'}</dd>
          </div>
          <div className="forecast-card__stat">
            <dt>Единица</dt>
            <dd style={{ fontSize: 16 }}>{unit} <small>(условно)</small></dd>
          </div>
          <div className="forecast-card__stat">
            <dt>Максимум ряда</dt>
            <dd>{maxPoint ? maxPoint.value : '—'}{maxPoint && <small>в {maxPoint.timestamp.slice(11, 16)}</small>}</dd>
          </div>
          <div className="forecast-card__stat forecast-card__stat--empty">
            <dt>Сравнение с обычным уровнем</dt>
            <dd>Нет данных</dd>
          </div>
        </dl>

        <div className="forecast-card__tabs" role="tablist" aria-label="Разделы карточки">
          <button type="button" role="tab" className="forecast-card__tab" aria-selected={tab === 'forecast'} onClick={() => setTab('forecast')}>Прогноз</button>
          <button type="button" role="tab" className="forecast-card__tab" aria-selected={tab === 'segments'} onClick={() => setTab('segments')}>По участкам</button>
          <button type="button" role="tab" className="forecast-card__tab" aria-selected={tab === 'about'} onClick={() => setTab('about')}>О маршруте</button>
        </div>

        {tab === 'forecast' && <div role="tabpanel">
          {loading && <p className="forecast-card__empty">Загружаем тестовый ряд…</p>}
          {error && <p className="forecast-card__error" role="alert">{error}</p>}
          {!loading && !error && hasData && <>
            <div className="forecast-card__view-toggle" role="group" aria-label="Вид данных">
              <button type="button" className="forecast-card__view-btn" aria-pressed={chartMode === 'chart'} onClick={() => setChartMode('chart')}>График</button>
              <button type="button" className="forecast-card__view-btn" aria-pressed={chartMode === 'table'} onClick={() => setChartMode('table')}>Таблица</button>
            </div>
            {chartMode === 'chart'
              ? <ForecastLineChart points={points} unit={unit} selectedIndex={selectedIndex} onSelectIndex={onSelectIndex} />
              : <ForecastTable points={points} unit={unit} selectedIndex={selectedIndex} onSelectIndex={onSelectIndex} />}
          </>}
        </div>}

        {tab === 'segments' && <div role="tabpanel"><p className="forecast-card__empty">Прогноз по участкам пока недоступен.</p></div>}
        {tab === 'about' && <div role="tabpanel"><p className="forecast-card__empty">Справочник маршрутов не подключён: в текущей версии прогноз не привязан к конкретному маршруту.</p></div>}

        <div className="forecast-card__status">
          <p><strong>{isMock ? 'Тестовые данные' : 'Данные'}</strong> — не реальный прогноз.</p>
          {fetchedAt && <p>Ответ получен: {fetchedAt.toLocaleTimeString('ru-RU')}</p>}
          <details>
            <summary>Факторы и ограничения</summary>
            <ul>
              <li>Источник: тестовая ML-заглушка (predict_mock), реальные данные не использованы.</li>
              <li>Нет привязки к маршруту, остановке или направлению.</li>
              <li>Нет сравнения с обычным уровнем и интервалов неопределённости.</li>
              <li>Фильтры и часовые горизонты недоступны — нет подключения к API v2.</li>
            </ul>
          </details>
        </div>
      </div>

      <div className="forecast-card__actions">
        <button type="button" className="forecast-card__action forecast-card__action--primary" onClick={onRetry} disabled={loading}>Обновить</button>
        <button type="button" className="forecast-card__action" disabled title="После согласованного backend-экспорта">CSV</button>
        <button type="button" className="forecast-card__action" disabled title="После согласования коэффициентов сценария">Сценарий</button>
      </div>
    </div>
  );
}
