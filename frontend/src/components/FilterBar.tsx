import { useMemo } from "react";
import type { Network } from "../map/loadMap";
import { groupRouteLanes } from "../map/routeSelection";
import { useForecastData } from "../useForecast";
import { Button } from "./ui";
import { OVERVIEW } from "../handoff";
import "./FilterBar.css";
export function FilterBar({ network }: { network: Network | null }) {
  const forecast = useForecastData();
  const options = useMemo(() => {
    const routes = new Map(
      groupRouteLanes(network?.lanes ?? []).map((group) => [
        group.routes[0],
        {
          value: group.routes[0],
          label: group.routes.join(" / "),
          method: "",
          forecast: false,
        },
      ]),
    );
    for (const route of forecast.caps?.routes ?? []) {
      const existing = routes.get(route.route_id);
      routes.set(route.route_id, {
        value: route.route_id,
        label: existing?.label ?? route.route_id,
        method: route.method,
        forecast: true,
      });
    }
    return [...routes.values()].sort((a, b) =>
      a.value.localeCompare(b.value, "ru", { numeric: true }),
    );
  }, [network, forecast.caps]);
  return (
    <div
      className="filter-bar"
      role="search"
      aria-label="Фильтры прогноза"
    >
      <label className="filter-field route-field">
        <span className="sr-only">Маршрут</span>
        <select
          aria-label="Маршрут"
          disabled={!options.length}
          value={forecast.route}
          onChange={(e) => forecast.changeRoute(e.target.value)}
        >
          <option value="">Снять выбор</option>
          {forecast.caps && <option value={OVERVIEW}>Обзор маршрутов</option>}
          {options.map((route) => (
            <option
              key={route.value}
              value={route.value}
              data-forecast={route.forecast}
            >
              № {route.label}
              {route.method === "baseline" ? " · нет истории" : ""}
              {forecast.caps && !route.forecast ? " · только схема" : ""}
            </option>
          ))}
        </select>
      </label>
      <label className="filter-field date-field">
        <span className="sr-only">Дата (МСК)</span>
        <input
          aria-label="Дата (МСК)"
          type="date"
          disabled={!forecast.caps}
          value={forecast.day}
          min={forecast.caps?.start.slice(0, 10)}
          max={forecast.lastDay}
          onChange={(e) => forecast.changeDay(e.target.value)}
        />
      </label>
      <div className="filter-extras">
        <div
          className="filter-bar__horizon"
          role="group"
          aria-label="Период прогноза"
        >
          {(
            [
              ["day", "День", "1 день"],
              ["week", "Неделя", "1 нед"],
              ["month", "Месяц", "1 мес"],
              ["year", "Год", "Год"],
            ] as const
          ).map(([value, label, accessible]) => (
            <Button
              key={value}
              variant={forecast.horizon === value ? "primary" : "neutral"}
              aria-label={accessible}
              aria-pressed={forecast.horizon === value}
              disabled={
                value === "year" ? !forecast.caps?.year?.qualitative_available : !forecast.caps?.resolutions.includes(
                  value === "day" ? "hour" : "day",
                )
              }
              onClick={() => forecast.changeHorizon(value)}
            >
              {label}
            </Button>
          ))}
        </div>
      </div>
      <span className={`filter-status app-shell__badge--${forecast.connection}${forecast.connection === 'ok' ? ' sr-only' : ''}`}  role="status">{forecast.connection === 'checking' ? 'Загружаем данные…' : forecast.connection === 'ok' ? 'Данные загружены' : 'Данные недоступны'}</span>
    </div>
  );
}
