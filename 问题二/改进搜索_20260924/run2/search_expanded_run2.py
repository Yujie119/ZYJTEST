"""Versioned multi-start search, general route expansion and joint MILP repair.

Reuses the audited physics and joint matrix; never overwrites earlier results.
All search limits are algorithm budgets, not physical feasibility rules.
"""
from __future__ import annotations
import os
for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:
    os.environ[k]='1'
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
os.environ['PYTHONUTF8']='1'
import argparse,gzip,hashlib,itertools,json,math,random,sys,time
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
Q2=HERE.parent.parent
sys.path.insert(0,str(Q2))
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from q2_data import load_data,make_route,save_json,decode
from q2_joint import JointModel,archive_add,vertices,dominates
from q2_candidates import construct_initial,single_point_catalog
from q2_verify import verify_plan

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def validate(data,p):
    if p is None:return False
    checks,errors,_=verify_plan(data,p)
    if not checks['all']:raise AssertionError(errors[:5])
    return True

def digest(routes):
    props=['candidate_id','vehicle','events','box_ids','energy','duration','charge_s','offsets','latest_start']
    raw=[{k:r[k] for k in props} for r in sorted(routes,key=lambda r:r['candidate_id'])]
    return hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def build(data,attempts):
    start=time.perf_counter()
    catalog,stats=single_point_catalog(data)
    pool={r['candidate_id']:r for r in catalog}
    for r in read(Q2/'子问题一/联合候选库.json'):
        rr=make_route(data,r['vehicle'],r['events'])
        if rr:pool[rr['candidate_id']]=rr
    rng=random.Random(20260924)
    zboxes=defaultdict(list)
    for b,v in data['boxes'].items():zboxes[v['zone']].append(b)
    zones=sorted(zboxes)
    neighbors={z:sorted([v for v in zones if v!=z],key=lambda v:data['geos'][z,v]['distance']) for z in zones}
    multi=Counter()
    for it in range(attempts):
        n=rng.choices([2,3,4,5],[.6,.25,.1,.05])[0]
        origin=rng.choice(zones)
        near=neighbors[origin][:8] if it%3 else neighbors[origin]
        visits=[origin]+rng.sample(near,n-1)
        rng.shuffle(visits)
        events=[]
        for z in visits:
            count=rng.choices([1,2,3],[.65,.25,.10])[0]
            bs=rng.sample(zboxes[z],min(count,len(zboxes[z])))
            events.append(dict(zone=z,boxes=bs))
        g=rng.choice(list(data['vehicles']))
        route=make_route(data,g,events,multi)
        if route:pool[route['candidate_id']]=route
    vals=list(pool.values())
    with gzip.open(HERE/'expanded_candidates.json.gz','wt',encoding='utf-8') as f:
        json.dump(vals,f,ensure_ascii=False)
    save_json(HERE/'candidate_scope.json',dict(single_count=len(catalog),total=len(vals),
        attempts=attempts,multi_stats=multi,visits=Counter(len(r['events']) for r in vals),
        types=Counter(r['vehicle'] for r in vals),coefficient_sha256=digest(vals),
        assumptions='Same q2_data physics and event-completion delivery assumptions as audited source.',
        complete=False,seconds=time.perf_counter()-start,input_manifest=data['manifest']))
    return vals

def worker(task):
    idx,steps,seconds,initials=task
    rng=random.Random(20261024+idx)
    data=load_data()
    with gzip.open(HERE/'expanded_candidates.json.gz','rt',encoding='utf-8') as f:pool=json.load(f)
    for r in pool:
        for key in ['route_id','start','uav','battery_id','takeoff','finish','recharge']:
            r.pop(key,None)
        if r['latest_start'] is None:r['latest_start']=math.inf
    sets={r['candidate_id']:set(r['box_ids']) for r in pool}
    scales=np.asarray(read(Q2/'冻结评价配置.json')['scale'])
    pref=[[.25,.25,.25,.25],[.1,.1,.55,.25],[.1,.1,.25,.55],
          [.4,.3,.2,.1],[.1,.5,.25,.15],[.25,.1,.5,.15]][idx%6]
    coeff=np.asarray(pref)/scales
    inherited=read(HERE.parent/'联合非支配档案.json')
    inherited.append(read(Q2/'源头核查_20260924/implementation/fixed_resources_timing_witness.json')['plan'])
    resource_best=HERE.parent/'固定箱组全资源/best_plan.json'
    if resource_best.exists():inherited.append(read(resource_best))
    archive=[]
    for p in inherited:
        validate(data,p);archive_add(archive,p)
    singletons=[r for r in pool if r['nbox']==1]
    canonical={r['candidate_id']:r for r in pool}
    important={r['candidate_id']:canonical[r['candidate_id']] for p in inherited for r in p['routes']}
    important.update({r['candidate_id']:r for r in singletons})
    for j in range(initials):
        local=dict(important)
        for r in rng.sample(pool,min(1800,len(pool))):local[r['candidate_id']]=r
        p=construct_initial(data,list(local.values()),20260924+idx*10000+j,j%4)
        if validate(data,p):archive_add(archive,p)
    current=min(archive,key=lambda p:float(coeff@p['objective']))
    logs=[];discovered={}
    begin=time.perf_counter()
    for step in range(steps):
        # Periodic restart from a different verified Pareto schedule.
        if step and step%12==0:current=rng.choice(archive)
        routes=current['routes'];n=min(rng.choice([4,5,6,8,10]),len(routes))
        op=step%6
        if op==0:released=rng.sample(routes,n)
        elif op==1:
            scores={r['candidate_id']:sum(data['boxes'][b]['priority']*max(0.,r['start']+r['offsets'][b]-data['boxes'][b]['expected']) for b in r['box_ids']) for r in routes}
            released=sorted(routes,key=lambda r:(scores[r['candidate_id']],rng.random()),reverse=True)[:n]
        elif op==2:
            u=rng.choice(routes)['uav'];released=[r for r in routes if r['uav']==u]
            rest=[r for r in routes if r not in released]
            released+=rng.sample(rest,max(0,min(n-len(released),len(rest))))
        elif op==3:
            b=rng.choice(routes)['battery_id'];released=[r for r in routes if r['battery_id']==b]
            rest=[r for r in routes if r not in released]
            released+=rng.sample(rest,max(0,min(n-len(released),len(rest))))
        elif op==4:
            z=rng.choice(routes)['zones'][0]
            released=sorted(routes,key=lambda r:min(0. if q==z else data['geos'][z,q]['distance'] for q in r['zones']))[:n]
        else:released=sorted(routes,key=lambda r:r['finish'],reverse=True)[:n]
        boxes={b for r in released for b in r['box_ids']}
        eligible=[r for r in pool if sets[r['candidate_id']]<=boxes]
        # Add mixed-delivery routes from the current released groups, all orders.
        for _ in range(50):
            picked=rng.sample(released,min(len(released),rng.choice([2,2,3])))
            ev=[];byz=defaultdict(list)
            for r in picked:
                for e in r['events']:byz[e['zone']]+=e['boxes']
            zs=list(byz);rng.shuffle(zs)
            if len(zs)<2:continue
            ev=[dict(zone=z,boxes=byz[z]) for z in zs]
            r=make_route(data,rng.choice(list(data['vehicles'])),ev)
            if r:
                eligible.append(r);discovered[r['candidate_id']]=r
        # Common schedules stay present, but all their times/resources remain free.
        subset={r['candidate_id']:r for r in routes}
        must=[r for r in eligible if r['nbox']==1]
        for r in must:subset[r['candidate_id']]=r
        rankings=[sorted(eligible,key=lambda r:r['energy']/r['nbox']),
                  sorted(eligible,key=lambda r:r['duration']/r['nbox']),
                  sorted(eligible,key=lambda r:-r['nbox'])]
        for rank in rankings:
            for r in rank[:12]:subset[r['candidate_id']]=r
        others=[r for r in eligible if r['candidate_id'] not in subset]
        for r in rng.sample(others,min(45,len(others))):subset[r['candidate_id']]=r
        # Exploration is real: an explicitly forced new column can exclude the
        # current schedule, so warm fallback cannot silently cancel a worse move.
        explore=(step%5==4 and bool(others))
        forced=None
        if explore:
            options=[r for r in subset.values() if r['candidate_id'] not in {q['candidate_id'] for q in routes} and r['nbox']>1]
            if options:forced=rng.choice(options)['candidate_id']
        cap={}
        if not forced:
            cap['C']=float(coeff@current['objective'])/coeff[2]+1e-5
        model=JointModel(data,deepcopy(list(subset.values())),warm=None if forced else current,
            cap=cap,scope=f'expanded_worker_{idx}_step_{step}')
        if forced:
            var=model.x[model.index[forced]];model.lb[var]=model.ub[var]=1.
        p,meta=model.solve(coeff,seconds=seconds,seed=20260924+idx*1000+step)
        accepted=False
        if validate(data,p):
            p['source']=f'expanded_worker_{idx}_step_{step}';archive_add(archive,p)
            delta=float(coeff@(np.asarray(p['objective'])-np.asarray(current['objective'])))
            accepted=delta<=1e-8 or (forced is not None and rng.random()<math.exp(min(0.,-delta/(.12*.97**step))))
            if accepted:current=p
        logs.append(dict(step=step,operator=op,released_count=len(released),columns=len(subset),
            forced_candidate=forced,accepted=accepted,objective=p['objective'] if p else None,solver=meta))
        if step%5==0 or step==steps-1:
            save_json(HERE/f'worker_{idx}_archive.json',archive)
            save_json(HERE/f'worker_{idx}_log.json',logs)
            print(f'WORKER {idx} step {step+1}/{steps} archive {len(archive)} F {current["objective"]}',flush=True)
    save_json(HERE/f'worker_{idx}_discovered.json',list(discovered.values()))
    return dict(worker=idx,archive=len(archive),steps=steps,initialization_attempts=initials,
        seconds=time.perf_counter()-begin,weights=pref)

def collect():
    data=load_data();archive=[]
    for file in sorted(HERE.glob('worker_*_archive.json')):
        for p in read(file):
            validate(data,p);archive_add(archive,p)
    for file in [HERE/'固定箱组全资源/最终方案.json',HERE/'固定箱组全资源/best_plan.json']:
        if file.exists():
            p=read(file);p=p.get('plan',p)
            if validate(data,p):archive_add(archive,p)
    # Terminal polishing is mandatory for every archived representative.
    polished=[];logs=[]
    for i,p in enumerate(archive):
        cap=dict(zip('NECL',p['objective']))
        model=JointModel(data,deepcopy(p['routes']),mandatory=True,fixed_resources=True,
            warm=p,cap=cap,scope=f'archive_terminal_{i}')
        q,m=model.solve([0,0,0,1],5,20260924+i)
        if validate(data,q):
            q['source']=f'terminal_of_{p.get("source",i)}';archive_add(polished,q)
        else:archive_add(polished,p)
        logs.append(m)
    archive=polished
    with gzip.open(HERE/'expanded_candidates.json.gz','rt',encoding='utf-8') as f:pool=json.load(f)
    routes={r['candidate_id']:r for r in pool}
    for file in HERE.glob('worker_*_discovered.json'):
        for r in read(file):routes[r['candidate_id']]=r
    for p in archive:
        for r in p['routes']:routes[r['candidate_id']]=r
    pool=list(routes.values())
    # A resource-workload set-partition LP is a valid relaxation of this entire
    # expanded route library. Earlier K0 lower bounds are deliberately not reused.
    boxes=list(data['boxes']);bi={b:i for i,b in enumerate(boxes)}
    rows=[];cols=[];vals=[]
    for j,r in enumerate(pool):
        for b in r['box_ids']:rows.append(bi[b]);cols.append(j);vals.append(1.)
    neq=len(pool)+1
    Aeq=coo_matrix((vals,(rows,cols)),shape=(len(boxes),neq)).tocsr()
    Aub=np.zeros((len(data['vehicles']),neq))
    for i,g in enumerate(data['vehicles']):
        for j,r in enumerate(pool):
            if r['vehicle']==g:Aub[i,j]=r['duration']
        Aub[i,-1]=-sum(v==g for v in data['uavs'].values())
    scales=np.asarray(read(Q2/'冻结评价配置.json')['scale'])
    weights=vertices((.25,)*4,.3);bases=[]
    library_hash=digest(pool)
    for w in weights:
        coeff=w/scales
        c=np.asarray([coeff[0]+coeff[1]*r['energy'] for r in pool]+[coeff[2]])
        result=linprog(c,A_ub=Aub,b_ub=np.zeros(len(Aub)),A_eq=Aeq,b_eq=np.ones(len(boxes)),
            bounds=[(0,1)]*len(pool)+[(0,None)],method='highs',options={'time_limit':60.})
        lower=float(result.fun) if result.success else 0.
        upper=min(float(coeff@p['objective']) for p in archive)
        if lower>upper+1e-6:raise AssertionError('invalid expanded LP bound')
        bases.append(dict(weight=w.tolist(),coefficients=coeff.tolist(),lower=lower,upper=upper,
            status=result.message,scope='expanded library box-cover and per-type UAV workload relaxation; L relaxed to zero',
            library_coefficient_sha256=library_hash))
    for p in archive:
        scores=[float(np.asarray(b['coefficients'])@p['objective']) for b in bases]
        p['regret_lower']=max(0.,max(v-b['upper'] for v,b in zip(scores,bases)))
        p['regret_upper']=max(v-b['lower'] for v,b in zip(scores,bases))
    archive.sort(key=lambda p:(p['regret_upper'],p['objective'][2],p['objective'][3]))
    final=archive[0]
    save_json(HERE/'联合非支配档案.json',archive)
    save_json(HERE/'最终方案.json',final)
    save_json(HERE/'terminal_polish.json',logs)
    save_json(HERE/'偏好极点基准_扩大库松弛.json',bases)
    with gzip.open(HERE/'frozen_evaluation_candidates.json.gz','wt',encoding='utf-8') as f:json.dump(pool,f,ensure_ascii=False)
    checks,errors,recomputed=verify_plan(data,final)
    save_json(HERE/'独立核验.json',dict(checks=checks,errors=errors,recomputed=recomputed))
    save_json(HERE/'汇总.json',dict(archive_count=len(archive),objective=final['objective'],
        regret_interval=[final['regret_lower'],final['regret_upper']],route_count=len(pool),
        library_coefficient_sha256=library_hash,scope='Expanded finite-library heuristic search with certified relaxation lower bounds; no full-route optimum claim',
        physics='Same audited q2_data physical assumptions; no parameter tuning against external answers',
        frozen_scale=scales.tolist(),status='completed'))
    print('COLLECTED',len(archive),final['objective'],flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--collect-only',action='store_true')
    parser.add_argument('--reuse-candidates',action='store_true')
    parser.add_argument('--workers',type=int,default=6);parser.add_argument('--steps',type=int,default=40)
    parser.add_argument('--seconds',type=float,default=3.);parser.add_argument('--initials',type=int,default=40)
    parser.add_argument('--attempts',type=int,default=24000);args=parser.parse_args()
    if args.collect_only:collect();return
    start=time.perf_counter();data=load_data()
    if args.reuse_candidates:
        with gzip.open(HERE/'expanded_candidates.json.gz','rt',encoding='utf-8') as f:pool=json.load(f)
    else:pool=build(data,args.attempts)
    save_json(HERE/'search_config.json',dict(vars(args),seed=20260924,threads_per_solver=1,
        hardware_parallelism='Independent CPU MILP workers; both GPUs reserved for batch coefficient verification',
        source_hashes={name:hashlib.sha256((Q2/name).read_bytes()).hexdigest() for name in ['q2_data.py','q2_joint.py','q2_verify.py']}))
    print('CANDIDATES',len(pool),flush=True)
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        jobs=[executor.submit(worker,(i,args.steps,args.seconds,args.initials)) for i in range(args.workers)]
        results=[future.result() for future in as_completed(jobs)]
    save_json(HERE/'worker_summary.json',results)
    collect()
    save_json(HERE/'runtime.json',dict(wall_seconds=time.perf_counter()-start,workers=args.workers))

if __name__=='__main__':main()

