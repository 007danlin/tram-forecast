// Runtime contract: backend/handoff/api.py (not the general v2 draft).
export type Filters = {route_ids: string[]; start: string; end: string; resolution: 'hour' | 'day'; forecast_run_id: string};
export type Capabilities = {
  schema_version: 'ml-handoff-v1'; forecast_run_id: string; start: string; end: string;
  routes: {route_id: string; method: 'model' | 'baseline'}[];
  resolutions: ('hour' | 'day')[]; warnings: string[]; limitations: string[];
  limits: {max_days: number; max_rows: number};
  scenario_supported?: boolean;
  scenario?: {coefficients?: string[]};
  year?: {version: string; source: string; qualitative_available: boolean; numeric_supported: false; value: null;
    history_end: string; history_months: number; reason: string;
    scenarios: {name: string; title: string; assumption: string; change: string; needed: string}[]};
};
export type Row = {
  route_id: string; start: string; end: string; value: number | null;
  reference_value: number | null; lower_90: number | null; upper_90: number | null;
  priority_score: number | null; status: 'ok' | 'cold_start_zero_baseline' | 'partial' | 'no_data';
  method: 'model' | 'baseline'; expected_hours: number; available_hours: number; coverage: number;
  base_value?: number | null; delta?: number | null;
};
export type Result = {
  schema_version: 'ml-handoff-v1'; forecast_run_id: string; result_id: string;
  model_version: string; dataset_version: string; csv_sha256: string; imported_at: string;
  filters: Filters; rows: Row[]; total: number | null;
  total_scope: 'complete' | 'available_only' | 'no_data'; coverage: number;
  warnings: string[]; limitations: string[]; interval_method: string;
};
export type Coefficients = {weather: number; event: number; closures: number; changes: number};
export const neutralCoefficients: Coefficients = {weather: 1, event: 1, closures: 1, changes: 1};
export type Scenario = {schema_version: 'manual-scenario-v1'; calculation_version: 'manual-multiply-v1';
  result_id: string; base: Result; coefficients: Coefficients; rows: Row[]; total: number | null;
  delta_total: number | null; interval_method: 'not_estimated'; source: 'dispatcher_assumption'};
export type Horizon = 'day' | 'week' | 'month' | 'year';
export const OVERVIEW = '__overview__';
const prefix = '/api/v2/handoff';
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string');
const identifier = (v: unknown): v is string => typeof v === 'string' && v.length > 0;
const number = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;
const nullable = (v: unknown) => v === null || number(v);
const stamp = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+03:00$/.test(v) && Number.isFinite(Date.parse(v));
const fraction = (v: unknown) => number(v) && v <= 1;
function requireContract(valid: unknown): asserts valid {
  if (!valid) throw new Error('Сервис вернул некорректный ответ. Повторите запрос.');
}

export function validateCapabilities(v: unknown): Capabilities {
  requireContract(object(v) && v.schema_version === 'ml-handoff-v1' && identifier(v.forecast_run_id)
    && v.timezone === 'Europe/Moscow' && v.unit === 'successful_boardings' && v.metric_id === 'successful_validations'
    && stamp(v.start) && stamp(v.end) && v.start < v.end
    && Array.isArray(v.routes) && v.routes.length > 0 && v.routes.every(r => object(r) && identifier(r.route_id) && ['model', 'baseline'].includes(String(r.method)))
    && new Set(v.routes.map(r => r.route_id)).size === v.routes.length
    && strings(v.resolutions) && v.resolutions.length > 0 && v.resolutions.every(r => ['hour', 'day'].includes(r))
    && strings(v.warnings) && strings(v.limitations) && object(v.limits) && number(v.limits.max_days) && number(v.limits.max_rows));
  requireContract(v.scenario_supported === undefined || typeof v.scenario_supported === 'boolean');
  requireContract(v.scenario === undefined || object(v.scenario) && (v.scenario.coefficients === undefined || strings(v.scenario.coefficients)));
  if (v.year !== undefined) {
    const year = v.year;
    requireContract(object(year) && year.version === 'qualitative-year-v1' && identifier(year.source)
      && year.qualitative_available === true && year.numeric_supported === false && year.value === null
      && typeof year.history_end === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(year.history_end)
      && number(year.history_months) && identifier(year.reason) && Array.isArray(year.scenarios)
      && year.scenarios.length === 3 && year.scenarios.every(s => object(s)
        && ['name', 'title', 'assumption', 'change', 'needed'].every(k => identifier(s[k]))));
  }
  return v as unknown as Capabilities;
}

export function sameFilters(a: Filters, b: Filters): boolean {
  return a.start === b.start && a.end === b.end && a.resolution === b.resolution && a.forecast_run_id === b.forecast_run_id
    && [...a.route_ids].sort().join(',') === [...b.route_ids].sort().join(',');
}

export function validateResult(v: unknown, query: Filters): Result {
  requireContract(object(v) && v.schema_version === 'ml-handoff-v1' && v.timezone === 'Europe/Moscow'
    && v.unit === 'successful_boardings' && v.metric_id === 'successful_validations'
    && v.forecast_run_id === query.forecast_run_id && identifier(v.result_id) && identifier(v.model_version)
    && identifier(v.dataset_version) && identifier(v.csv_sha256) && typeof v.imported_at === 'string'
    && typeof v.interval_method === 'string' && strings(v.warnings) && strings(v.limitations)
    && object(v.filters) && strings(v.filters.route_ids) && sameFilters(v.filters as unknown as Filters, query)
    && nullable(v.total) && ['complete', 'available_only', 'no_data'].includes(String(v.total_scope)) && fraction(v.coverage)
    && Array.isArray(v.rows));
  const step = query.resolution === 'hour' ? 3600000 : 86400000;
  const count = (Date.parse(query.end) - Date.parse(query.start)) / step;
  requireContract(v.rows.length === count * query.route_ids.length);
  const seen = new Set<string>();
  let available = 0;
  let expected = 0;
  for (const row of v.rows) {
    requireContract(object(row) && query.route_ids.includes(String(row.route_id)) && stamp(row.start) && stamp(row.end)
      && Date.parse(row.start) >= Date.parse(query.start) && Date.parse(row.end) <= Date.parse(query.end)
      && (Date.parse(row.start) - Date.parse(query.start)) % step === 0 && Date.parse(row.end) - Date.parse(row.start) === step
      && ['ok', 'cold_start_zero_baseline', 'partial', 'no_data'].includes(String(row.status))
      && ['model', 'baseline'].includes(String(row.method)) && ['value', 'reference_value', 'lower_90', 'upper_90', 'priority_score'].every(k => nullable(row[k]))
      && row.expected_hours === step / 3600000 && number(row.available_hours) && Number.isInteger(row.available_hours)
      && row.available_hours <= row.expected_hours && row.coverage === row.available_hours / row.expected_hours);
    requireContract((row.available_hours === 0) === (row.value === null)
      && (row.status === 'no_data') === (row.available_hours === 0)
      && (row.status === 'partial') === (row.available_hours > 0 && row.available_hours < row.expected_hours)
      && (query.resolution !== 'day' || (row.lower_90 === null && row.upper_90 === null))
      && (row.status !== 'cold_start_zero_baseline' || (row.method === 'baseline' && row.value === 0)));
    const key = `${row.route_id}/${row.start}`;
    requireContract(!seen.has(key)); seen.add(key);
    available += row.available_hours; expected += row.expected_hours;
  }
  requireContract(v.coverage === available / expected
    && v.total_scope === (available === expected ? 'complete' : available ? 'available_only' : 'no_data')
    && (v.total === null) === (available === 0));
  return v as unknown as Result;
}

// Calendar arithmetic uses UTC solely for date parts; API boundaries always carry MSK.
export function addDays(day: string, days: number): string {
  return new Date(Date.parse(`${day}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
}
export function buildFilters(caps: Capabilities, route: string, day: string, horizon: Horizon): Filters {
  if (horizon === 'year') throw new Error('Годовой режим качественный: численный запрос недоступен.');
  requireContract(/^\d{4}-\d{2}-\d{2}$/.test(day) && Number.isFinite(Date.parse(day)) && addDays(day, 0) === day);
  const startDay = horizon === 'month' ? `${day.slice(0, 7)}-01` : day;
  const nextMonth = new Date(`${startDay}T00:00:00Z`);
  nextMonth.setUTCMonth(nextMonth.getUTCMonth() + 1);
  const endDay = horizon === 'month' ? nextMonth.toISOString().slice(0, 10) : addDays(startDay, horizon === 'week' ? 7 : 1);
  const resolution = horizon === 'day' ? 'hour' : 'day';
  if ((route !== OVERVIEW && !caps.routes.some(r => r.route_id === route)) || !caps.resolutions.includes(resolution)) throw new Error('Этот режим недоступен для пакета.');
  const start = `${startDay}T00:00:00+03:00`, end = `${endDay}T00:00:00+03:00`;
  if (start < caps.start || end > caps.end) throw new Error('Выберите период целиком в доступном диапазоне. Неделя содержит 7 суток, месяц — все календарные дни.');
  if ((Date.parse(end) - Date.parse(start)) / 86400000 > caps.limits.max_days) throw new Error('Период превышает ограничение сервиса.');
  const route_ids = route === OVERVIEW ? caps.routes.map(r => r.route_id) : [route];
  if (route_ids.length * (Date.parse(end) - Date.parse(start)) / (resolution === 'hour' ? 3600000 : 86400000) > caps.limits.max_rows) throw new Error('Слишком много строк для обзора. Сократите период.');
  return {route_ids, start, end, resolution, forecast_run_id: caps.forecast_run_id};
}

export class ApiError extends Error {
  constructor(public status: number, public requestId = '') {
    super(({503: 'Готовый пакет прогноза отсутствует или недоступен.', 410: 'Версия прогноза изменилась. Обновите доступные данные.', 409: 'Результат экспорта изменился. Повторно получите прогноз перед скачиванием.'} as Record<number, string>)[status]
      ?? `Не удалось получить данные (HTTP ${status}). Повторите запрос.`);
  }
}
export async function request(path: string, signal: AbortSignal, body?: unknown): Promise<Response> {
  const response = await fetch(path.startsWith('/') ? path : `${prefix}/${path}`, {signal, ...(body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})});
  if (!response.ok) throw new ApiError(response.status, response.headers.get('X-Request-Id') ?? '');
  return response;
}
export async function getCapabilities(signal: AbortSignal): Promise<Capabilities> {
  const ready = await (await request('ready', signal)).json();
  requireContract(object(ready) && ready.status === 'ready' && identifier(ready.forecast_run_id));
  const caps = validateCapabilities(await (await request('capabilities', signal)).json());
  requireContract(caps.forecast_run_id === ready.forecast_run_id);
  return caps;
}
export async function getResult(filters: Filters, signal: AbortSignal): Promise<Result> {
  return validateResult(await (await request('query', signal, filters)).json(), filters);
}
export async function exportResult(result: Result, signal: AbortSignal): Promise<Blob> {
  const response = await request('export', signal, {...result.filters, expected_result_id: result.result_id});
  if (!/^text\/csv(?:;|$)/i.test(response.headers.get('Content-Type') ?? '') || response.headers.get('X-Result-Id') !== result.result_id) throw new Error('CSV не соответствует показанному результату. Повторите запрос.');
  return response.blob();
}

export const sameCoefficients = (a: Coefficients, b: Coefficients) => a.weather === b.weather && a.event === b.event && (a.closures ?? 1) === b.closures && (a.changes ?? 1) === b.changes;
export async function getScenario(filters: Filters, coefficients: Coefficients, signal: AbortSignal): Promise<Scenario> {
  const v = await (await request('/api/v2/scenarios/query', signal, {...filters, coefficients: Object.fromEntries(Object.entries(coefficients).filter(([k,v]) => k === "weather" || k === "event" || v !== 1))})).json();
  requireContract(object(v) && v.schema_version === 'manual-scenario-v1' && v.calculation_version === 'manual-multiply-v1'
    && identifier(v.result_id) && object(v.coefficients) && sameCoefficients(v.coefficients as Coefficients, coefficients)
    && nullable(v.total) && (v.delta_total === null || typeof v.delta_total === 'number' && Number.isFinite(v.delta_total))
    && v.interval_method === 'not_estimated' && v.source === 'dispatcher_assumption' && Array.isArray(v.rows));
  const base = validateResult(v.base, filters);
  requireContract(v.rows.length === base.rows.length && (v.total === null) === (base.total === null));
  for (let i = 0; i < base.rows.length; i++) {
    const b = base.rows[i], r = v.rows[i];
    requireContract(object(r) && r.route_id === b.route_id && r.start === b.start && r.end === b.end
      && r.base_value === b.value && nullable(r.value) && (r.value === null) === (b.value === null)
      && r.coverage === b.coverage && r.status === b.status && r.method === b.method
      && r.available_hours === b.available_hours && r.expected_hours === b.expected_hours
      && r.lower_90 === null && r.upper_90 === null && r.priority_score === null
      && (b.value === null ? r.delta === null : typeof r.value === 'number' && typeof r.delta === 'number'
        && Math.abs(r.value - b.value * coefficients.weather * coefficients.event * coefficients.closures * coefficients.changes) <= 1e-8 + Math.abs(r.value) * 1e-12
        && Math.abs(r.delta - (r.value - b.value)) <= 1e-8));
  }
  return v as unknown as Scenario;
}
export async function exportScenario(scenario: Scenario, signal: AbortSignal): Promise<Blob> {
  const response = await request('/api/v2/scenarios/export', signal, {...scenario.base.filters,
    coefficients: scenario.coefficients, expected_result_id: scenario.result_id});
  if (!/^text\/csv(?:;|$)/i.test(response.headers.get('Content-Type') ?? '') || response.headers.get('X-Result-Id') !== scenario.result_id) throw new Error('CSV не соответствует показанному сценарию.');
  return response.blob();
}
