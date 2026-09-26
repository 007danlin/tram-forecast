import { useEffect, useRef } from "react";
import type { Network } from "../map/loadMap";
import { TramMap } from "./TramMap";
import { ForecastCard } from "./ForecastCard";
import { TimelinePanel } from "./TimelinePanel";
import { Button, Icon } from "./ui";
import "./Workspace.css";
export function Workspace({
  network,
  mapProblem,
  selectedRoute,
  onRouteChange,
  hidden,
  expanded,
  onExpandedChange,
  mobilePane,
  onOpenForecast,
  onOpenScenario,
}: {
  network: Network | null;
  mapProblem: string;
  selectedRoute: string;
  onRouteChange: (route: string) => void;
  hidden: boolean;
  expanded: boolean;
  onExpandedChange: (v: boolean) => void;
  mobilePane: "map" | "forecast";
  onOpenForecast: () => void;
  onOpenScenario: () => void;
}) {
  const expandTrigger = useRef<HTMLButtonElement>(null);
  const mapShell = useRef<HTMLDivElement>(null);
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
      className={`workspace workspace--mobile-${mobilePane}`}
      hidden={hidden}
    >
      <div className="workspace-card" inert={expanded}>
        <ForecastCard onOpenScenario={onOpenScenario} compact={mobilePane === 'map'} onOpenForecast={onOpenForecast} />
      </div>
      <div className="workspace-map-column">
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
            expanded ? "Закрыть увеличенную схему" : "Увеличить схему"
          }
          onClick={() => onExpandedChange(!expanded)}
        >
          <Icon name={expanded ? "close" : "expand"} />
          <span>{expanded ? "Закрыть схему" : "Увеличить схему"}</span>
        </Button>
        <TramMap
          map={network}
          mapProblem={mapProblem}
          selectedRoute={selectedRoute}
          onRouteChange={onRouteChange}
        />
      </div>
      <div className="workspace-timeline" inert={expanded}><TimelinePanel /></div>
      </div>
    </div>
  );
}
