"""Independent full-library set partitioning + actual dual-resource scheduling.

Master workload is only a search proxy. Only verify_plan-passing schedules are
admitted to the delivered archive. No route-count equality is imposed.
"""
from __future__ import annotations
import os
for key in ['OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS']:
    os.environ[key] = '1'
os.environ['MKL_THREADING_LAYER'] = 'SEQUENTIAL'
import gzip, hashlib, json, math, random, sys, time
from pathlib import Path
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from scipy.optimize._highspy import _core as hc
from scipy.sparse import coo_matrix

HERE = Path(__file__).resolve().parent
Q2 = HERE.parents[1]
sys.path.insert(0, str(Q2))
from q2_data import load_data, decode, save_json
from q2_joint import JointModel, archive_add
from q2_verify import verify_plan
SOURCE = Q2 / '改进搜索_20260924'

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def master(data, pool, spec, rng):
    n = len(pool); rows=[]; low=[]; high=[]
    coverage={b:[] for b in data['boxes']}
    for i,r in enumerate(pool):
        for b in r['box_ids']: coverage[b].append(i)
    for b,ids in coverage.items():
        rows.append({i:1. for i in ids});low.append(1.);high.append(1.)
    for g in data['vehicles']:
        m=sum(t==g for t in data['uavs'].values())
        row={i:r['duration'] for i,r in enumerate(pool) if r['vehicle']==g}
        row[n]=-m;rows.append(row);low.append(-np.inf);high.append(0.)
        # Necessary cumulative workload cuts on route-implied completion limits.
        for cutoff in [1800.,2400.,3000.,3600.,4200.,4800.,5400.,6000.,7200.]:
            row={i:r['duration'] for i,r in enumerate(pool) if r['vehicle']==g
                 and r['latest_start'] is not None and r['latest_start']+r['duration']<=cutoff+1e-8}
            if row: rows.append(row);low.append(-np.inf);high.append(m*cutoff)
    for label,cap in spec.get('cap',{}).items():
        row={i:(1. if label=='N' else r['energy']) for i,r in enumerate(pool)}
        rows.append(row);low.append(-np.inf);high.append(float(cap))
    rr=[];cc=[];vv=[]
    for j,row in enumerate(rows):
        for i,v in row.items():rr.append(j);cc.append(i);vv.append(v)
    A=coo_matrix((vv,(rr,cc)),shape=(len(rows),n+1)).tocsc()
    wn,we,wc=spec['weights']
    cost=np.array([wn/25+we*r['energy']/70 for r in pool]+[wc/7000.])
    # Log-seeded small perturbation makes independent cover patterns, not a
    # claimed objective of the actual transportation model.
    cost[:n] += np.array([rng.uniform(0,spec.get('noise',0.001)) for _ in pool])
    lp=hc.HighsLp();lp.num_col_=n+1;lp.num_row_=len(rows)
    lp.col_cost_=cost;lp.col_lower_=np.zeros(n+1);lp.col_upper_=np.r_[np.ones(n),50000.]
    lp.row_lower_=np.asarray(low);lp.row_upper_=np.asarray(high)
    lp.a_matrix_.num_col_=n+1;lp.a_matrix_.num_row_=len(rows)
    lp.a_matrix_.format_=hc.MatrixFormat.kColwise
    lp.a_matrix_.start_=A.indptr.astype(np.int32);lp.a_matrix_.index_=A.indices.astype(np.int32);lp.a_matrix_.value_=A.data
    lp.integrality_=[hc.HighsVarType.kInteger]*n+[hc.HighsVarType.kContinuous]
    h=hc._Highs()
    for k,v in [('output_flag',False),('threads',1),('time_limit',spec['master_seconds']),
                ('mip_rel_gap',0.003),('mip_feasibility_tolerance',1e-8),('random_seed',spec['seed'])]:h.setOptionValue(k,v)
    h.passModel(lp)
    byid={r['candidate_id']:i for i,r in enumerate(pool)}
    inherited=read(SOURCE/'联合非支配档案.json')
    if (HERE/'initial_archive.json').exists(): inherited+=read(HERE/'initial_archive.json')
    warm=None;warm_cost=math.inf
    for plan in inherited:
        if any(r['candidate_id'] not in byid for r in plan['routes']):continue
        xx=np.zeros(n+1)
        for r in plan['routes']:xx[byid[r['candidate_id']]]=1.
        xx[n]=max(sum(r['duration'] for r in plan['routes'] if r['vehicle']==g)/sum(t==g for t in data['uavs'].values()) for g in data['vehicles'])
        ax=A@xx
        if max(float(np.max(np.asarray(low)-ax)),float(np.max(ax-np.asarray(high))))>2e-5:continue
        score=float(cost@xx)
        if score<warm_cost:warm=xx;warm_cost=score
    if warm is not None:
        solwarm=hc.HighsSolution();solwarm.col_value=warm;solwarm.value_valid=True;h.setSolution(solwarm)
    h.run();sol=h.getSolution();info=h.getInfo()
    meta={'status':h.modelStatusToString(h.getModelStatus()),'objective_proxy':float(info.objective_function_value),
          'proxy_dual_bound':float(info.mip_dual_bound),'proxy_not_actual_completion':True,'master_warm_start':warm is not None}
    if not sol.value_valid:return None,meta
    x=np.array(sol.col_value);ax=A@x
    resid=max(float(np.max(np.asarray(low)-ax)),float(np.max(ax-np.asarray(high))),
              float(np.max(abs(x[:n]-np.rint(x[:n])))),float(np.max(-x)),float(np.max(x[:n]-1)))
    meta['residual']=resid
    if resid>2e-5:return None,meta
    routes=[deepcopy(r) for i,r in enumerate(pool) if x[i]>.5]
    meta.update(N=len(routes),E=sum(r['energy'] for r in routes),workload_proxy=float(x[n]),
                selected_candidate_ids=[r['candidate_id'] for r in routes])
    return routes,meta

def greedy(data, routes, rng, weights):
    best=None;bestscore=math.inf
    for k in range(220):
        decorated=[]
        for r in routes:
            latest = r['latest_start'] if r['latest_start'] is not None else 18000.
            soft=min((data['boxes'][b]['expected']-r['offsets'][b] for b in r['box_ids']),default=18000.)
            key=min(latest,soft*(1+rng.random()*.4)) if k%3 else latest
            key+=rng.uniform(-650.,650.) if k else 0.
            decorated.append((key,r))
        ua={u:0. for u in data['uavs']};ba={b:0. for b in data['batteries']};out=[];bad=False
        for _,r in sorted(decorated,key=lambda t:t[0]):
            us=[u for u,g in data['uavs'].items() if g==r['vehicle']]
            bs=[b for b,g in data['batteries'].items() if g==r['vehicle']]
            u=min(us,key=ua.get);b=min(bs,key=ba.get);start=max(ua[u],ba[b])
            if r['latest_start'] is not None and start>r['latest_start']+1e-7:bad=True;break
            q=deepcopy(r);q.update(start=start,uav=u,battery_id=b);out.append(q)
            ua[u]=start+r['duration'];ba[b]=ua[u]+r['charge_s']
        if bad:continue
        p=decode(data,out);score=sum(a*b for a,b in zip(weights,p['objective']))
        if score<bestscore:best=p;bestscore=score
    return best

def worker(spec):
    begin=time.perf_counter();data=load_data();rng=random.Random(spec['seed'])
    with gzip.open(SOURCE/'frozen_evaluation_candidates.json.gz','rt',encoding='utf-8') as f:pool=json.load(f)
    routes,meta=master(data,pool,spec,rng)
    result={'spec':spec,'master':meta,'plan':None,'scheduling':None,'verification':None}
    if routes:
        weights=spec['schedule_weights'];warm=greedy(data,routes,rng,weights)
        model=JointModel(data,routes,mandatory=True,warm=warm,scope='fixed_cover_actual_resource_schedule')
        plan,sm=model.solve(weights,seconds=spec['schedule_seconds'],seed=spec['seed'])
        result['scheduling']=sm
        if plan:
            checks,errors,extra=verify_plan(data,plan)
            result['verification']=dict(checks=checks,errors=errors,recomputed=extra)
            if checks['all']:
                plan['source']='full_library_cover_'+spec['name'];result['plan']=plan
            else:result['verification_failure']=True
    result['seconds']=time.perf_counter()-begin
    save_json(HERE/(spec['name']+'.json'),result)
    print(spec['name'],result['plan']['objective'] if result['plan'] else None,
          meta['status'],(result['scheduling'] or {}).get('status'),flush=True)
    return result

def main():
    start=time.perf_counter();HERE.mkdir(parents=True,exist_ok=True)
    specs=[]
    caps=[{}, {'N':20},{'N':21},{'N':22},{'N':23},{'N':24},{'N':25},{'N':26}]
    for j,cap in enumerate(caps):
        for k,(w,s) in enumerate([([.10,.15,.75],[0,0,1/7000.,.3/600.]),
                                  ([.25,.50,.25],[0,0,.65/7000.,.35/600.]),
                                  ([.05,.25,.70],[0,0,.25/7000.,.75/600.])]):
            specs.append(dict(name=f'cover_{j:02d}_{k}',cap=cap,weights=w,schedule_weights=s,
                              noise=.0008*(k+1),seed=2026092400+j*10+k,master_seconds=12.,schedule_seconds=12.))
    save_json(HERE/'config.json',{'specs':specs,'route_count_fixed':False,'working_columns_file':str(SOURCE/'frozen_evaluation_candidates.json.gz'),
        'candidate_file_sha256':hashlib.sha256((SOURCE/'frozen_evaluation_candidates.json.gz').read_bytes()).hexdigest(),
        'scope':'Finite full available library; only O01 battery exchanges; no carried spare or remote stock assumed.'})
    archive=[];logs=[]
    with ProcessPoolExecutor(max_workers=4) as ex:
        for f in as_completed([ex.submit(worker,s) for s in specs]):
            r=f.result();logs.append({k:v for k,v in r.items() if k!='plan'})
            if r['plan']:archive_add(archive,r['plan'])
            save_json(HERE/'archive.json',archive);save_json(HERE/'solver_log.json',logs)
    save_json(HERE/'summary.json',{'seconds':time.perf_counter()-start,'jobs':len(specs),
        'successful_actual_schedules':sum(x.get('verification',{}).get('checks',{}).get('all',False) if x.get('verification') else 0 for x in logs),
        'nondominated':len(archive),'objectives':[p['objective'] for p in archive]})

if __name__=='__main__':main()
