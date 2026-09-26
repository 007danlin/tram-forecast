import { useEffect, useRef, useState } from 'react';
import { AppHeader, type ConnectionStatus, type ViewName } from './components/AppHeader';
import { FilterBar } from './components/FilterBar';
import { Workspace } from './components/Workspace';
import { AnalyticsView } from './components/AnalyticsView';
import { SettingsPanel } from './components/SettingsPanel';
import { ForecastContext, useForecast } from './useForecast';

export function App() {
  const forecast = useForecast();
  const {points, busy: loading, error, selected: selectedIndex, setSelected: setSelectedIndex, playing, setPlaying} = forecast;
  const [view, setView] = useState<ViewName>('map');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [cardOpen, setCardOpen] = useState(true);

  const reopenRef = useRef<HTMLButtonElement>(null);
  const settingsTriggerRef = useRef<HTMLButtonElement | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const filterBarRef = useRef<HTMLDivElement>(null);

  const connection: ConnectionStatus = forecast.current ? 'ok' : error ? 'error' : 'checking';

  useEffect(() => {
    if (!cardOpen) reopenRef.current?.focus();
  }, [cardOpen]);

  useEffect(() => {
    const filterBar = filterBarRef.current;
    const body = bodyRef.current;
    if (!filterBar || !body) return;
    const measure = () => body.style.setProperty('--filters-height', `${filterBar.offsetHeight}px`);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(filterBar);
    return () => ro.disconnect();
  }, []);

  const retry = forecast.retry;

  return (
    <ForecastContext.Provider value={forecast}><div className="app-shell">
      <AppHeader
        view={view}
        onViewChange={setView}
        settingsOpen={settingsOpen}
        onOpenSettings={() => setSettingsOpen(o => !o)}
        settingsButtonRef={settingsTriggerRef}
        connection={connection}
      />
      <div className="app-shell__body" ref={bodyRef}>
        <FilterBar
          ref={filterBarRef}
          overlay={view === 'map'}
          dataDateLabel={forecast.day}
        />
        <Workspace
          hidden={view !== 'map'}
          points={points} unit="успешные посадки" isMock={false}
          loading={loading} error={error} onRetry={retry} fetchedAt={null}
          selectedIndex={selectedIndex} onSelectIndex={i => {setPlaying(false); setSelectedIndex(i);}}
          cardOpen={cardOpen} onCardOpen={() => setCardOpen(true)} onCardClose={() => setCardOpen(false)}
          playing={playing} onTogglePlay={() => {if (selectedIndex >= points.length-1) setSelectedIndex(0); setPlaying(p => !p);}}
          reopenRef={reopenRef}
        />
        {view === 'analytics' && (
          <AnalyticsView points={points} unit="успешные посадки" loading={loading} error={error} onRetry={retry}
            selectedIndex={selectedIndex} onSelectIndex={i => {setPlaying(false); setSelectedIndex(i);}} />
        )}
      </div>
      {settingsOpen && <SettingsPanel onClose={() => { setSettingsOpen(false); settingsTriggerRef.current?.focus(); }} />}
    </div></ForecastContext.Provider>
  );
}
