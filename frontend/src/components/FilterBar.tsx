import { useEffect, useMemo, useRef, useState } from "react";
import type { Network } from "../map/loadMap";
import { groupRouteLanes } from "../map/routeSelection";
import { useForecastData } from "../useForecast";
import { Button, Icon } from "./ui";
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
  const [moreOpen, setMoreOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!moreOpen) return;
    const close = (e: PointerEvent) => {
      if (
        !popoverRef.current?.contains(e.target as Node) &&
        !trigger.current?.contains(e.target as Node)
      )
        setMoreOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [moreOpen]);
  return (
    <div
      className="filter-bar"
      role="search"
      aria-label="Фильтры прогноза"
      onKeyDown={(e) => {
        if (e.key === "Escape" && moreOpen) {
          setMoreOpen(false);
          trigger.current?.focus();
        }
      }}
    >
      <label className="filter-field route-field">
        <span className="sr-only">Маршрут</span>
        <select
          aria-label="Маршрут"
          disabled={!options.length}
          value={forecast.route}
          onChange={(e) => forecast.changeRoute(e.target.value)}
        >
          <option value="">Все маршруты</option>
          {options.map((route) => (
            <option
              key={route.value}
              value={route.value}
              data-forecast={route.forecast}
            >
              № {route.label}
              {route.method === "baseline" ? " · baseline" : ""}
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
      <button
        ref={trigger}
        type="button"
        className="button more-filters"
        aria-expanded={moreOpen}
        aria-controls="extra-filters"
        onClick={() => setMoreOpen((v) => !v)}
      >
        <span>Ещё</span>
        <span className="more-period">
          {forecast.horizon === "day"
            ? "День"
            : forecast.horizon === "week"
              ? "Неделя"
              : "Месяц"}
        </span>
        <Icon name="chevron" />
      </button>
      <div
        ref={popoverRef}
        id="extra-filters"
        className={`filter-extras${moreOpen ? " is-open" : ""}`}
      >
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
            ] as const
          ).map(([value, label, accessible]) => (
            <Button
              key={value}
              variant={forecast.horizon === value ? "primary" : "neutral"}
              aria-label={accessible}
              aria-pressed={forecast.horizon === value}
              disabled={
                !forecast.caps?.resolutions.includes(
                  value === "day" ? "hour" : "day",
                )
              }
              onClick={() => forecast.changeHorizon(value)}
            >
              {label}
            </Button>
          ))}
        </div>
        <Button
          variant="ghost"
          className="reset-filters"
          disabled={!forecast.caps}
          onClick={forecast.reset}
        >
          Сбросить
        </Button>
      </div>
      <div className="filter-status">
        <span>
          Исторический прогноз{" "}
          <span className="mobile-period">
            ·{" "}
            {forecast.horizon === "day"
              ? "День"
              : forecast.horizon === "week"
                ? "Неделя"
                : "Месяц"}
          </span>
        </span>
        <span
          className={`connection-status app-shell__badge--${forecast.connection}`}
          role="status"
        >
          {forecast.connection === "checking"
            ? "Проверяем пакет…"
            : forecast.connection === "ok"
              ? "Пакет подключён"
              : "Пакет недоступен"}
        </span>
      </div>
    </div>
  );
}
