import { useForecastData } from "../useForecast";

export function DataDetails() {
  const { current: result } = useForecastData();
  return (
    <div className="data-details">
      <p>
        Посадка — успешная валидация билета. Это не число уникальных пассажиров
        и не заполненность вагона.
      </p>
      <p>
        Карта — схема 2026 года. Доступные маршруты и даты прогноза зависят от
        загруженных данных; связь со схемой — по номеру маршрута. Прогнозов по
        остановкам и направлениям нет.
      </p>
      <p>
        Погода и события в сценариях — ручные поправки к прогнозу. Годовой
        сценарий описывает условия без чисел.
      </p>
      <p>
        CSV содержит показанный прогноз без округления. Конкурсный файл
        формируется отдельно.
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
