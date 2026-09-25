import { useEffect, useRef, useState } from 'react';
import { AppHeader, type ConnectionStatus, type ViewName } from './components/AppHeader';
import { FilterBar } from './components/FilterBar';
import { Workspace } from './components/Workspace';
import { AnalyticsView } from './components/AnalyticsView';
import { SettingsPanel } from './components/SettingsPanel';
import type { ForecastPoint } from './components/ForecastData';

type Forecast = { is_mock: true; unit: 'passengers'; points: ForecastPoint[] };

const MONTHS_RU = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

function formatDateRu(isoDate: string) {
  const [y, m, d] = isoDate.split('-').map(Number);
  if (!y || !m || !d) return isoDate;
  return `${d} ${MONTHS_RU[m - 1]} ${y}`;
}

async function getJson(path: string, signal: AbortSignal) {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function validateForecast(data: Forecast): Forecast {
  if (data.is_mock !== true || data.unit !== 'passengers' || !Array.isArray(data.points) || !data.points.length ||
    !data.points.every(p => Number.isInteger(p.value) && p.value >= 0 && typeof p.timestamp === 'string' &&
      /(?:Z|[+-]\d{2}:\d{2})$/.test(p.timestamp) && Number.isFinite(Date.parse(p.timestamp)))) {
    throw new Error('Некорректный ответ API');
  }
  return data;
}

const PLAY_STEP_MS = 900;

export function App() {
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);

  const [view, setView] = useState<ViewName>('map');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [cardOpen, setCardOpen] = useState(true);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);

  const reopenRef = useRef<HTMLButtonElement>(null);
  const settingsTriggerRef = useRef<HTMLButtonElement | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const filterBarRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    setLoading(true); setError(''); setForecast(null); setSelectedIndex(null); setPlaying(false);
    async function load() {
      try {
        const health = await getJson('/api/v1/health', controller.signal);
        if (health.status !== 'ok') throw new Error('Неожиданный статус сервиса');
        const data = validateForecast(await getJson('/api/v1/forecast', controller.signal));
        if (active) { setForecast(data); setFetchedAt(new Date()); }
      } catch {
        if (active) setError('Проверьте, что backend запущен и доступен, затем повторите запрос.');
      } finally {
        window.clearTimeout(timeout);
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; window.clearTimeout(timeout); controller.abort(); };
  }, [attempt]);

  const points = forecast?.points ?? [];
  const connection: ConnectionStatus = forecast ? 'ok' : error ? 'error' : 'checking';

  useEffect(() => {
    if (points.length && selectedIndex === null) setSelectedIndex(0);
  }, [points, selectedIndex]);

  useEffect(() => {
    if (!playing || points.length === 0) return;
    const id = window.setInterval(() => {
      setSelectedIndex(i => {
        const next = (i ?? 0) + 1;
        if (next >= points.length) { setPlaying(false); return i; }
        return next;
      });
    }, PLAY_STEP_MS);
    return () => window.clearInterval(id);
  }, [playing, points.length]);

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

  const retry = () => setAttempt(a => a + 1);

  return (
    <div className="app-shell">
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
          dataDateLabel={points[0] ? formatDateRu(points[0].timestamp.slice(0, 10)) : 'Нет данных'}
        />
        <Workspace
          hidden={view !== 'map'}
          points={points} unit={forecast?.unit ?? 'passengers'} isMock={forecast?.is_mock ?? true}
          loading={loading} error={error} onRetry={retry} fetchedAt={fetchedAt}
          selectedIndex={selectedIndex} onSelectIndex={setSelectedIndex}
          cardOpen={cardOpen} onCardOpen={() => setCardOpen(true)} onCardClose={() => setCardOpen(false)}
          playing={playing} onTogglePlay={() => setPlaying(p => !p)}
          reopenRef={reopenRef}
        />
        {view === 'analytics' && (
          <AnalyticsView points={points} unit={forecast?.unit ?? 'passengers'} loading={loading} error={error} onRetry={retry}
            selectedIndex={selectedIndex} onSelectIndex={setSelectedIndex} />
        )}
      </div>
      {settingsOpen && <SettingsPanel onClose={() => { setSettingsOpen(false); settingsTriggerRef.current?.focus(); }} />}
    </div>
  );
}
