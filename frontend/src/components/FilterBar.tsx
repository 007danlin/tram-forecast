import { useEffect, useRef, useState } from "react";
import { useForecastData } from "../useForecast";
import { Button, Icon } from "./ui";
import "./FilterBar.css";
export function FilterBar() {
  const forecast = useForecastData();
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
          disabled={!forecast.caps}
          value={forecast.route}
          onChange={(e) => forecast.changeRoute(e.target.value)}
        >
          {!forecast.caps && <option value="">Маршрут</option>}
          {forecast.caps?.routes.map((route) => (
            <option key={route.route_id} value={route.route_id}>
              № {route.route_id}
              {route.method === "baseline" ? " · baseline" : ""}
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
