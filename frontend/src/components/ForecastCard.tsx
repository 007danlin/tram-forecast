import { useState } from "react";
import { format, useForecastData } from "../useForecast";
import { dateLabel, intervalLabel } from "../display";
import { ForecastLineChart, ForecastTable } from "./ForecastData";
import { DataDetails } from "./DataDetails";
import { Button, Icon } from "./ui";
import { YearView, RouteOverview } from "./DispatchTools";
import "./ForecastCard.css";

export function ForecastCard({ onClose }: { onClose: () => void }) {
  const forecast = useForecastData();
  const { current: result, points, busy, error } = forecast;
  const [chartMode, setChartMode] = useState<"chart" | "table">("chart");
  const [expanded, setExpanded] = useState(false);
  const valid = points.filter((p) => p.value !== null);
  const maximum = valid.length ? Math.max(...valid.map((p) => p.value!)) : null;
  const peaks = valid.filter((p) => p.value === maximum);
  const peak = peaks[0];
  const daily = result?.filters.resolution === "day";
  const onSelect = (i: number) => {
    forecast.setPlaying(false);
    forecast.setSelected(i);
  };
  const end = result?.filters.end
    ? new Date(Date.parse(result.filters.end) - 1).toISOString().slice(0, 10)
    : "";
  if (forecast.horizon === 'year') return <YearView />;
  if (forecast.overview) return <RouteOverview />;
  return (
    <section
      className="forecast-card"
      aria-label="Карточка прогноза"
      tabIndex={-1}
      data-expanded={expanded}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div className="forecast-card__summary">
        <div className="forecast-card__head">
          <h1>{forecast.route ? `Маршрут ${forecast.route}` : "Прогноз"}</h1>
          <p className="forecast-card__date">
            {result && daily
              ? `${dateLabel(result.filters.start, true)} — ${dateLabel(end, true)}`
              : dateLabel(forecast.day, true)}
          </p>
        </div>
        <p className="forecast-card__meta">Исторический прогноз · МСК · Базовая модель</p>
        <div className="forecast-card__total">
          {result ? (
            <strong data-testid="total" data-raw-value={forecast.displayTotal ?? ""}>
              {format(forecast.displayTotal)}
            </strong>
          ) : (
            <strong className={busy ? "is-loading" : ""}>—</strong>
          )}
          <span>
            {result?.total_scope === "available_only"
              ? "Сумма доступных значений"
              : result?.total_scope === "no_data"
                ? "Нет данных за период"
                : `успешных посадок ${forecast.horizon === "day" ? "за день" : "за период"}`}
          </span>
        </div>
        <dl className="forecast-card__stats">
          <div>
            <dt>
              {peaks.length > 1
                ? "Первый максимум"
                : daily
                  ? "Пиковый день"
                  : "Пиковый час"}
            </dt>
            <dd>{peak ? intervalLabel(peak.start, peak.end, !!daily) : "—"}</dd>
          </div>
          <div>
            <dt>Покрытие</dt>
            <dd>{result ? `${format(result.coverage * 100)}%` : "—"}</dd>
          </div>
        </dl>
        {busy && (
          <p className="forecast-message" role="status">
            Загружаем прогноз…
          </p>
        )}
        {forecast.emptyReason && (
          <p className="forecast-message" role="status">
            {forecast.emptyReason}
          </p>
        )}
        {error && (
          <p className="forecast-message forecast-message--error" role="alert">
            {error}
          </p>
        )}
        {forecast.caps?.routes.find((r) => r.route_id === forecast.route)
          ?.method === "baseline" && (
          <p className="forecast-message">
            Нулевой baseline: нет успешной истории обучения. Это не означает
            отсутствия движения.
          </p>
        )}
        {result?.total_scope === "available_only" && (
          <p className="forecast-message" role="status">
            Неполное покрытие (partial): пропуски не заменены нулями.
          </p>
        )}
        {result?.total_scope === "no_data" && (
          <p className="forecast-message" role="status">
            Нет данных (no_data): выберите другой период.
          </p>
        )}
      </div>
      <div className="forecast-card__visual" id="forecast-visual">
        <div
          className="forecast-card__view-toggle"
          role="group"
          aria-label="Вид данных"
        >
          <Button
            variant="ghost"
            aria-pressed={chartMode === "chart"}
            onClick={() => setChartMode("chart")}
          >
            График
          </Button>
          <Button
            variant="ghost"
            aria-pressed={chartMode === "table"}
            onClick={() => setChartMode("table")}
          >
            Таблица
          </Button>
        </div>
        {!!points.length &&
          (chartMode === "chart" ? (
            <ForecastLineChart
              points={points}
              unit="успешные посадки"
              selectedIndex={forecast.selected}
              onSelectIndex={onSelect}
            />
          ) : (
            <ForecastTable
              points={points}
              unit="успешные посадки"
              selectedIndex={forecast.selected}
              onSelectIndex={onSelect}
            />
          ))}
        {!points.length && (
          <div className="chart-placeholder" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        )}
      </div>
      <div className="forecast-card__actions">
        <Button
          variant="primary"
          disabled={!result || busy || !!error || forecast.exporting}
          onClick={() => void forecast.download()}
          aria-label="Скачать CSV"
        >
          {forecast.exporting ? "Скачиваем…" : "Скачать CSV"}
        </Button>
        <Button
          variant="ghost"
          onClick={forecast.retry}
          disabled={busy || forecast.exporting || !!forecast.emptyReason}
          aria-label={
            forecast.errorStatus === 410
              ? "Обновить доступные данные"
              : error
                ? "Повторить запрос"
                : "Обновить прогноз"
          }
        >
          {error ? "Повторить" : "Обновить"}
        </Button>
      </div>
      <Button
        variant="ghost"
        className="forecast-card__expand"
        aria-expanded={expanded}
        aria-controls="forecast-visual forecast-details"
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? "Свернуть подробности" : "График, таблица и сведения"}
        <Icon name="chevron" />
      </Button>
      <div className="forecast-card__footer">
        <details id="forecast-details" className="forecast-card__details">
          <summary>Данные и ограничения</summary>
          <DataDetails />
        </details>
        <button
          className="card-close"
          onClick={onClose}
          aria-label="Свернуть карточку"
        >
          <Icon name="close" />
        </button>
      </div>
    </section>
  );
}
