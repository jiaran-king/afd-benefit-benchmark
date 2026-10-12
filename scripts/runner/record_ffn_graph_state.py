"""Record FFN Python state using read-only process memory; never attach or execute in workers."""
import ctypes
from functools import lru_cache
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(os.environ['BENCH_WORK_DIR'])
PREP = Path(__file__).resolve().parent
GROUP, PHASE = sys.argv[1:3]
assert GROUP in ('afd_eager','afd_fgraph') and PHASE in ('before','after')
RUN = ROOT / 'runs' / os.environ['BENCH_RUN_NAME']
if sys.version_info[:2] != (3, 12):
    argv = json.loads((RUN/'configuration/ffn-0/argv.json').read_text())
    os.execv(argv[0], [argv[0], str(PREP/'record_ffn_graph_state.py'), GROUP, PHASE])

sys.path.insert(0, str(PREP))
from live_environment import mappings

C_LAYOUT = r'''
#define Py_BUILD_CORE
#include <Python.h>
#include <stddef.h>
#include <stdio.h>
#include "internal/pycore_runtime.h"
#include "internal/pycore_interp.h"
#include "internal/pycore_dict.h"
#define O(T,F) printf("\"" #T "." #F "\":%zu,", offsetof(T,F))
int main(void) {
 printf("{");
 O(_PyRuntimeState,interpreters.main);
 O(PyInterpreterState,gc.generations);
 O(PyInterpreterState,gc.permanent_generation);
 O(PyTypeObject,tp_name); O(PyTypeObject,tp_flags); O(PyTypeObject,tp_dictoffset);
 O(PyHeapTypeObject,ht_cached_keys);
 O(PyDictObject,ma_keys); O(PyDictObject,ma_values); O(PyDictObject,ma_used);
 O(PyDictKeysObject,dk_log2_index_bytes); O(PyDictKeysObject,dk_kind);
 O(PyDictKeysObject,dk_nentries); O(PyDictKeysObject,dk_indices);
 O(PyASCIIObject,length); O(PyASCIIObject,state);
 printf("\"gc_generation_size\":%zu,\"gc_head_size\":%zu,\"ascii_size\":%zu,\"managed_dict_flag\":%lu}",
   sizeof(struct gc_generation),sizeof(PyGC_Head),sizeof(PyASCIIObject),(unsigned long)Py_TPFLAGS_MANAGED_DICT);
}
'''
with tempfile.TemporaryDirectory(prefix='ffn-graph-readonly-') as tmp:
    cfile=Path(tmp)/'layout.c'; executable=Path(tmp)/'layout'
    cfile.write_text(C_LAYOUT)
    subprocess.run(['gcc','-I'+__import__('sysconfig').get_path('include'),str(cfile),'-o',str(executable)],check=True,capture_output=True)
    ABI=json.loads(subprocess.check_output([str(executable)]))

class Reader:
    def __init__(self,pid):
        self.pid=pid
        self.fd=os.open(f'/proc/{pid}/mem',os.O_RDONLY)
    @lru_cache(maxsize=8192)
    def page(self,address):
        return os.pread(self.fd,4096,address)
    def read(self,address,size,cached=True):
        if not cached: return os.pread(self.fd,size,address)
        low=address & ~4095
        if address+size <= low+4096:
            data=self.page(low)[address-low:address-low+size]
        else: data=os.pread(self.fd,size,address)
        if len(data)!=size: raise ValueError('short memory read')
        return data
    def u64(self,address,cached=True): return struct.unpack('<Q',self.read(address,8,cached))[0]
    def i64(self,address): return struct.unpack('<q',self.read(address,8))[0]
    def u8(self,address): return self.read(address,1)[0]
    def offset(self,key): return ABI[key]
    @lru_cache(maxsize=4096)
    def type_name(self,typ):
        ptr=self.u64(typ+self.offset('PyTypeObject.tp_name'))
        return self.read(ptr,128).split(b'\0',1)[0].decode(errors='replace')
    def kind(self,obj): return self.type_name(self.u64(obj+8)) if obj else '<null>'
    def ascii(self,obj):
        if self.kind(obj)!='str': return None
        state=struct.unpack('<I',self.read(obj+self.offset('PyASCIIObject.state'),4))[0]
        length=self.i64(obj+self.offset('PyASCIIObject.length'))
        if state & 64 and state & 32 and 0<=length<=200:
            return self.read(obj+ABI['ascii_size'],length).decode('ascii')
        return None
    def integer(self,obj):
        assert self.kind(obj) in ('int','bool')
        tag=self.u64(obj+16,False);digits=tag>>3
        assert digits<=4
        value=sum(struct.unpack('<I',self.read(obj+24+4*i,4,False))[0]<<(30*i) for i in range(digits))
        return -value if tag&3==2 else value
    def attributes(self,obj):
        typ=self.u64(obj+8)
        if self.u64(typ+self.offset('PyTypeObject.tp_flags')) & ABI['managed_dict_flag']:
            dorv=self.u64(obj-24,False)
            if dorv & 1:
                values=dorv+1
                keys=self.u64(typ+self.offset('PyHeapTypeObject.ht_cached_keys'))
            else:
                assert dorv
                keys=self.u64(dorv+self.offset('PyDictObject.ma_keys'),False)
                values=self.u64(dorv+self.offset('PyDictObject.ma_values'),False)
        else:
            offset=self.i64(typ+self.offset('PyTypeObject.tp_dictoffset'))
            assert offset>0
            dictionary=self.u64(obj+offset,False)
            keys=self.u64(dictionary+self.offset('PyDictObject.ma_keys'),False)
            values=self.u64(dictionary+self.offset('PyDictObject.ma_values'),False)
        count=self.i64(keys+self.offset('PyDictKeysObject.dk_nentries'))
        assert 0<=count<=20000
        general=self.u8(keys+self.offset('PyDictKeysObject.dk_kind'))==0
        start=keys+self.offset('PyDictKeysObject.dk_indices')+(1<<self.u8(keys+self.offset('PyDictKeysObject.dk_log2_index_bytes')))
        result={}
        for i in range(count):
            entry=start+i*(24 if general else 16)
            key=self.u64(entry+(8 if general else 0))
            if not key: continue
            name=self.ascii(key)
            if name is None: continue
            value=self.u64(values+8*i if values else entry+(16 if general else 8),False)
            if value: result[name]=value
        return result
    def locate_runner(self):
        own_symbol=ctypes.addressof(ctypes.c_char.in_dll(ctypes.pythonapi,'_PyRuntime'))
        own_mapping=next(v for v in mappings(os.getpid()) if v[0]<=own_symbol<v[1])
        own_base=next(v for v in mappings(os.getpid()) if v[3:]==own_mapping[3:] and v[2]==0)
        target_base=next(v for v in mappings(self.pid) if v[3:]==own_mapping[3:] and v[2]==0)
        runtime=target_base[0]+own_symbol-own_base[0]
        interp=self.u64(runtime+self.offset('_PyRuntimeState.interpreters.main'),False)
        heads=[interp+self.offset('PyInterpreterState.gc.permanent_generation')]
        heads += [interp+self.offset('PyInterpreterState.gc.generations')+i*ABI['gc_generation_size'] for i in [2,1,0]]
        seen=set()
        for head in heads:
            node=self.u64(head,False)
            while node and node!=head and node not in seen:
                seen.add(node)
                assert len(seen)<5000000
                obj=node+ABI['gc_head_size']
                if self.kind(obj)=='AFDNPUFFNModelRunner': return obj,len(seen)
                node=self.u64(node,False)
        raise RuntimeError('No live FFN model runner found; preserve read failure')

# Verify the ABI reader against known objects in this recorder process.
class SelfCheck:
    pass
sample=SelfCheck()
for i in range(45): setattr(sample,f'field_{i}',i)
sample._async_cam_ffn_graph_enabled=True
sample._async_cam_ffn_replays=123456789012
reader=Reader(os.getpid())
attrs=reader.attributes(id(sample))
assert reader.integer(attrs['_async_cam_ffn_graph_enabled'])==1
assert reader.integer(attrs['_async_cam_ffn_replays'])==123456789012
os.close(reader.fd); reader.page.cache_clear()

records=json.loads((RUN/'configuration/ffn-0/actual-processes.json').read_text())
selected=[v for v in records if any('vllm_ascend_C' in p for p in v['maps'])]
assert len(selected)==4
path=RUN/'configuration/ffn-0/native-graph-live-state.json'
previous=json.loads(path.read_text()) if path.exists() else None
previous_workers={(v['pid'],v['start_ticks']):v for v in previous['workers']} if previous else {}
out={'time_ns':time.time_ns(),'method':'read-only /proc/PID/mem and installed CPython ABI; no attach, pause, signal, injection or model request',
     'abi_self_check':'passed','abi':ABI,'workers':[]}
for row in selected:
    pid=row['pid'];state=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    assert state[0]!='Z' and state[19]==row['start_ticks']
    reader=Reader(pid)
    try:
        prior=previous_workers.get((pid,row['start_ticks']))
        if prior:
            address=int(prior['runner_address'],16);traversed=0
            assert reader.kind(address)=='AFDNPUFFNModelRunner'
        else: address,traversed=reader.locate_runner()
        attributes=reader.attributes(address)
        graph=attributes['_async_cam_ffn_graph'];counter=attributes['_async_cam_ffn_replays']
        connector=attributes['connector'];connector_attrs=reader.attributes(connector)
        item={'pid':pid,'start_ticks':row['start_ticks'],'runner_address':hex(address),'gc_objects_read':traversed,
              'runner_type':reader.kind(address),'enabled':bool(reader.integer(attributes['_async_cam_ffn_graph_enabled'])),
              'graph_address':hex(graph),'graph_type':reader.kind(graph),
              'output_type':reader.kind(attributes['_async_cam_ffn_output']),
              'replays':reader.integer(counter),'layered_executor_type':reader.kind(attributes['_layered_executor']),
              'world_rank':reader.integer(connector_attrs['world_rank']),'read_time_ns':time.time_ns(),
              'legacy_graph_entries':reader.u64(attributes['_acl_graphs']+ABI['PyDictObject.ma_used'],False)}
        assert item['enabled']==(GROUP=='afd_fgraph'),item
        if PHASE=='after' and GROUP=='afd_fgraph':
            assert item['graph_type']=='NPUGraph' and item['output_type']=='Tensor' and item['replays']>0,item
        if GROUP=='afd_eager':
            assert item['replays']==0,item
        assert item['legacy_graph_entries']==0
        if prior and GROUP=='afd_fgraph':
            if prior['graph_type']=='NPUGraph': assert item['graph_address']==prior['graph_address']
            assert item['replays']>prior['replays']
            item['previous_replays']=prior['replays']
            item['previous_read_time_ns']=prior['read_time_ns']
            item['replay_count_increased']=True
        out['workers'].append(item)
    finally:
        os.close(reader.fd);reader.page.cache_clear();reader.type_name.cache_clear()
out['status']='passed'
out['group']=GROUP
out['phase']=PHASE
out['recorded_at_ns']=time.time_ns()
if path.exists():
    previous=path.with_name(f'native-graph-live-state-{out["recorded_at_ns"]}.json')
    previous.write_bytes(path.read_bytes())
path.write_text(json.dumps(out,indent=2)+'\n')
path.with_name('native-graph-state-'+PHASE+'.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
