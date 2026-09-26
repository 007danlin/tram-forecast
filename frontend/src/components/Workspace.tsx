import { useEffect, useRef, useState } from "react";
import type { Network } from "../map/loadMap";
import { TramMap } from "./TramMap";
import { ForecastCard } from "./ForecastCard";
import { FilterBar } from "./FilterBar";
import { Button, Icon } from "./ui";
import { useForecastData } from "../useForecast";
import "./Workspace.css";
export function Workspace({
  network,
  mapProblem,
  selectedRoute,
  onRouteChange,
  hidden,
  expanded,
  onExpandedChange,
}: {
  network: Network | null;
  mapProblem: string;
  selectedRoute: string;
  onRouteChange: (route: string) => void;
  hidden: boolean;
  expanded: boolean;
  onExpandedChange: (v: boolean) => void;
}) {
  const forecast = useForecastData();
  const [cardOpen, setCardOpen] = useState(true);
  const reopen = useRef<HTMLButtonElement>(null);
  const expandTrigger = useRef<HTMLButtonElement>(null);
  const mapShell = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (forecast.overview || forecast.horizon === 'year') setCardOpen(true);
  }, [forecast.overview, forecast.horizon]);
  useEffect(() => {
    if (!cardOpen) reopen.current?.focus();
  }, [cardOpen]);
  useEffect(() => {
    if (!expanded) return;
    const prior = document.activeElement as HTMLElement;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    mapShell.current?.querySelector<HTMLButtonElement>(".map-expand")?.focus();
    return () => {
      document.body.style.overflow = oldOverflow;
      prior?.focus();
    };
  }, [expanded]);
  return (
    <div
      className={`workspace${!cardOpen ? " workspace--map-only" : ""}${forecast.overview || forecast.horizon === 'year' ? ' workspace--text-mode' : ''}`}
      hidden={hidden}
    >
      <div className="workspace-card" inert={expanded}>
        {cardOpen ? (
          <>
            {!hidden && <FilterBar network={network} />}
            <ForecastCard onClose={() => setCardOpen(false)} />
          </>
        ) : (
          <button
            ref={reopen}
            className="button forecast-card-reopen"
            onClick={() => setCardOpen(true)}
          >
            Открыть прогноз
          </button>
        )}
      </div>
      <div
        ref={mapShell}
        className={`map-shell${expanded ? " map-shell--expanded" : ""}`}
        role={expanded ? "dialog" : undefined}
        aria-modal={expanded ? true : undefined}
        aria-label={expanded ? "Увеличенная схема" : undefined}
        onKeyDown={(e) => {
          if (!expanded) return;
          if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            onExpandedChange(false);
            requestAnimationFrame(() => expandTrigger.current?.focus());
          }
          if (e.key === "Tab") {
            const els = Array.from(
              mapShell.current?.querySelectorAll<HTMLElement>(
                'button:not(:disabled),select,[tabindex="0"]',
              ) ?? [],
            ).filter((el) => el.getClientRects().length);
            const first = els[0],
              last = els[els.length - 1];
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last?.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <Button
          className="map-expand"
          ref={expandTrigger}
          aria-label={
            expanded ? "Закрыть увеличенную схему" : "Увеличить сайт"
          }
          onClick={() => onExpandedChange(!expanded)}
        >
          <Icon name={expanded ? "close" : "expand"} />
          <span>{expanded ? "Закрыть схему" : "Увеличить сайт"}</span>
        </Button>
        <TramMap
          map={network}
          mapProblem={mapProblem}
          selectedRoute={selectedRoute}
          onRouteChange={onRouteChange}
        />
      </div>
    </div>
  );
}
