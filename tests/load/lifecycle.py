"""Supplementary process-start/recreate measurements after the RPS test."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reference', type=Path, required=True)
parser.add_argument('--base-url', default='http://127.0.0.1:5173')
parser.add_argument('--project', required=True, help='The isolated local Compose project to recreate')
parser.add_argument('--compose-file', action='append', dest='compose_files')
parser.add_argument('--output', type=Path, required=True)
args=parser.parse_args()
if args.output.exists():
    parser.error('Output exists; preserve the previous measurement')
if urlsplit(args.base_url).hostname not in ('127.0.0.1','localhost','::1'):
    parser.error('This lifecycle check is intended for an isolated localhost stack')
root=Path.cwd()
reference=json.loads(args.reference.read_text())
base=args.base_url.rstrip('/')+'/api/v2/handoff'
env=dict(os.environ)
if not env.get('TRAMFLOW_HANDOFF_HOST_DIR'):
    parser.error('Set TRAMFLOW_HANDOFF_HOST_DIR to the imported release')
env['TRAMFLOW_HANDOFF_HOST_DIR']=str(Path(env['TRAMFLOW_HANDOFF_HOST_DIR']).resolve())
compose=['docker','compose','-p',args.project]
for path in args.compose_files or ['compose.yaml','compose.handoff.yaml','compose.load.yaml']:
    compose.extend(['-f',path])
container=subprocess.check_output([*compose,'ps','--all','-q','backend'],env=env,text=True).strip()
if not container or '\n' in container:
    parser.error('Expected exactly one existing backend container')
report={'run':reference['forecast_run_id'],'recreates':[]}
report['process_after_load']=json.loads(subprocess.check_output(['docker','exec',container,'python','-c','import json; from pathlib import Path; print(json.dumps({"status":Path("/proc/1/status").read_text()}))'],text=True))

def request(path,body=None):
    raw=None if body is None else json.dumps(body).encode()
    start=time.perf_counter()
    with urlopen(Request(base+path,data=raw,headers={'Content-Type':'application/json'}),timeout=10) as response:
        data=response.read()
    return json.loads(data), (time.perf_counter()-start)*1000, len(data)

def query(control):
    result,ms,size=request('/query',control['filters'])
    assert result['forecast_run_id']==reference['forecast_run_id']
    assert len(result['rows'])==len(control['rows'])
    for row,expected in zip(result['rows'],control['rows']):
        assert row['route_id']==expected['route_id'] and row['start']==expected['start']
        assert abs(row['value']-expected['value']) <= 1e-9+1e-12*abs(expected['value'])
    return ms,size,result

ready,_,_=request('/ready')
assert ready['forecast_run_id']==reference['forecast_run_id'], 'Reference does not match active run'

for iteration in range(2):
    start=time.perf_counter()
    subprocess.run([*compose,'up','-d','--no-deps','--force-recreate','--no-build','--pull','never','backend'],env=env,check=True,stdout=subprocess.DEVNULL)
    for _ in range(300):
        try:
            ready,_,_=request('/ready')
            assert ready['forecast_run_id']==reference['forecast_run_id']
            break
        except URLError:
            time.sleep(.1)
    else:
        raise RuntimeError('Ready failed after recreate')
    ready_ms=(time.perf_counter()-start)*1000
    container=subprocess.check_output([*compose,'ps','-q','backend'],env=env,text=True).strip()
    first_ms,first_size,_=query(reference['days'][0])
    inspected=json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0]
    mount=next(m for m in inspected['Mounts'] if m['Destination']=='/data/handoff')
    assert mount['RW'] is False and mount['Source']==env['TRAMFLOW_HANDOFF_HOST_DIR']
    report['recreates'].append({'to_ready_ms':ready_ms,'first_query_ms':first_ms,'response_bytes':first_size,'mount':mount,'run':ready['forecast_run_id']})

def summarize(values):
    values=sorted(values)
    def quantile(p):
        pos=(len(values)-1)*p; lower=int(pos); upper=min(lower+1,len(values)-1)
        return values[lower]+(values[upper]-values[lower])*(pos-lower)
    return {'n':len(values),'p50_ms':statistics.median(values),'p95_ms':quantile(.95),'p99_ms':quantile(.99),'max_ms':max(values)}

report['repeated_day']=summarize([query(reference['days'][0])[0] for _ in range(30)])
report['different_days']=summarize([query(control)[0] for control in reference['days']])
report['different_months']=summarize([query(control)[0] for control in reference['months']])
report['response_bytes']={name:query(controls[0])[1] for name,controls in [('day',reference['days']),('month',reference['months'])]}
_,report['large_query_bytes'],result=query(reference['export'])
body=json.dumps({**result['filters'],'expected_result_id':result['result_id']}).encode()
with urlopen(Request(base+'/export',data=body,headers={'Content-Type':'application/json'}),timeout=10) as response:
    export=response.read()
    assert response.headers['X-Result-Id']==result['result_id']
    report['export_bytes']=len(export)
assert len(export.decode('utf-8-sig').strip().splitlines())==7441
report['passed']=True
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False))
