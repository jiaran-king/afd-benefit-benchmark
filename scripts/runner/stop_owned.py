"""Stop only this arm's owned service processes; retain task and storage."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

r=Path(os.environ['BENCH_WORK_DIR']);group=sys.argv[1]
run=r/'runs'/os.environ['BENCH_RUN_NAME']
manifest=json.loads((run/'manifest.json').read_text())
assert manifest['arm']==group
out={'started_ns':time.time_ns(),'group':group,'task_retained':True,'storage_retained':True,'owned':[],'signals':[]}
drivers={s['driver_pid']:s['driver_start_ticks'] for s in manifest['services']}
recorded=dict(drivers)
for snapshot in (run/'configuration').glob('*/actual-processes.json'):
 for v in json.loads(snapshot.read_text()):recorded[v['pid']]=v['start_ticks']
processes={};selected=set()
for p in Path('/proc').glob('[0-9]*'):
 try:
  pid=int(p.name);stat=(p/'stat').read_text().rsplit(')',1)[1].split()
  if stat[0]=='Z':continue
  processes[pid]={'pid':pid,'start_ticks':stat[19],'ppid':int(stat[1])}
  env=dict(x.split('=',1) for x in (p/'environ').read_bytes().decode(errors='replace').split('\0') if '=' in x)
  if env.get('BENEFIT_RUN')==str(run) or recorded.get(pid)==stat[19]:selected.add(pid)
 except (OSError,ValueError):continue
for _ in range(30):
 children={pid for pid,v in processes.items() if v['ppid'] in selected}
 if children<=selected:break
 selected|=children
out['ownership_evidence']='matching saved PID/start_ticks, exact run environment tag, and descendants of those live owned processes'
out['owned']=[processes[pid] for pid in sorted(selected)]
if '--inspect' in sys.argv:
 prep=r
 excluded=[]
 for path in [prep/f'{group}-replay-process.json',prep/'sequence-lock.json']:
  if path.exists():
   v=json.loads(path.read_text());assert v['pid'] not in selected;excluded.append(v['pid'])
 workers=[v for path in (run/'configuration').glob('*/actual-processes.json') for v in json.loads(path.read_text()) if any('vllm_ascend_C' in x for x in v['maps'])]
 assert len(workers)==16 and all(v['pid'] in selected and processes[v['pid']]['start_ticks']==v['start_ticks'] for v in workers)
 print(json.dumps({'group':group,'inspection_only':True,'selected_processes':len(selected),'device_workers_covered':len(workers),'excluded_replay_and_sequence_pids':excluded,'signals_sent':0}))
 raise SystemExit(0)
def live(v):
 try:
  st=Path(f'/proc/{v["pid"]}/stat').read_text().rsplit(')',1)[1].split()
  return st[0]!='Z' and st[19]==v['start_ticks']
 except FileNotFoundError:return False
for v in out['owned']:
 if live(v):
  try:os.kill(v['pid'],signal.SIGTERM)
  except ProcessLookupError:continue
  out['signals'].append({'pid':v['pid'],'signal':'SIGTERM'})
deadline=time.monotonic()+25
while any(live(v) for v in out['owned']) and time.monotonic()<deadline:time.sleep(.5)
for v in out['owned']:
 if live(v):
  try:os.kill(v['pid'],signal.SIGKILL)
  except ProcessLookupError:continue
  out['signals'].append({'pid':v['pid'],'signal':'SIGKILL'})
time.sleep(2)
out['remaining']=[v for v in out['owned'] if live(v)]
deadline=time.monotonic()+30
while True:
 out['npu_smi']=subprocess.check_output(['npu-smi','info'],text=True)
 if all(f'No running processes found in NPU {i}' in out['npu_smi'] for i in range(8)) or time.monotonic()>=deadline:break
 time.sleep(1)
out['finished_ns']=time.time_ns()
(run/'stop-owned.json').write_text(json.dumps(out,indent=2)+'\n')
assert not out['remaining']
assert all(f'No running processes found in NPU {i}' in out['npu_smi'] for i in range(8))
print(json.dumps({'group':group,'stopped_processes':len(out['owned']),'idle_16_die':True,'task_retained':True,'storage_retained':True}))
