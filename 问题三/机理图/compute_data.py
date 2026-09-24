"""Read existing evidence only; no new optimization or production mutations."""
from pathlib import Path
import json, hashlib, itertools
import numpy as np

OUT=Path(__file__).resolve().parent
Q3=OUT.parent
SOURCES=[]
def read(relative):
    p=Q3/relative
    SOURCES.append(dict(path=relative,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    return json.loads(p.read_text(encoding='utf-8'))

def main():
    archive=read('搜索精修/扩展固定结构精修_v1/共同档案重评/目标去重共同档案.json')
    archive=[r for r in archive if r['nondominated']]
    filters=[]
    for caps in [dict(N=24,E=65.20,L=650),dict(N=24,E=65.13,L=500),dict(N=24,E=64.95,L=500)]:
        eligible=[i for i,p in enumerate(archive) if all(p['objective'][{'N':0,'E':1,'L':3}[k]]<=v+1e-8 for k,v in caps.items())]
        best=None
        if eligible:
            c=min(archive[i]['objective'][2] for i in eligible)
            ties=[i for i in eligible if archive[i]['objective'][2]<=c+2e-4]
            # Manuscript (6-28): lexicographic C, L, E, N, with stated tolerances.
            l=min(archive[i]['objective'][3] for i in ties)
            ties=[i for i in ties if archive[i]['objective'][3]<=l+1e-6]
            best=min(ties,key=lambda i:(archive[i]['objective'][1],archive[i]['objective'][0]))
        filters.append(dict(caps=caps,eligible=eligible,best=best))
    logs=[r for r in read('日志/搜索记录.json') if r['kind']=='ALNS']
    chains=[]
    for seed in sorted(set(r['seed'] for r in logs)):
        rows=sorted([r for r in logs if r['seed']==seed],key=lambda r:r['iteration'])
        chains.append(dict(seed=seed,wave=rows[0]['wave'],caps=rows[0]['caps'],rows=rows,
                           returned_count=sum(bool(r['feasible']) for r in rows)))
    plan=read('搜索精修/扩展固定结构精修_v1/official/已核验方案.json')
    # Show actual incidence, but removal/reconnection is a labelled conceptual move.
    relay=plan['relays'][0]
    incident=[r for r in plan['routes'] if any(l['relay_slot']==relay['slot'] for l in r['links'])]
    others=[r for r in plan['routes'] if r not in incident]
    graph=dict(relay=relay['relay_id'],slot=relay['slot'],
               routes=[dict(id=r['route_id'],zone='/'.join(r['zones']),related=r in incident) for r in (incident[:4]+others[:2])],
               incidence_count=len(incident),meaning='Subset of actual incidence; highlighted removal is illustrative, not a recovered ALNS transition')
    old=read('搜索精修/扩展固定结构精修_v1/扩展搜索汇总.json')
    runs=[]
    for mode in ['C','E','L','N']:
        rel=f'扩展搜索后台/两小时_20260924_045708_v2/全库_{mode}/直接联合MILP结果.json'
        r=read(rel)
        runs.append({k:r[k] for k in ['scalar_objective','epsilon_caps','finite_model_valid_lower_bound','elapsed_s','iterations','status']})
    # Analytic toy MILP: min u+v, 2u+v>=4, u+2v>=4, 0<=u,v<=3.
    toy=dict(kind='synthetic illustrative MILP, unrelated to actual sortie counts',
             vertices=[[.5,3],[3,3],[3,.5],[4/3,4/3]],
             integers=[[u,v] for u,v in itertools.product(range(4),repeat=2) if 2*u+v>=4 and u+2*v>=4],
             LP=[4/3,4/3],IP=[[1,2],[2,1]],LB=8/3,UB=3.)
    assert min(sum(p) for p in toy['integers'])==toy['UB']
    data=dict(archive=archive,filters=filters,chains=chains,graph=graph,old_bounds=old['direct_runs'],
              long_runs=runs,toy=toy,sources=SOURCES,
              scope='O01-only battery exchange, no carried spare; all figures distinguish measured archives/logs and schematics',
              no_new_optimization=True,archive_filtering_is_posthoc_not_original_epsilon_history=True,
              historical_ALNS_feasible_flag_is_solver_return_not_independent_certification=True)
    (OUT/'mechanism_data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('DATA_READY',len(archive),'archive vectors',len(logs),'ALNS records')

if __name__=='__main__':main()
