import http from 'k6/http';
import exec from 'k6/execution';
import {check, fail} from 'k6';
import {Rate, Trend, Counter} from 'k6/metrics';

const base = (__ENV.BASE_URL || 'http://127.0.0.1:5173').replace(/\/$/, '') + '/api/v2/handoff';
const rate = Number(__ENV.RATE || 50);
const mode = __ENV.MODE || 'load';
if (!__ENV.REFERENCE) throw new Error('REFERENCE must name the controls generated from the supplied local release');
const controls = JSON.parse(open(__ENV.REFERENCE));
const semantic = new Rate('semantic_valid');
const latency = new Trend('measured_latency', true);
const requests = new Counter('measured_requests');
const thresholds = {'semantic_valid':['rate==1'], 'http_req_failed{phase:measured}':['rate<0.01']};
if (mode !== 'export') Object.assign(thresholds, {
  'measured_latency':['p(95)<300'], 'measured_latency{class:day}':['p(95)<300'],
  'measured_latency{class:month}':['p(95)<300'], 'dropped_iterations':['count==0'],
});
export const options = {
  scenarios: mode === 'export' ? {export:{executor:'shared-iterations', vus:1, iterations:1}} :
    {traffic:{executor:'constant-arrival-rate', rate, timeUnit:'1s', duration:__ENV.DURATION || '5m', preAllocatedVUs:Math.max(50,rate), maxVUs:Math.max(100,rate*2)}},
  thresholds, summaryTrendStats:['min','med','p(95)','p(99)','max'],
};
const headers = {'Content-Type':'application/json', ...(__ENV.AUTHORIZATION ? {Authorization:__ENV.AUTHORIZATION} : {})};
const near = (actual, expected) => typeof actual === 'number' && Number.isFinite(actual) && actual >= 0 && Math.abs(actual-expected) <= 1e-9 + 1e-12*Math.abs(expected);
function valid(response, control) {
  if (response.status !== 200) return false;
  try {
    const value = response.json();
    if (value.schema_version !== 'ml-handoff-v1' || value.forecast_run_id !== controls.forecast_run_id) return false;
    if (!control) return Array.isArray(value.routes) && value.routes.length === 10 && value.routes.some(r => r.route_id === '5');
    return value.rows.length === control.rows.length && value.coverage === 1 && near(value.total,control.total)
      && value.rows.every((row,i) => row.route_id === control.rows[i].route_id && row.start === control.rows[i].start && near(row.value,control.rows[i].value)
        && row.coverage === 1 && row.method === (row.route_id === '5' ? 'baseline' : 'model') && row.status === (row.route_id === '5' ? 'cold_start_zero_baseline' : 'ok'));
  } catch (_) {return false;}
}
export function setup() {
  const params = {headers, tags:{phase:'setup'}, timeout:'30s'};
  const ready = http.get(base+'/ready',params);
  if (ready.status !== 200 || ready.json().forecast_run_id !== controls.forecast_run_id) fail('A validated matching handoff is required before load');
  const caps = http.get(base+'/capabilities',params);
  if (!valid(caps,null) || caps.json().start !== '2025-11-01T00:00:00+03:00' || caps.json().end !== '2026-01-01T00:00:00+03:00') fail('Incomplete period/catalogue');
  const first = http.post(base+'/query',JSON.stringify(controls.days[0].filters),params);
  if (!valid(first,controls.days[0])) fail('Source/API control mismatch before load');
  console.log(JSON.stringify({run:controls.forecast_run_id,csv_sha256:controls.csv_sha256,requested_rps:mode === 'export' ? null : rate,first_query_ms:first.timings.duration,mode}));
  if (mode === 'export') {
    const result = http.post(base+'/query',JSON.stringify(controls.export.filters),params);
    if (!valid(result,controls.export)) fail('Export source control mismatch');
    return {filters:result.json().filters,result_id:result.json().result_id};
  }
  return {};
}
export default function(data) {
  const index = exec.scenario.iterationInTest;
  const slot = index % 10;
  const kind = mode === 'export' ? 'export' : slot < 7 ? 'day' : slot < 9 ? 'month' : 'capabilities';
  const pool = kind === 'day' ? controls.days : controls.months;
  const control = kind === 'capabilities' || kind === 'export' ? null : pool[Math.floor(index/10) % pool.length];
  const params = {headers,tags:{phase:'measured',class:kind},timeout:'30s'};
  // Exactly one request per measured iteration: iteration rate equals offered RPS.
  const response = kind === 'capabilities' ? http.get(base+'/capabilities',params) : kind === 'export'
    ? http.post(base+'/export',JSON.stringify({...data.filters,expected_result_id:data.result_id}),params)
    : http.post(base+'/query',JSON.stringify(control.filters),params);
  let ok;
  if (kind === 'export') {
    ok = response.status === 200 && (response.headers['Content-Type'] || '').startsWith('text/csv') && response.headers['X-Result-Id'] === data.result_id;
    if (ok) {
      const lines = response.body.replace(/^\uFEFF/,'').trim().split(/\r?\n/); const fields=lines[0].split(',');
      ok = lines.length === 7441 && lines.slice(1).every((line,i) => {const row=line.split(','); const expected=controls.export.rows[i]; return row[fields.indexOf('route_id')] === expected.route_id && row[fields.indexOf('start')] === expected.start && near(Number(row[fields.indexOf('value')]),expected.value);});
    }
  } else ok = valid(response,control);
  semantic.add(ok,{class:kind}); latency.add(response.timings.duration,{class:kind}); requests.add(1,{class:kind});
  check(response,{'semantic source match':() => ok},{class:kind});
}
