"""Per-objective-archive type decomposition timing polish.

Candidate identities and box groups are fixed per archived plan; all matching
UAV/battery assignments and starts are reopened independently within each type.
No formal result files are modified.
"""
from __future__ import annotations
from pathlib import Path
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib,json,math,sys,time
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]; Q2=ROOT/'问题二'; AUD=Q2/'源头核查_20260924/implementation'
sys.path.insert(0,str(Q2));sys.path.insert(0,str(AUD))
from q2_data import load_data,decode,make_route,save_json
from q2_joint import JointModel
from q2_verify import verify_plan
from independent_raw_verify import raw_data,verify as raw_verify

ARCH=Q2/'改进搜索_20260924/联合非支配档案.json'

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))

def subset_data(data, vehicle):
    d=deepcopy(data)
    d['vehicles']={vehicle:deepcopy(data['vehicles'][vehicle])}
    d['uavs']={u:g for u,g in data['uavs'].items() if g==vehicle}
    d['batteries']={p:g for p,g in data['batteries'].items() if g==vehicle}
    # Nodes/geos can remain complete; every route's nodes are from this set.
    return d

def normalize_route(data, r):
    q=make_route(data,r['vehicle'],deepcopy(r['events']))
    if q is None: raise ValueError(f'invalid archived candidate {r.get("candidate_id")}')
    q.update(start=float(r['start']),uav=r['uav'],battery_id=r['battery_id'])
    # preserve archived identity only for warm construction; decode will assign
    # fresh route IDs when plans are merged.
    q['route_id']=r.get('route_id')
    return q

def local_plan(data, routes):
    p=decode(data,[normalize_route(data,r) for r in routes])
    c,e,_=verify_plan(data,p)
    if not c['all']: raise AssertionError(e[:8])
    return p

def global_type_contribution(data, p, vehicle):
    soft=[b for b,v in data['boxes'].items() if not v['hard'] and data['uavs'].get(next((r['uav'] for r in p['routes'] if b in r['box_ids']),''))==vehicle]
    # Use all boxes on selected routes, since route type is homogeneous.
    ids={b for r in p['routes'] if r['vehicle']==vehicle for b in r['box_ids']}
    soft=[b for b in ids if not data['boxes'][b]['hard']]
    den=sum(data['boxes'][b]['priority'] for b in soft) or 1.
    numerator=sum(data['boxes'][b]['priority']*max(0.,next(x['delivery'] for x in p['boxes'] if x['box']==b)-data['boxes'][b]['expected']) for b in soft)
    return numerator,den,numerator/den

def merge_plans(data, typed):
    records=[]
    for vehicle,p in typed.items():
        for r in p['routes']:
            q=deepcopy(r);q.pop('route_id',None);records.append(q)
    out=decode(data,records)
    c,e,re=verify_plan(data,out)
    if not c['all']:raise AssertionError(e[:10])
    return out,c,e,re

def one_plan(idx, original):
    begin=time.perf_counter();data=load_data();raw=raw_data();global_C=float(original['objective'][2]); typed={};stages=[]
    for g in sorted(data['vehicles']):
        routes=[r for r in original['routes'] if r['vehicle']==g]
        boxes={b for r in routes for b in r['box_ids']}
        if not routes:
            # Some archived plans use only B/C.  There is no subproblem for an
            # absent type; do not manufacture an empty route plan that the
            # strict verifier would (correctly) reject.
            stages.append({'vehicle':g,'skipped':True,'reason':'no routes of this type'})
            continue
        sd=subset_data(data,g);sd['boxes']={b:deepcopy(data['boxes'][b]) for b in boxes}
        warm=local_plan(sd,routes)
        num,den,orig_local_L=global_type_contribution(data,original,g)
        # JointModel's local L is numerator/den, so original same-type cap is
        # exactly this value. C uses the original global max as a valid cap.
        cap={'C':global_C,'L':orig_local_L+1e-7}
        m=JointModel(sd,deepcopy(routes),mandatory=True,warm=warm,cap=cap,scope=f'type_polish_{idx}_{g}_L')
        pL,metaL=m.solve([0,0,0,1],20,20260924+idx*10+ord(g))
        if pL is None:pL=warm;metaL['fallback_to_warm']=True
        cL,eL,_=verify_plan(sd,pL)
        if not cL['all']:raise AssertionError((idx,g,'L',eL[:8]))
        # C stage must preserve the type-specific optimized lateness.
        cap2={'C':global_C,'L':pL['objective'][3]+1e-7}
        m2=JointModel(sd,deepcopy(routes),mandatory=True,warm=pL,cap=cap2,scope=f'type_polish_{idx}_{g}_C')
        pC,metaC=m2.solve([0,0,1,0],20,20260924+idx*10+100+ord(g))
        if pC is None:pC=pL;metaC['fallback_to_stage_L']=True
        cC,eC,_=verify_plan(sd,pC)
        if not cC['all']:raise AssertionError((idx,g,'C',eC[:8]))
        typed[g]=pC
        stages.append({'vehicle':g,'original_objective':original['objective'],'original_type_L':orig_local_L,'L_stage':metaL,'L_objective':pL['objective'],'C_stage':metaC,'C_objective':pC['objective'],'local_checks':cC})
    merged,checks,errors,recalc=merge_plans(data,typed)
    rawcheck=raw_verify(merged,raw)
    if not rawcheck['all']:raise AssertionError((idx,'raw',rawcheck))
    # Ensure no global metric worsened where the type decomposition promises it.
    if merged['objective'][0]>original['objective'][0]+1e-9 or merged['objective'][1]>original['objective'][1]+1e-7 or merged['objective'][2]>original['objective'][2]+2e-5 or merged['objective'][3]>original['objective'][3]+2e-5:
        raise AssertionError((idx,'global objective worsened',original['objective'],merged['objective']))
    out={'index':idx,'source':original.get('source'),'original_objective':original['objective'],'polished_objective':merged['objective'],'routes':merged['routes'],'boxes':merged['boxes'],'objective':merged['objective'],'stages':stages,'production_checks':checks,'production_errors':errors,'recomputed':recalc,'raw_checks':rawcheck,'elapsed':time.perf_counter()-begin}
    save_json(HERE/f'plan_{idx:02d}.json',out)
    save_json(HERE/f'plan_{idx:02d}_solver.json',{'stages':stages,'elapsed':out['elapsed']})
    print(json.dumps({'index':idx,'old':original['objective'],'new':merged['objective'],'elapsed':out['elapsed']},ensure_ascii=False),flush=True)
    return {'index':idx,'old':original['objective'],'new':merged['objective'],'elapsed':out['elapsed'],'raw':rawcheck['all'],'verified':checks['all']}

def main():
    archive=read(ARCH);save_json(HERE/'config.json',{'archive':str(ARCH),'archive_sha256':hashlib.sha256(ARCH.read_bytes()).hexdigest(),'count':len(archive),'vehicles':['A','B','C'],'seconds_per_type_stage':20,'route_choices_fixed':True,'resources_open':True,'global_C_cap_source':'each plan objective[2]','N_policy':'preserve original plan N; no route addition/removal'})
    results=[]
    with ProcessPoolExecutor(max_workers=min(6,len(archive))) as ex:
        fs=[ex.submit(one_plan,i,p) for i,p in enumerate(archive)]
        for f in as_completed(fs):results.append(f.result())
    results.sort(key=lambda x:x['index']);save_json(HERE/'summary.json',{'count':len(results),'results':results,'status':'complete'})
    print('COMPLETE',len(results),flush=True)

if __name__=='__main__':main()
