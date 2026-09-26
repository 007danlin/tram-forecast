import { useEffect, useRef, useState } from 'react';
import { AppHeader, type ViewName } from './components/AppHeader';
import { FilterBar } from './components/FilterBar';
import { Workspace } from './components/Workspace';
import { AnalyticsView } from './components/AnalyticsView';
import { SettingsPanel } from './components/SettingsPanel';
import { ScenarioPanel } from './components/ScenarioPanel';
import { Dialog } from './components/Dialog';
import { RouteOverview, YearView } from './components/DispatchTools';
import { ForecastContext, useForecast } from './useForecast';
import { useNetwork } from './map/useNetwork';
import { useTheme } from './theme/useTheme';
import { OVERVIEW } from './handoff';

export function App() {
  const forecast = useForecast();
  const { network, problem: mapProblem } = useNetwork();
  const { theme, changeTheme } = useTheme();
  const [view, setView] = useState<'map' | 'analytics'>('map');
  const [mobilePane, setMobilePane] = useState<'map' | 'forecast'>('map');
  const [panel, setPanel] = useState<'data' | 'scenario' | 'year' | null>(null);
  const [mapExpanded, setMapExpanded] = useState(false);
  const previousRoute = useRef<string | null>(null);
  useEffect(() => {if (!forecast.overview) previousRoute.current = forecast.route;}, [forecast.route, forecast.overview]);
  const activeView: ViewName = forecast.overview ? 'routes' : view;
  function changeView(next: ViewName) {
    forecast.setPlaying(false);
    if (next === 'routes') {
      if (!forecast.overview) previousRoute.current = forecast.route;
      setView('map');
      forecast.changeRoute(OVERVIEW);
    } else {
      if (forecast.overview) forecast.changeRoute(previousRoute.current ?? forecast.caps?.routes[0]?.route_id ?? '');
      setView(next);
    }
  }
  function openPanel(next: 'data' | 'scenario' | 'year') {
    forecast.setPlaying(false);
    setPanel(next);
  }
  return <ForecastContext.Provider value={forecast}>
    <div className="app-shell">
      <div inert={mapExpanded}>
        <AppHeader view={activeView} onViewChange={changeView} onOpenSettings={() => openPanel('data')} onOpenYear={() => openPanel('year')} yearAvailable={!!forecast.caps?.year?.qualitative_available} theme={theme} onThemeChange={changeTheme} />
        <FilterBar network={network} onOpenScenario={() => openPanel('scenario')} onOpenYear={() => openPanel('year')} />
      </div>
      <main className="app-shell__body">
        <Workspace network={network} mapProblem={mapProblem} selectedRoute={forecast.overview ? '' : forecast.route}
          onRouteChange={forecast.changeRoute} hidden={activeView !== 'map'} expanded={mapExpanded} onExpandedChange={setMapExpanded}
          mobilePane={mobilePane} onOpenForecast={() => setMobilePane('forecast')} onOpenScenario={() => openPanel('scenario')} />
        {activeView === 'analytics' && <AnalyticsView />}
        {activeView === 'routes' && <RouteOverview onOpenScenario={() => openPanel('scenario')} onSelectRoute={route => {setView('map'); setMobilePane('forecast'); forecast.changeRoute(route);}} />}
      </main>
      <nav className="mobile-navigation" aria-label="Основные экраны" inert={mapExpanded}>
        <button aria-current={activeView === 'map' && mobilePane === 'map' ? 'page' : undefined} onClick={() => {changeView('map'); setMobilePane('map');}}>Карта</button>
        <button aria-current={activeView !== 'routes' && (activeView === 'analytics' || mobilePane === 'forecast') ? 'page' : undefined} onClick={() => {changeView('map'); setMobilePane('forecast');}}>Прогноз</button>
      </nav>
      {panel === 'data' && <SettingsPanel onClose={() => setPanel(null)} />}
      {panel === 'scenario' && <Dialog title="Ручные поправки" onClose={() => setPanel(null)}><ScenarioPanel onClose={() => setPanel(null)} /></Dialog>}
      {panel === 'year' && <Dialog title="На год: допущения" onClose={() => setPanel(null)}><YearView /></Dialog>}
    </div>
  </ForecastContext.Provider>;
}
