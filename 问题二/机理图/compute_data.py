"""Prepare auditable figure data; reconstruct the workload LP projection."""
from pathlib import Path
import os
for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'): os.environ[key]='1'
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
import sys, json, gzip, hashlib, csv
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from scipy.spatial import ConvexHull

OUT=Path(__file__).resolve().parent
Q2=OUT.parent
FINAL=Q2/'最终求解_20260924'
OLD=Q2/'子问题二'
sys.path.insert(0,str(Q2))
from q2_data import load_data

def read(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    inputs=[FINAL/'联合非支配档案.json',FINAL/'最终方案.json',FINAL/'frozen_evaluation_candidates.json.gz',
        FINAL/'偏好极点基准_扩大库松弛.json',Q2/'冻结评价配置.json',
        OLD/'ALNS对照日志.json',OLD/'ALNS对照档案.json',OLD/'自适应epsilon.json',
        OLD/'完整联合运行日志.json',OLD/'构造初始化档案.json',
        Q2/'改进搜索_20260924/89分钟与20至22架次_下界核查.json']
    arc=read(inputs[0]); final=read(inputs[1]); bases=read(inputs[3]); config=read(inputs[4])
    F=np.array([p['objective'] for p in arc])
    eps=[]
    for cap in [dict(N=22,E=66.,L=30.),dict(N=22,E=66.,L=0.),dict(N=20,E=66.,L=0.)]:
        eligible=[i for i,f in enumerate(F) if all(f['NECL'.index(k)]<=v+1e-8 for k,v in cap.items())]
        chosen=min(eligible,key=lambda i:(F[i,2],F[i,3],F[i,1],F[i,0]))
        eps.append(dict(cap=cap,eligible=eligible,selected=chosen,scope='archive filter only, not a new global MILP solve'))
    hist=read(inputs[7]); init=read(inputs[9]); IF=np.array([p['objective'] for p in init]); mi,ma=IF.min(0),IF.max(0)
    proposed=[dict(N=int(mi[0])-1,E=ma[1],L=ma[3]),dict(N=int(ma[0]),E=(mi[1]+ma[1])/2,L=ma[3]),
        dict(N=int(ma[0]),E=ma[1],L=(mi[3]+ma[3])/2),dict(N=int(ma[0]),E=ma[1],L=0.)]
    for p,q in zip(proposed,hist[0]['thresholds']): assert all(abs(p[k]-q[k])<1e-7 for k in p)
    jobs=[r for r in read(inputs[8]) if 'epsilon' in r['job']['label']]
    hrecords=[]
    for j,r in enumerate(jobs):
        stage=r['stages'][0]
        hrecords.append(dict(index=j,cap=r['job']['cap'],status=stage['status'],incumbent=stage['incumbent'],
            stages=[{k:s.get(k) for k in ['stage','status','lower_bound','upper_bound','incumbent']} for s in r['stages']]))
    assert len(hrecords)==4 and hist[1]['thresholds']==[]
    alog=read(inputs[5]); aa=read(inputs[6]); first=next(i for i,r in enumerate(alog) if r['accepted'])
    before=aa[0]; after=next(p for p in aa if np.allclose(p['objective'],alog[first]['objective']))
    released=set(alog[first]['released']); fixed={r['candidate_id'] for r in before['routes']}-released
    pre=[r for r in before['routes'] if r['candidate_id'] in released]
    post=[r for r in after['routes'] if r['candidate_id'] not in fixed]
    assert sorted(b for r in pre for b in r['box_ids'])==sorted(b for r in post for b in r['box_ids'])
    for a in [r for r in before['routes'] if r['candidate_id'] in fixed]:
        b=next(r for r in after['routes'] if r['candidate_id']==a['candidate_id'])
        assert all(a[k]==b[k] for k in ['uav','battery_id','start','finish'])
    current=np.array(before['objective']); states=[current.tolist()]
    for r in alog:
        if r['accepted']: current=np.array(r['objective'])
        states.append(current.tolist())
    # Reproduce adaptive operator probabilities from the actual reward rules.
    weights=np.ones(4); uses=np.zeros(4); rewards=np.zeros(4); ops=['random','deadline','battery','energy']
    current=np.array(before['objective'])
    for t,r in enumerate(alog):
        assert np.allclose(r['probabilities'],weights/weights.sum(),atol=1e-12)
        o=ops.index(r['operator']); uses[o]+=1
        candidate=np.array(r['objective'])
        better=tuple(candidate[[2,3,1,0]])<tuple(current[[2,3,1,0]])
        reward=8 if r['new_nondominated'] else 4 if better else 1 if r['accepted'] else .1
        rewards[o]+=reward
        if r['accepted']: current=candidate
        if (t+1)%3==0:
            for o in range(4):
                if uses[o]: weights[o]=max(.05,.75*weights[o]+.25*rewards[o]/uses[o])
            uses[:]=0; rewards[:]=0
        assert np.allclose(r['scores'],weights,atol=1e-12)
    # x are route fractions; t is makespan epigraph in minutes.
    with gzip.open(inputs[2],'rt',encoding='utf-8') as stream: pool=json.load(stream)
    raw=load_data(); boxes=list(raw['boxes']); bi={b:i for i,b in enumerate(boxes)}; nr=len(pool)
    rr=[];cc=[]
    for j,r in enumerate(pool):
        for b in r['box_ids']:rr.append(bi[b]);cc.append(j)
    A=coo_matrix((np.ones(len(rr)),(rr,cc)),shape=(len(boxes),nr+1)).tocsr()
    energies=np.array([r['energy'] for r in pool]+[0.])
    counts=np.array([1.]*nr+[0.])
    G=np.array([[r['duration']/60 if r['vehicle']==g else 0. for r in pool]+[-sum(t==g for t in raw['uavs'].values())] for g in ['A','B','C']])
    logs=[]
    def solve(cost,cap=None,window=False,label='LP'):
        mat=list(G); rhs=[0.]*3
        for k,v in (cap or {}).items():mat.append(counts if k=='N' else energies);rhs.append(v)
        if window:
            mat.extend([energies,-energies]);rhs.extend([72.,-58.])
        bounds=[(0,1)]*nr+([(85,160)] if window else [(0,None)])
        res=linprog(cost,A_eq=A,b_eq=np.ones(len(boxes)),A_ub=np.array(mat),b_ub=rhs,
            bounds=bounds,method='highs',options={'time_limit':60.})
        logs.append(dict(label=label,status=res.message,success=bool(res.success),objective=float(res.fun) if res.success else None))
        assert res.success,label
        assert np.max(np.abs(A@res.x-1))<1e-6
        assert np.max(np.array(mat)@res.x-np.array(rhs))<1e-5
        return res
    cost=np.r_[np.zeros(nr),1.]
    bound_records=[]
    for r in read(inputs[10])['records']:
        sol=solve(cost,r['cap'],label=r['name']); value=float(sol.fun)
        assert abs(value*60-r['lower_seconds'])<1e-4
        eligible=[i for i,f in enumerate(F) if all(f['NECL'.index(k)]<=v+1e-8 for k,v in r['cap'].items())]
        idx=min(eligible,key=lambda i:F[i,2])
        bound_records.append(dict(name=r['name'],cap=r['cap'],lower_min=value,upper_min=F[idx,2]/60,
            upper_archive_index=idx,upper_objective=F[idx].tolist(),gap_pct=100*(F[idx,2]/60-value)/(F[idx,2]/60)))
    min_c=solve(cost,label='min_C_fractional_example')
    fractionals=[dict(candidate_id=r['candidate_id'],vehicle=r['vehicle'],zones=r['zones'],value=float(x),
        energy=r['energy'],duration_min=r['duration']/60) for r,x in zip(pool,min_c.x[:-1]) if 1e-7<x<1-1e-7]
    fractionals.sort(key=lambda r:(-r['value'],r['candidate_id']))
    # Exact 2-D projection via support LPs; cached support queries and edge checks.
    P=np.vstack([energies/72,cost/160]); points=[]; cache={}
    def support(d):
        key=tuple(np.round(d,12))
        if key not in cache:
            sol=solve(-np.asarray(d)@P,window=True,label='projection_support')
            cache[key]=P@sol.x
        return cache[key]
    for d in [(1,0),(-1,0),(0,1),(0,-1)]:points.append(support(d))
    for iteration in range(80):
        points=np.unique(np.round(points,11),axis=0).tolist(); hull=ConvexHull(points)
        additions=[];worst=0.
        for equation in hull.equations:
            p=support(equation[:2]);v=equation[:2]@p+equation[2];worst=max(worst,float(v))
            if v>2e-8:additions.append(p)
        if not additions:break
        points.extend(additions)
    else: raise AssertionError('Support projection did not converge')
    polygon=np.array(points)[hull.vertices]*np.array([72,160])
    known=F[:,[1,2]]/[1,60]
    assert np.max(hull.equations[:,:2]@(known/[72,160]).T+hull.equations[:,2,None])<1e-7
    projection=dict(window=[58,72,85,160],vertices=polygon.tolist(),support_calls=len(cache),iterations=iteration+1,
        max_normalized_support_violation=worst,known_hull=known[ConvexHull(known).vertices].tolist(),
        min_c_point=[float(energies@min_c.x),float(min_c.fun)],fractionals=fractionals,
        selected_nonzero=int(np.count_nonzero(min_c.x[:-1]>1e-7)),fractional_count=len(fractionals),
        semantics='Projection of coverage/type-workload LP into (E,C_hat) with explicitly clipped display window; not full scheduling LP or integer hull.')
    prefs=[]
    for b in bases:
        coef=np.array(b['coefficients']);scores=F@coef;upper=float(scores.min());assert abs(upper-b['upper'])<1e-8
        score=float(np.array(final['objective'])@coef)
        prefs.append(dict(weight=b['weight'],lower=b['lower'],upper=upper,final_score=score,
            regret_lower=score-upper,regret_upper=score-b['lower']))
    assert abs(max(r['regret_upper'] for r in prefs)-final['regret_upper'])<1e-9
    data=dict(scope='finite 28216-route O01 exchange submodel',archive=[dict(id=f'PF{i+1:04d}',objective=p['objective']) for i,p in enumerate(arc)],
        final_objective=final['objective'],final_regret=[final['regret_lower'],final['regret_upper']],epsilon_filters=eps,
        historical_epsilon=dict(initial_objectives=IF.tolist(),history=hist,records=hrecords,minimum=mi.tolist(),maximum=ma.tolist()),
        alns=dict(log=[{k:r[k] for k in ['iteration','operator','probabilities','scores','accepted','new_nondominated','objective']} for r in alog],
            states=states,first_accepted_index=first,released=sorted(released),fixed=sorted(fixed),before=before,after=after,
            before_released_count=len(pre),after_repair_count=len(post)),
        projection=projection,bounds=bound_records,preferences=prefs,lp_logs=logs,
        input_sha256={str(p.relative_to(Q2)):sha(p) for p in inputs},
        validations=dict(epsilon_thresholds_recomputed=True,operator_probabilities_recomputed=True,
            released_box_conservation=True,fixed_tasks_unchanged=True,lp_bounds_recomputed=True,
            projection_edge_certified=True,known_points_inside_projection=True,regret_recomputed=True))
    write(OUT/'mechanism_data.json',data)
    for name,rows in [('上下界核验.csv',bound_records),('松弛分数路线.csv',fractionals),('LP求解记录.csv',logs)]:
        with (OUT/name).open('w',encoding='utf-8-sig',newline='') as stream:
            w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(json.dumps(dict(candidate_count=nr,archive_count=len(arc),projection_vertices=len(polygon),
        support_calls=len(cache),fractional_count=len(fractionals),checks=data['validations']),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
