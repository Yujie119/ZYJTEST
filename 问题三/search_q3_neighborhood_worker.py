"""Bounded single-process Q3 neighborhood worker, restricted to O01 exchange.

CLI: --seconds 6600 --output ABSOLUTE_DIRECTORY --seed INTEGER
     [--task-seconds 90] [--max-rounds INTEGER] [--smoke]

Each MILP uses an explicitly frozen small neighborhood. Its bound never
certifies the larger accumulated library or original continuous problem.
All columns are free; there is no set-cover-then-fixed-schedule claim. Only
plans passing independent DEM, raw-input and battery-location audits are added
to verified_candidates.json. Official submissions are never overwritten.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import itertools
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from q3_common import Context, OUT, load, make_route, save
from solve_q3_global import expand_instances, route_signature, run_direct
from verify_q3 import Verifier
sys.path.insert(0,str(OUT/'审查资料'))
from audit_source_and_result import audit
from battery_location_audit import audit_locations


def now():return datetime.now(timezone.utc).isoformat()


def atomic_json(path,value):
    path=Path(path);temp=path.with_name(path.name+'.tmp')
    save(temp,value);temp.replace(path)


def initial_seeds():
    base=OUT/'搜索精修/扩展固定结构精修_v1'
    summary=load(base/'精修摘要.json');sources=[]
    for record in summary['records']:
        folder=base/record['source']
        sources.append((str(folder/'已核验方案.json'),folder/'独立DEM核验.json',folder/'原始数据结构审计.json'))
    folder=OUT/'全局直接求解/Q2新种子'
    sources.append((str(folder/'1_C_原运输资源次序_已核验方案.json'),folder/'1_C_原运输资源次序_原DEM核验.json',folder/'1_C_原运输资源次序_原始算术核验.json'))
    plans=[];records=[]
    for source,physical,raw in sources:
        p=load(source);v=load(physical);a=load(raw)
        if v.get('status')!='PASS' or a.get('status')!='PASS' or not v.get('passed'):
            raise ValueError(f'Unverified seed source: {source}')
        if not np.allclose(p['objective'],v['objective_recomputed'],atol=2e-4,rtol=0):
            raise ValueError(f'Seed/evidence objective mismatch: {source}')
        p['_worker_seed_source']=source
        plans.append(p);records.append(dict(source=source,objective=p['objective'],physical_evidence=str(physical),raw_evidence=str(raw)))
    return plans,records


def configure_context():
    ctx=Context();ctx.qs=load(OUT/'缓存/中继候选位置.json');geometry=load(OUT/'缓存/区间几何.json')
    if geometry['candidate_count']!=len(ctx.qs):raise ValueError('Geometry/position candidate mismatch')
    ctx.arc_cache={tuple(map(int,k.split(','))):v for k,v in geometry['arcs'].items()}
    ctx.node_cache={int(k):v for k,v in geometry['nodes'].items()}
    return ctx


def neighborhood(ctx,seed,rng,kind):
    """Seed structure plus bounded one/two-route box and vehicle alternatives."""
    patterns={route_signature(r):copy.deepcopy(r) for r in seed['routes']}
    metadata={'kind':kind,'source_route_count':len(seed['routes']),'new_pattern_count':0}
    if kind=='free_joint_retiming':
        routes,library=expand_instances(ctx,list(patterns.values()))
        return routes,dict(metadata,library=library)
    selected=rng.sample(seed['routes'],min(2,len(seed['routes'])))
    remain={}
    for route in selected:
        for c,n in route['counts'].items():remain[c]=remain.get(c,0)+int(n)
    metadata['replaced_route_source_ids']=[r['route_id'] for r in selected]
    base_count=len(patterns)
    def add(g,deliveries):
        if len(patterns)>=base_count+18:return
        sig=(g,tuple((d['zone'],tuple(sorted((c,int(n)) for c,n in d['counts'].items() if n))) for d in deliveries))
        if sig in patterns:return
        candidate=make_route(ctx,g,copy.deepcopy(deliveries),'NEW')
        if candidate is not None:patterns[sig]=candidate
    for route in selected:
        for g in 'ABC':add(g,route['deliveries'])
        if 1<len(route['deliveries'])<=3:
            for perm in itertools.permutations(route['deliveries']):add(route['vehicle'],list(perm))
    by_zone={}
    for c,n in remain.items():by_zone.setdefault(c.split('|')[0],{})[c]=n
    zones=sorted(by_zone)
    for z in zones:
        full={'zone':z,'counts':by_zone[z]}
        for g in 'ABC':add(g,[full])
    # Randomized subgroups target actual residual demand; no battery cargo or
    # invented boxes is introduced. Seed columns stay in the candidate set.
    for _ in range(100):
        if len(patterns)>=base_count+18:break
        choose=rng.sample(zones,min(len(zones),rng.choice([1,1,2])))
        deliveries=[]
        for z in choose:
            counts={c:rng.randint(0,n) for c,n in by_zone[z].items()}
            counts={c:n for c,n in counts.items() if n}
            if counts:deliveries.append({'zone':z,'counts':counts})
        if deliveries:add(rng.choice('ABC'),deliveries)
    routes,library=expand_instances(ctx,list(patterns.values()))
    metadata.update(new_pattern_count=len(patterns)-base_count,library=library)
    return routes,metadata


def cap_scenario(seed,mode,tight):
    values=dict(zip(('N','E','C','L'),map(float,seed['objective'])))
    caps={k:v for k,v in values.items() if k!=mode}
    if not tight:
        slack={'N':1.,'E':.5,'C':180.,'L':100.}
        caps={k:v+slack[k] for k,v in caps.items()}
    return caps


def verify_candidate(plan,folder,label='candidate'):
    """The only route into the worker's verified archive."""
    verifier=Verifier(plan);verifier.verify_routes();verifier.verify_boxes();verifier.verify_relays();physical=verifier.finish()
    raw=audit(plan);locations=audit_locations(plan)
    save(folder/f'{label}_DEM核验.json',physical)
    save(folder/f'{label}_原始算术核验.json',raw)
    save(folder/f'{label}_电池位置核验.json',locations)
    passed=physical.get('passed') and raw.get('status')=='PASS' and locations.get('status')=='PASS'
    return dict(passed=bool(passed),physical_status=physical['status'],raw_status=raw['status'],battery_status=locations['status'],
                physical_checks=len(physical['checks']),raw_checks=len(raw['checks']),battery_checks=locations.get('check_count'),
                evidence=[str(folder/f'{label}_{suffix}.json') for suffix in ('DEM核验','原始算术核验','电池位置核验')])


def update_archive(archive,plan):
    f=np.asarray(plan['objective']);tol=np.array([0.,2e-6,2e-4,2e-4])
    if any(np.all(abs(np.asarray(p['objective'])-f)<=tol) for p in archive):return False
    archive.append(plan);return True


def nondominated(plans):
    tol=np.array([0.,2e-6,2e-4,2e-4])
    return [p for i,p in enumerate(plans) if not any(j!=i and np.all(np.asarray(q['objective'])<=np.asarray(p['objective'])+tol)
           and np.any(np.asarray(q['objective'])<np.asarray(p['objective'])-tol) for j,q in enumerate(plans))]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=6600)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seed',type=int,required=True)
    parser.add_argument('--task-seconds',type=float,default=90)
    parser.add_argument('--max-rounds',type=int,default=100000)
    parser.add_argument('--smoke',action='store_true')
    args=parser.parse_args()
    if not args.output.is_absolute():parser.error('--output must be absolute')
    if args.seconds<=0 or not 0<args.task_seconds<=90:parser.error('positive budget and 0 < task-seconds <= 90 required')
    output=args.output;output.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter();deadline=start+args.seconds
    config=dict(seconds=args.seconds,task_seconds=args.task_seconds,seed=args.seed,output=str(output),started_utc=now(),pid=os.getpid(),
                scope='O01-exchange only; no spare carriage; whole-sortie original energy limits retained',
                bounds_scope='Each bound belongs ONLY to its frozen neighborhood, caps, positions, slots and horizon; never merge with a larger-library lower bound.',
                official_files_modified=False,threads_per_solver=1)
    atomic_json(output/'configuration.json',config)
    atomic_json(output/'progress.json',dict(state='initializing',updated_utc=now(),**config))
    ctx=configure_context();seeds,seed_records=initial_seeds();rng=random.Random(args.seed)
    atomic_json(output/'seed_sources.json',seed_records)
    logs=[];accepted=[];control=None
    atomic_json(output/'verified_candidates.json',[])
    atomic_json(output/'verified_nondominated_candidates.json',[])
    if args.smoke:
        folder=output/'smoke_existing_seed_control';folder.mkdir(exist_ok=True)
        control=verify_candidate(seeds[0],folder,'existing_seed')
        control['meaning']='Existing verified seed, not a new solution discovered by this worker'
        atomic_json(output/'smoke_control.json',control)
        if not control['passed']:raise RuntimeError('Smoke seed failed independent audit')
    for round_no in range(args.max_rounds):
        remaining=deadline-time.perf_counter()
        if remaining<3 or (output/'STOP').exists():break
        # Alternate new verified structures and original sources. Duplicate
        # seed goals remain useful only as distinct route/relay structures.
        population=seeds+nondominated(accepted)
        seed=population[round_no%len(population)] if round_no<len(population) else rng.choice(population)
        mode=('C','E','L','N')[round_no%4]
        kind='free_joint_retiming' if round_no%3==0 else 'two_route_box_vehicle_neighborhood'
        folder=output/f'round_{round_no:05d}_{mode}';folder.mkdir(exist_ok=True)
        task_deadline=min(deadline,time.perf_counter()+args.task_seconds)
        record=dict(round=round_no,mode=mode,kind=kind,started_utc=now(),seed_objective=seed['objective'],
                    seed_source=seed.get('_worker_seed_source',seed.get('_worker_verified_path')),status='running')
        atomic_json(output/'progress.json',dict(state='building_neighborhood',updated_utc=now(),elapsed_s=time.perf_counter()-start,
                    round=round_no,new_verified_count=len(accepted),latest=record,scope=config['scope']))
        try:
            routes,info=neighborhood(ctx,seed,rng,kind)
            save(folder/'neighborhood_manifest.json',info)
            caps=cap_scenario(seed,mode,tight=(round_no%2==0))
            loaded={r['route_id'] for r in routes}
            pairs={tuple(sorted((a['route_id'],b['route_id']))) for a,b in itertools.combinations(routes,2) if a['vehicle']==b['vehicle']}
            # Fully loaded small neighborhoods avoid falsely accepting a
            # communication-free incumbent. The direct-loop validator still
            # rejects any omitted/conflicting block before candidate output.
            allowance=max(.1,task_deadline-time.perf_counter()-min(5.,args.task_seconds*.2))
            atomic_json(output/'progress.json',dict(state='solving_neighborhood',updated_utc=now(),elapsed_s=time.perf_counter()-start,
                        round=round_no,new_verified_count=len(accepted),route_instances=len(routes),latest=record,scope=config['scope']))
            result=run_direct(ctx,routes,seconds=allowance,round_seconds=allowance,mode=mode,caps=caps,
                              output_dir=folder,loaded_ids=loaded,pair_keys=pairs)
            record.update(status=result['status'],route_instances=len(routes),patterns=info['library']['patterns'],caps=caps,
                          neighborhood_only_lower_bound=result['finite_model_valid_lower_bound'],
                          lower_bound_scope='This round frozen neighborhood only; not the accumulated full route library.',
                          solver_elapsed_s=result['elapsed_s'])
            candidate=result.get('candidate_plan')
            if candidate is not None:
                candidate['source']='bounded_neighborhood_joint_MILP'
                candidate['expert_rule_scope']=config['scope']
                verification=verify_candidate(candidate,folder)
                record['independent_verification']=verification
                if verification['passed']:
                    candidate['status']='triple_verified_O01_strategy_neighborhood_candidate'
                    candidate['_worker_verified_path']=str(folder/'verified_plan.json')
                    save(folder/'verified_plan.json',candidate)
                    save(folder/'已核验方案.json',candidate)
                    fresh=update_archive(accepted,candidate)
                    record.update(status='verified_candidate',objective=candidate['objective'],new_objective=fresh)
                else:
                    record['status']='rejected_by_independent_audit'
                    save(folder/'rejected_candidate.json',candidate)
            else:record['accepted_as_feasible']=False
        except Exception as error:
            record.update(status='error',error=type(error).__name__+': '+str(error))
            import traceback
            (folder/'error_trace.txt').write_text(traceback.format_exc(),encoding='utf8')
        record['finished_utc']=now();logs.append(record)
        save(folder/'round_record.json',record)
        atomic_json(output/'attempts.json',logs)
        atomic_json(output/'verified_candidates.json',accepted)
        atomic_json(output/'verified_nondominated_candidates.json',nondominated(accepted))
        atomic_json(output/'progress.json',dict(state='round_complete',updated_utc=now(),elapsed_s=time.perf_counter()-start,
                    round=round_no,new_verified_count=len(accepted),latest=record,scope=config['scope']))
        print(json.dumps(record,ensure_ascii=False),flush=True)
    summary=dict(state='completed',updated_utc=now(),elapsed_s=time.perf_counter()-start,rounds=len(logs),
                 new_verified_count=len(accepted),new_nondominated_count=len(nondominated(accepted)),
                 existing_seed_count=len(seeds),smoke_control=control,attempts=logs,scope=config['scope'],
                 bounds_scope=config['bounds_scope'],original_global_optimality_claim=False,
                 stop_requested=(output/'STOP').exists(),physical_verification_may_finish_after_solver_budget=True)
    atomic_json(output/'summary.json',summary);atomic_json(output/'progress.json',summary)
    print('NEIGHBORHOOD_WORKER_DONE',len(logs),'ROUNDS',len(accepted),'VERIFIED',str(output),flush=True)
    return 0 if not args.smoke or control['passed'] and bool(logs) and not any(x['status']=='error' for x in logs) else 2


if __name__=='__main__':raise SystemExit(main())
