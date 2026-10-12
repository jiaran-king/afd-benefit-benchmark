"""Compatibility names for the existing genuine AgentInfer formal path."""
from topology import GROUPS, RUN_NAMES, services_for, endpoints_for
TOPOLOGY = {
 'non_ep4': {'instances':4,'dp':1,'tp':4,'ep':4,'cache_domains':4,'mbt':8192},
 'non_ep8': {'instances':2,'dp':2,'tp':4,'ep':8,'cache_domains':4,'mbt':8192},
 'afd_eager': {'attention_die':12,'attention_dp':3,'attention_tp':4,'ffn_die':4,'ffn_dp':4,'ffn_tp':1,'ffn_ep':4,'cache_domains':3,'mbt':32768,'ffn_graph':False},
 'afd_fgraph': {'attention_die':12,'attention_dp':3,'attention_tp':4,'ffn_die':4,'ffn_dp':4,'ffn_tp':1,'ffn_ep':4,'cache_domains':3,'mbt':32768,'ffn_graph':True},
}
TASKS={key:'local-target' for key in GROUPS}
PREPARED='prepared256k-256sessions-v24'
MAX_LENGTH=262144
OUTPUT_TOKENS=1

def route_key(group):
 return 'afd' if group.startswith('afd_') else 'nonafd'

def domain_worker(group,domain):
 if group=='non_ep4': return 'nonafd',domain,0
 if group=='non_ep8': return 'nonafd',domain//2,domain%2
 return 'attention',0,domain
