"""Global joint MILP first; adaptive epsilon and ALNS as a controlled contrast."""
from __future__ import annotations
import os
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['MKL_NUM_THREADS']='1'
import argparse,gzip,hashlib,itertools,json,math,random,time
from copy import deepcopy
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import numpy as np
from q2_data import OUT,load_data,load_baseline,make_route,save_json
from q2_joint import JointModel,archive_add,vertices,dominates,OBJ_TOL
from q2_candidates import single_point_catalog,global_pool,construct_initial
from q2_verify import verify_plan

def valid(data,p):
    if p is None:return False
    checks,errors,_=verify_plan(data,p)
    if not checks['all']:raise ValueError('Joint incumbent failed independent verification: '+repr(errors[:6]))
    return True

def run_job(data,pool,warm,job):
    begin=time.perf_counter();cap=dict(job.get('cap',{}));logs=[]
    if warm and 'weights' in job and job['weights'][2]>0 and not job.get('relax'):
        # Safe incumbent objective sublevel: all four physical objectives >= 0.
        implied=float(np.array(job['weights'])@warm['objective'])/job['weights'][2]
        cap['C']=min(cap.get('C',math.inf),implied+OBJ_TOL[2])
    model=JointModel(data,deepcopy(pool),warm=warm,cap=cap,scope=job['label'])
    for j,lower in enumerate(job.get('objective_lower_bounds',[])):
        model.add(model.f[j],low=lower)
    if job.get('objective_lower_bounds'):model.compile()
    if job.get('relax'):
        p,meta=model.solve(job['weights'],seconds=job['seconds'],seed=job['seed'],relax=True);logs=[meta]
    elif 'order' in job:p,logs=model.lexsolve(job['order'],seconds=job['seconds'],seed=job['seed'])
    else:p,meta=model.solve(job['weights'],seconds=job['seconds'],seed=job['seed']);logs=[meta]
    if p is not None:
        valid(data,p);p['source']=job['label']
    return p,dict(job=job,stages=logs,wall_seconds=time.perf_counter()-begin)

def batch(data,pool,jobs,archive,log,workers):
    answers=[];completed={}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        pending={}
        for job in jobs:
            eligible=[p for p in archive if all(p['objective']['NECL'.index(k)]<=v+OBJ_TOL['NECL'.index(k)] for k,v in job.get('cap',{}).items())]
            if eligible:
                key=(lambda p:tuple(p['objective'][j] for j in job['order'])) if 'order' in job else (lambda p:float(np.asarray(job['weights'])@p['objective']))
                warm=min(eligible,key=key)
            else:warm=None
            pending[executor.submit(run_job,data,pool,warm,job)]=job
        for f in as_completed(pending):
            p,meta=f.result();completed[meta['job']['label']]=(p,meta)
            print('JOB',meta['job']['label'],'F=',p['objective'] if p else None,'status=',[m['status'] for m in meta['stages']],flush=True)
    # Stable acceptance order; worker completion time does not break equal ties.
    for job in jobs:
        p,meta=completed[job['label']];log.append(meta)
        if p:archive_add(archive,p);answers.append(p)
    return answers

def alns_compare(data,pool,base,config):
    rng=random.Random(config['seed']);ops=['random','deadline','battery','energy'];scores=np.ones(4);uses=np.zeros(4);rewards=np.zeros(4)
    arc=[deepcopy(base)];current=deepcopy(base);log=[];scale=np.array([max(1,base['objective'][0]),max(1,base['objective'][1]),max(1,base['objective'][2]),max(1,base['objective'][3])])
    start=time.perf_counter()
    for it in range(config['alns_iterations']):
        probabilities=scores/scores.sum();op=rng.choices(range(4),weights=probabilities,k=1)[0];uses[op]+=1
        rs=current['routes'];n=min(config['destroy_route_count'],len(rs))
        if ops[op]=='random':released=rng.sample(rs,n)
        elif ops[op]=='deadline':released=sorted(rs,key=lambda r:(r['latest_start'] if r['latest_start'] is not None else math.inf)-r['start'])[:n]
        elif ops[op]=='battery':released=sorted(rs,key=lambda r:r['charge_s'],reverse=True)[:n]
        else:released=sorted(rs,key=lambda r:r['energy'],reverse=True)[:n]
        released_ids={r['candidate_id'] for r in released};boxids={b for r in released for b in r['box_ids']}
        fixed={r['candidate_id']:r for r in rs if r['candidate_id'] not in released_ids}
        alternatives=[r for r in pool if set(r['box_ids'])<=boxids]
        # Neighborhood budget, not a restriction on the primary global MILP.
        rng.shuffle(alternatives);alts={r['candidate_id']:r for r in alternatives[:65]}
        alts.update({r['candidate_id']:r for r in released});alts.update(fixed)
        model=JointModel(data,list(alts.values()),fixed=fixed,warm=current,scope=f'ALNS-local-{it}')
        p,stages=model.lexsolve(seconds=config['alns_seconds'],seed=config['seed']+it)
        accepted=False;gain=False;reward=0.
        if valid(data,p):
            gain=archive_add(arc,p);delta=(p['objective'][2]-current['objective'][2])/scale[2]
            same=abs(delta)<=OBJ_TOL[2]/scale[2]
            better=tuple(p['objective'][j] for j in [2,3,1,0])<tuple(current['objective'][j] for j in [2,3,1,0])
            temp=config['initial_temperature']*config['cooling']**it
            accepted=better or (not same and rng.random()<math.exp(min(0.,-delta/temp)))
            if accepted:current=p
            reward=8. if gain else 4. if better else 1. if accepted else .1
        rewards[op]+=reward
        if (it+1)%3==0:
            for j in range(4):
                if uses[j]>0:scores[j]=max(config['operator_floor'],(1-config['operator_reaction'])*scores[j]+config['operator_reaction']*rewards[j]/uses[j])
            uses[:]=0;rewards[:]=0
        log.append(dict(iteration=it,operator=ops[op],probabilities=probabilities.tolist(),scores=scores.tolist(),accepted=accepted,new_nondominated=gain,
                        objective=p['objective'] if p else None,released=list(released_ids),stages=stages))
        print('ALNS',it,ops[op],p['objective'] if p else None,flush=True)
    return arc,log,time.perf_counter()-start

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=OUT/'联合求解配置.json');args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding='utf-8'));start=time.perf_counter();data=load_data()
    base=load_baseline(data);valid(data,base)
    # Independent exact replication of the report's fixed-resources counterexample.
    model=JointModel(data,deepcopy(base['routes']),mandatory=True,warm=base,fixed_resources=True,cap={'C':base['objective'][2]},scope='audit_fixed_routes_resources')
    counter,cm=model.solve([0,0,0,1],10,config['seed']);valid(data,counter)
    if counter['objective'][3]>520.7998072166129+2e-5:raise AssertionError('known counterexample regression')
    counter['source']='fixed_original_resources_lateness_repair'
    save_json(OUT/'子问题二/固定原资源反例复现.json',dict(plan=counter,solver=cm))
    catalog,cs=single_point_catalog(data)
    with gzip.open(OUT/'子问题一/完整单点逐箱候选.json.gz','wt',encoding='utf-8') as f:json.dump(catalog,f,ensure_ascii=False)
    pool,info=global_pool(data,catalog,base,config['seed'],config['per_zone_type'],config['multipoint_budget'])
    save_json(OUT/'子问题一/联合候选库.json',pool);save_json(OUT/'子问题一/候选生成统计.json',dict(catalog_count=len(catalog),catalog_stats=cs,working_pool=info))
    save_json(OUT/'输入指纹.json',data['manifest'])
    library_hash=hashlib.sha256('\n'.join(sorted(r['candidate_id'] for r in pool)).encode()).hexdigest()
    archive=[counter];logs=[];anchors=[]
    for i in range(40):
        init=construct_initial(data,pool,config['seed']+i,i%4)
        if valid(data,init):archive_add(archive,init)
    save_json(OUT/'子问题二/构造初始化档案.json',archive)
    for j in range(4):
        # C upper bound from a valid incumbent is an objective-level cutoff,
        # not an artificial maximum expected deadline.
        cap={'C':min(p['objective'][2] for p in archive)} if j==2 else {}
        anchors.append(dict(label='global_anchor_'+'NECL'[j],weights=np.eye(4)[j].tolist(),cap=cap,seconds=config['anchor_seconds'],seed=config['seed']+j))
    baseline_answers=batch(data,pool,anchors,archive,logs,config['parallel_jobs'])
    objective_lowers=[]
    for j in range(4):
        rec=next(z for z in logs if z['job']['label']=='global_anchor_'+'NECL'[j])['stages'][0]
        objective_lowers.append(max(0.,(rec['lower_bound'] or 0.)-OBJ_TOL[j]))
    save_json(OUT/'子问题二/单目标有效下界.json',dict(lower_bounds=objective_lowers,scope='same K0; unconditional anchors or safe incumbent cutoff',library_sha256=library_hash))
    values=np.array([p['objective'] for p in [counter]+baseline_answers]);a=values.min(0);b=values.max(0)
    scale=np.maximum(b-a,np.array([1.,1.,300.,60.]));b=a+scale
    frozen=dict(ideal_reference=a.tolist(),upper_reference=b.tolist(),scale=scale.tolist(),delta=config['preference_delta'],center=config['preference_center'],
                rationale='Frozen after primary anchor pilot; zero pilot ranges use explicit positive unit scales.',library_sha256=library_hash)
    save_json(OUT/'冻结评价配置.json',frozen)
    # Adaptive epsilon refinement: each next round uses verified solutions from
    # previous rounds. Duplicate thresholds are never rerun under new names.
    seen=set();epsilon_history=[]
    for rnd in range(config['epsilon_rounds']):
        proposals=[]
        aa=np.array([p['objective'] for p in archive]);mins=aa.min(0);maxs=aa.max(0)
        # Isolate each trade-off, including a strict next integer N when possible.
        targets=[dict(N=max(1,int(mins[0])-1),E=float(maxs[1]),L=float(maxs[3])),
                 dict(N=int(maxs[0]),E=float((mins[1]+maxs[1])/2),L=float(maxs[3])),
                 dict(N=int(maxs[0]),E=float(maxs[1]),L=float((mins[3]+maxs[3])/2)),
                 dict(N=int(maxs[0]),E=float(maxs[1]),L=0.)]
        for cap in targets:
            key=tuple(round(cap[k],7) for k in ['N','E','L'])
            if key in seen:continue
            seen.add(key);proposals.append(dict(label=f'global_epsilon_{rnd}_{len(proposals)}',order=[2,3,1,0],cap=cap,seconds=config['epsilon_seconds'],seed=config['seed']+100+rnd,objective_lower_bounds=objective_lowers))
        proposals=proposals[:config['epsilon_per_round']]
        answers=batch(data,pool,proposals,archive,logs,config['parallel_jobs']) if proposals else []
        epsilon_history.append(dict(round=rnd,thresholds=[j['cap'] for j in proposals],verified_objectives=[p['objective'] for p in answers]))
    direct_archive=deepcopy(archive);direct_seconds=time.perf_counter()-start
    # Same K0 physical domain; ALNS is a separately labeled simplified contrast.
    alns,alnslogs,alnsseconds=alns_compare(data,pool,counter,config)
    for p in alns:p['source']='ALNS_comparison';archive_add(archive,p)
    weights=vertices(config['preference_center'],config['preference_delta']);prefjobs=[]
    for h,w in enumerate(weights):prefjobs.append(dict(label=f'global_preference_{h}',weights=(w/scale).tolist(),seconds=config['preference_seconds'],seed=config['seed']+300+h,preference=w.tolist(),objective_lower_bounds=objective_lowers))
    lpjobs=[dict(j,label=j['label']+'_LP',relax=True,seconds=config.get('preference_lp_seconds',20)) for j in prefjobs]
    batch(data,pool,lpjobs,archive,logs,config['parallel_jobs'])
    batch(data,pool,prefjobs,archive,logs,config['parallel_jobs'])
    baselines=[]
    for job in prefjobs:
        record=next(z for z in logs if z['job']['label']==job['label']);m=record['stages'][0];coeff=np.array(job['weights'])
        # All F are nonnegative: 0 is valid for uncentered scalar objectives.
        lpmeta=next(z for z in logs if z['job']['label']==job['label']+'_LP')['stages'][0]
        component_lb=float(coeff@np.asarray(objective_lowers))
        lb=max(component_lb,m['lower_bound'] if m['lower_bound'] is not None else 0.,lpmeta['lower_bound'] if lpmeta['lower_bound'] is not None else 0.)
        ub=min(float(coeff@p['objective']) for p in archive)
        if lb>ub+1e-6:raise AssertionError('invalid preference bound')
        baselines.append(dict(weight=job['preference'],coefficients=job['weights'],lower=lb,upper=ub,status=m['status'],lp_status=lpmeta['status'],lp_lower=lpmeta['lower_bound'],component_lower=component_lb,scope='same_frozen_joint_library',library_sha256=library_hash))
    for p in archive:
        vals=[float(np.array(v['coefficients'])@p['objective']) for v in baselines]
        p['regret_lower']=max(0.,max(s-v['upper'] for s,v in zip(vals,baselines)))
        p['regret_upper']=max(0.,max(s-v['lower'] for s,v in zip(vals,baselines)))
    final=min(archive,key=lambda p:(p['regret_upper'],p['objective'][2],p['objective'][3]))
    # Pareto polishing of a selected representative in the SAME joint library.
    cap=dict(zip('NECL',final['objective']));model=JointModel(data,deepcopy(pool),warm=final,cap=cap,scope='global_final_dominance_check')
    polished,pm=model.solve([1/scale[j] for j in range(4)],config['preference_seconds'],config['seed']+900)
    logs.append(dict(job=dict(label='global_final_dominance_check',cap=cap),stages=[pm]))
    if valid(data,polished) and dominates(polished['objective'],final['objective']):
        archive_add(archive,polished);final=polished
    # A new polished incumbent tightens common preference uppers for EVERY plan.
    for v in baselines:v['upper']=min(float(np.array(v['coefficients'])@p['objective']) for p in archive)
    for p in archive:
        vals=[float(np.array(v['coefficients'])@p['objective']) for v in baselines]
        p['regret_lower']=max(0.,max(s-v['upper'] for s,v in zip(vals,baselines)))
        p['regret_upper']=max(0.,max(s-v['lower'] for s,v in zip(vals,baselines)))
    final=min(archive,key=lambda p:(p['regret_upper'],p['objective'][2],p['objective'][3]))
    lp=JointModel(data,deepcopy(pool),scope='global_K0_LP_C')
    _,lpm=lp.solve([0,0,1,0],20,config['seed'],relax=True)
    save_json(OUT/'子问题二/连续松弛下界.json',lpm)
    save_json(OUT/'子问题二/偏好极点基准.json',baselines)
    save_json(OUT/'子问题二/自适应epsilon.json',epsilon_history)
    save_json(OUT/'子问题二/ALNS对照日志.json',alnslogs)
    save_json(OUT/'子问题二/完整联合运行日志.json',logs)
    save_json(OUT/'子问题二/直接联合档案.json',direct_archive)
    save_json(OUT/'子问题二/ALNS对照档案.json',alns)
    save_json(OUT/'子问题二/联合非支配档案.json',archive)
    save_json(OUT/'子问题二/最终方案.json',final)
    save_json(OUT/'子问题二/独立核验.json',dict(zip(['checks','errors','recomputed'],verify_plan(data,final))))
    save_json(OUT/'联合运行摘要.json',dict(library=info,library_sha256=library_hash,single_point_catalog=len(catalog),archive_count=len(archive),
        objective=final['objective'],regret_interval=[final['regret_lower'],final['regret_upper']],global_optimality_certified=False,
        direct_seconds=direct_seconds,alns_seconds=alnsseconds,total_seconds=time.perf_counter()-start,
        scope='All decisions optimized jointly over K0. Incomplete route enumeration; limited solver certification. ALNS is a separate contrast.',
        comparison_note='Direct phase and ALNS use the same K0 but different actual budgets; no equal-budget superiority claim.'))
    print('FINAL',final['objective'],final['regret_lower'],final['regret_upper'],flush=True)

if __name__=='__main__':main()
