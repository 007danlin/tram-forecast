import { useForecastData } from "../useForecast";

export function DataDetails() {
  const { current: result } = useForecastData();
  return (
    <div className="data-details">
      <p>Посадка — успешная валидация билета. Это не число уникальных пассажиров и не заполненность вагона.</p>
      <p>Схема: 2026. Прогноз: {result?.filters.start.slice(0, 4) || 'год выбранной даты'}, по номеру маршрута. Данных по остановкам и направлениям нет.</p>
      <p>Сценарий: база × погода × событие. Поправки задаются вручную; интервал неопределённости не рассчитан.</p>
      <p>CSV: выбранный маршрут, период и слой, без округления. Конкурсный файл готовится отдельно.</p>
      {result && (
        <>
          <dl>
            <div>
              <dt>Run</dt>
              <dd>
                <code data-testid="run">{result.forecast_run_id}</code>
              </dd>
            </div>
            <div>
              <dt>Модель</dt>
              <dd>
                <code>{result.model_version}</code>
              </dd>
            </div>
            <div>
              <dt>CSV SHA-256</dt>
              <dd>
                <code>{result.csv_sha256}</code>
              </dd>
            </div>
            <div>
              <dt>Пакет импортирован</dt>
              <dd>{result.imported_at}</dd>
            </div>
            <div>
              <dt>Метод интервала</dt>
              <dd>{result.interval_method}</dd>
            </div>
          </dl>
          <p>
            Импорт — не время обучения. Номинальная граница интервала не
            гарантирует покрытие; дневные границы не равны сумме почасовых.
          </p>
          <ul>
            {[...new Set([...result.warnings, ...result.limitations])].map(
              (w) => (
                <li key={w}>{w}</li>
              ),
            )}
          </ul>
        </>
      )}
    </div>
  );
}
