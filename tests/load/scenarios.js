import http from 'k6/http';
import exec from 'k6/execution';
import {check, fail} from 'k6';
import {Rate, Trend} from 'k6/metrics';
const base = __ENV.BASE_URL || 'http://127.0.0.1:15186';
if (!/^http:\/\/(127\.0\.0\.1|frontend)(:\d+)?$/.test(base)) throw new Error('Local-only acceptance');
const controls = JSON.parse(open(__ENV.REFERENCE));
const rate = Number(__ENV.RATE || 50);
const semantic = new Rate('semantic_valid');
const latency = new Trend('scenario_latency', true);
export const options = {scenarios:{query:{executor:'constant-arrival-rate',rate,timeUnit:'1s',duration:__ENV.DURATION||'30s',preAllocatedVUs:100,maxVUs:400}},
  thresholds:{http_req_failed:['rate==0'],semantic_valid:['rate==1'],dropped_iterations:['count==0'],scenario_latency:['p(95)<300']},
  summaryTrendStats:['med','p(95)','p(99)','max']};
const near=(a,b)=>typeof a==='number' && Math.abs(a-b)<1e-8+Math.abs(b)*1e-12;
export function setup(){const r=http.get(base+'/api/v2/handoff/ready');if(r.status!==200||r.json().forecast_run_id!==controls.forecast_run_id)fail('Wrong run');}
export default function(){
  const i=exec.scenario.iterationInTest, pool=i%10<7?controls.days:controls.months, c=pool[Math.floor(i/10)%pool.length];
  const weather=i%2?1.1:0.8,event=1.2;
  const r=http.post(base+'/api/v2/scenarios/query',JSON.stringify({...c.filters,coefficients:{weather,event}}),{headers:{'Content-Type':'application/json'}});
  let ok=false;
  try {const s=r.json();ok=r.status===200 && s.schema_version==='manual-scenario-v1' && s.base.forecast_run_id===controls.forecast_run_id
    && near(s.base.total,c.total) && near(s.total,c.total*weather*event) && s.rows.length===c.rows.length
    && s.rows.every((p,j)=>p.route_id===c.rows[j].route_id && p.start===c.rows[j].start && near(p.base_value,c.rows[j].value)
      && near(p.value,c.rows[j].value*weather*event) && p.coverage===1 && p.lower_90===null && p.upper_90===null
      && p.status===(p.route_id==='5'?'cold_start_zero_baseline':'ok'));}catch(_){}
  semantic.add(ok);latency.add(r.timings.duration);check(r,{'scenario matches source CSV':()=>ok});
}
