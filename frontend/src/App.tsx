import { useRef, useState } from "react";
import { AppHeader, type ViewName } from "./components/AppHeader";
import { FilterBar } from "./components/FilterBar";
import { Workspace } from "./components/Workspace";
import { AnalyticsView } from "./components/AnalyticsView";
import { SettingsPanel } from "./components/SettingsPanel";
import { ForecastContext, useForecast } from "./useForecast";
import { useNetwork } from "./map/useNetwork";
import { useTheme } from "./theme/useTheme";

export function App() {
  const forecast = useForecast();
  const { network, problem: mapProblem } = useNetwork();
  const { theme, changeTheme } = useTheme();
  const [view, setView] = useState<ViewName>("map");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mapExpanded, setMapExpanded] = useState(false);
  const settingsTriggerRef = useRef<HTMLButtonElement | null>(null);
  return (
    <ForecastContext.Provider value={forecast}>
      <div className="app-shell">
        <div inert={mapExpanded || settingsOpen}>
          <AppHeader
            view={view}
            onViewChange={setView}
            settingsOpen={settingsOpen}
            onOpenSettings={() => setSettingsOpen(true)}
            settingsButtonRef={settingsTriggerRef}
            theme={theme}
            onThemeChange={changeTheme}
          />
          <FilterBar network={network} />
        </div>
        <main className="app-shell__body" inert={settingsOpen}>
          <Workspace
            network={network}
            mapProblem={mapProblem}
            selectedRoute={forecast.overview ? '' : forecast.route}
            onRouteChange={forecast.changeRoute}
            hidden={view !== "map"}
            expanded={mapExpanded}
            onExpandedChange={setMapExpanded}
          />
          {view === "analytics" && <AnalyticsView />}
        </main>
        {settingsOpen && (
          <SettingsPanel
            onClose={() => {
              setSettingsOpen(false);
              requestAnimationFrame(() => {
                const trigger = settingsTriggerRef.current;
                if (trigger?.getClientRects().length) trigger.focus();
                else
                  document
                    .querySelector<HTMLButtonElement>(".nav-toggle")
                    ?.focus();
              });
            }}
          />
        )}
      </div>
    </ForecastContext.Provider>
  );
}
