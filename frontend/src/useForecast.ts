import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { addDays, ApiError, buildFilters, exportResult, getCapabilities, getResult, sameFilters } from './handoff';
import type { Capabilities, Horizon, Result } from './handoff';
export const format = (value: number | null) => value === null ? 'Нет данных' : value.toLocaleString('ru-RU', {maximumFractionDigits: 2});
export const statusLabels = {ok: 'Полное покрытие', cold_start_zero_baseline: 'Нулевой baseline', partial: 'Неполное покрытие', no_data: 'Нет данных'};
const message = (error: unknown) => error instanceof Error ? error.name === 'AbortError' ? 'Время ожидания истекло. Повторите запрос.' : error.message : 'Не удалось получить данные.';

export function useForecast() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [route, setRoute] = useState('');
  const [day, setDay] = useState('');
  const [horizon, setHorizon] = useState<Horizon>('day');
  const [bootstrap, setBootstrap] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [loadingCaps, setLoadingCaps] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [errorStatus, setErrorStatus] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [exporting, setExporting] = useState(false);
  const [selected, setSelected] = useState(0);
  const [playing, setPlaying] = useState(false);
  const exportController = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const filtersState = useMemo(() => {
    if (!caps) return {filters: null, problem: ''};
    try { return {filters: buildFilters(caps, route, day, horizon), problem: ''}; }
    catch (e) { return {filters: null, problem: message(e)}; }
  }, [caps, route, day, horizon]);
  const filters = filtersState.filters;
  const current = result && filters && sameFilters(result.filters, filters) ? result : null;
  const busy = loadingCaps || loading;
  const changeContext = () => {
    generation.current += 1; exportController.current?.abort(); setPlaying(false); setExporting(false);
  };
  const showError = (e: unknown) => {setError(message(e)); setErrorStatus(e instanceof ApiError ? e.status : 0);};

  useEffect(() => {
    const controller = new AbortController(); let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    setLoadingCaps(true); setCaps(null); setResult(null); setError(''); setErrorStatus(0);
    void getCapabilities(controller.signal).then(value => {
      if (!active) return;
      setCaps(value); setRoute((value.routes.find(r => r.method === 'model') ?? value.routes[0]).route_id);
      setDay(value.start.slice(0, 10)); setHorizon(value.resolutions.includes('hour') ? 'day' : 'week');
    }).catch(e => {if (active) showError(e);}).finally(() => {window.clearTimeout(timeout); if (active) setLoadingCaps(false);});
    return () => {active = false; controller.abort(); window.clearTimeout(timeout);};
  }, [bootstrap]);

  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setResult(null); setSelected(0); setPlaying(false); setLoading(false);
    if (!filters) return;
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    setLoading(true); setError(''); setErrorStatus(0);
    void getResult(filters, controller.signal).then(value => {if (active) setResult(value);})
      .catch(e => {if (active) showError(e);}).finally(() => {window.clearTimeout(timeout); if (active) setLoading(false);});
    return () => {active = false; controller.abort(); window.clearTimeout(timeout);};
  }, [filters, attempt]);

  useEffect(() => () => exportController.current?.abort(), []);
  useEffect(() => {
    if (!playing || !current || busy || error) return;
    const timer = window.setInterval(() => setSelected(i => {
      if (i >= current.rows.length - 1) {setPlaying(false); return i;}
      return i + 1;
    }), 1000);
    return () => window.clearInterval(timer);
  }, [playing, current, busy, error]);

  async function download() {
    if (!current || busy || error || exporting) return;
    const version = generation.current;
    const controller = new AbortController(); exportController.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    setExporting(true); setPlaying(false);
    try {
      const blob = await exportResult(current, controller.signal);
      if (controller.signal.aborted || generation.current !== version) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = `tramflow-${current.filters.start.slice(0, 10)}.csv`;
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {if (generation.current === version) showError(e);}
    finally {window.clearTimeout(timeout); if (generation.current === version) setExporting(false);}
  }
  function retry() {
    changeContext(); setResult(null); setError('');
    if (!caps || errorStatus === 410) {setCaps(null); setBootstrap(v => v + 1);}
    else setAttempt(v => v + 1);
  }
  const usable = !busy && !error && !filtersState.problem ? current : null;
  const points = useMemo(() => usable?.rows.map(row => ({...row, timestamp: row.start})) ?? [], [usable]);
  return {caps, route, day, horizon, current: usable, points, busy, error: error || filtersState.problem,
    errorStatus, exporting, retry, download, selected, setSelected, playing, setPlaying,
    changeRoute: (value: string) => {changeContext(); setRoute(value);},
    changeDay: (value: string) => {changeContext(); setDay(value);},
    changeHorizon: (value: Horizon) => {changeContext(); setHorizon(value);},
    reset: () => {if(caps) {changeContext(); setRoute((caps.routes.find(r => r.method === 'model') ?? caps.routes[0]).route_id); setDay(caps.start.slice(0,10)); setHorizon(caps.resolutions.includes('hour') ? 'day' : 'week');}},
    lastDay: caps ? addDays(caps.end.slice(0,10),-1) : undefined};
}
export type ForecastState = ReturnType<typeof useForecast>;
export const ForecastContext = createContext<ForecastState | null>(null);
export function useForecastData() {
  const value = useContext(ForecastContext);
  if (!value) throw new Error('Forecast context missing');
  return value;
}
