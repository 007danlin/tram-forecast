import { useState } from 'react';
import './ForecastCard.css';
import { format, useForecastData } from '../useForecast';
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
  const forecast = useForecastData();
  const result = forecast.current;
  const [tab, setTab] = useState<Tab>('forecast');
  const [chartMode, setChartMode] = useState<'chart' | 'table'>('chart');
  const hasData = points.length > 0;
  const maxPoint = hasData ? points.reduce((a, b) => ((b.value ?? -Infinity) > (a.value ?? -Infinity) ? b : a)) : null;

  return (
    <div
      className="forecast-card"
      role="dialog"
      aria-label="Карточка прогноза" tabIndex={-1}
      onKeyDown={e => { if (e.key === 'Escape') onClose(); }}
    >
      <div className="forecast-card__head">
        <img className="forecast-card__head-icon" src="/tram-icon.png" alt="" aria-hidden="true" />
        <h2 className="forecast-card__head-title">{forecast.route ? `Маршрут № ${forecast.route}` : 'Прогноз успешных посадок'}</h2>
        <button type="button" className="forecast-card__icon-btn" disabled title="Избранное пока недоступно" aria-label="Добавить в избранное">☆</button>
        <button type="button" className="forecast-card__icon-btn" onClick={onClose} aria-label="Свернуть карточку">✕</button>
      </div>
      <div className="forecast-card__body">
        <p className="forecast-card__meta">
          Исторический ML-прогноз, время МСК. Линии схемы не связаны с выбранным маршрутом прогноза.
          {hasData && <> Ряд: {points[0].timestamp.slice(0, 16).replace('T', ' ')} — {points[points.length - 1].timestamp.slice(0, 16).replace('T', ' ')} ({points[0].timestamp.slice(19)}), шаг {result?.filters.resolution === 'day' ? 'сутки' : 'час'}.</>}
        </p>

        <dl className="forecast-card__stats">
          <div className="forecast-card__stat">
            <dt>{result?.total_scope === 'available_only' ? 'Сумма доступных значений' : result?.total_scope === 'no_data' ? 'Нет данных за период' : 'Всего успешных посадок'}</dt>
            {result ? <dd data-testid="total" data-raw-value={result.total ?? ''}>{format(result.total)}</dd> : <dd>—</dd>}
          </div>
          <div className="forecast-card__stat">
            <dt>Единица</dt>
            <dd style={{ fontSize: 16 }}>{unit}</dd>
          </div>
          <div className="forecast-card__stat">
            <dt>Максимум ряда</dt>
            <dd>{maxPoint ? format(maxPoint.value) : '—'}{maxPoint?.value != null && <small>{result?.filters.resolution === 'day' ? maxPoint.timestamp.slice(0, 10) : `в ${maxPoint.timestamp.slice(11, 16)}`}</small>}</dd>
          </div>
          <div className="forecast-card__stat forecast-card__stat--empty">
            <dt>Сравнение с обычным уровнем</dt>
            <dd>Нет данных</dd>
          </div>
        </dl>

        {error && <p className="forecast-card__error" role="alert">{error}</p>}
        <div className="forecast-card__tabs" role="tablist" aria-label="Разделы карточки">
          <button type="button" role="tab" className="forecast-card__tab" aria-selected={tab === 'forecast'} onClick={() => setTab('forecast')}>Прогноз</button>
          <button type="button" role="tab" className="forecast-card__tab" aria-selected={tab === 'segments'} onClick={() => setTab('segments')}>По участкам</button>
          <button type="button" role="tab" className="forecast-card__tab" aria-selected={tab === 'about'} onClick={() => setTab('about')}>О маршруте</button>
        </div>

        {tab === 'forecast' && <div role="tabpanel">
          {loading && <p className="forecast-card__empty">Загружаем прогноз…</p>}
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
        {tab === 'about' && <div role="tabpanel"><p className="forecast-card__empty">Маршрут и период прогноза получены из ML-пакета. Остановки и направления не поддержаны; линии карты не связаны с селектором.</p></div>}

        <div className="forecast-card__status">
          <p role="status">{result ? `Покрытие: ${format(result.coverage * 100)}%` : 'Прогноз не получен'}</p>
          {forecast.caps?.routes.find(r => r.route_id === forecast.route)?.method === 'baseline' && <p>Нулевой baseline: нет успешной истории обучения. Это не означает отсутствия движения.</p>}
          {result?.total_scope === 'available_only' && <p>Неполное покрытие (partial): пропуски не заменены нулями.</p>}
          {result?.total_scope === 'no_data' && <p>Нет данных (no_data): выберите другой период.</p>}
          <details>
            <summary>Факторы и ограничения</summary>
            <p>CSV содержит показанный прогноз без округления. Это диспетчерский экспорт, не конкурсный submission. Посадки не равны заполненности вагона.</p>
            {result && <>
              <p>Run: <code data-testid="run">{result.forecast_run_id}</code></p>
              <p>Модель: <code>{result.model_version}</code></p><p>CSV SHA-256: <code>{result.csv_sha256}</code></p>
              <p>Импорт пакета: {result.imported_at} (не время обучения).</p>
              <p>Интервал: {result.interval_method}; номинальная граница не гарантирует покрытие. Дневные границы не равны сумме почасовых.</p>
              <ul>{[...new Set([...result.warnings,...result.limitations])].map(w => <li key={w}>{w}</li>)}</ul>
            </>}
          </details>
        </div>
      </div>

      <div className="forecast-card__actions">
        <button type="button" className="forecast-card__action forecast-card__action--primary" onClick={onRetry} disabled={loading || forecast.exporting} aria-label={forecast.errorStatus === 410 ? 'Обновить доступные данные' : error ? 'Повторить запрос' : 'Обновить прогноз'}>Обновить</button>
        <button type="button" className="forecast-card__action" disabled={!result || loading || !!error || forecast.exporting} onClick={() => void forecast.download()} aria-label="Скачать CSV">{forecast.exporting ? '…' : 'CSV'}</button>
        <button type="button" className="forecast-card__action" disabled title="После согласования коэффициентов сценария">Сценарий</button>
      </div>
    </div>
  );
}
