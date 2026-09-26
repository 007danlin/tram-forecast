import { useForecastData } from "../useForecast";

export function DataDetails() {
  const { current: result } = useForecastData();
  return (
    <div className="data-details">
      <p>
        CSV содержит показанный прогноз без округления. Это диспетчерский
        экспорт, не конкурсный submission. Успешные посадки не равны числу
        уникальных пассажиров или заполненности вагона.
      </p>
      <p>
        Карта и прогноз выбираются по номеру маршрута. Схема относится к 2026
        году; исторический прогноз — к периоду подключённого пакета. Состав
        остановок разных лет не сопоставлен: показанные остановки не имеют
        отдельных прогнозов. Направления, сценарные коэффициенты и годовой
        прогноз недоступны.
      </p>
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
