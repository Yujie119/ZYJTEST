"""Release a single verified representative, keeping all older runs immutable."""
from __future__ import annotations
import os
for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']:os.environ[k]='1'
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
import sys,json,gzip,hashlib,shutil,math
from pathlib import Path
from collections import Counter
from copy import deepcopy
HERE=Path(__file__).resolve().parent
Q2=HERE.parent
OLD=Q2/'改进搜索_20260924'
sys.path[:0]=[str(Q2),str(Q2/'源头核查_20260924/implementation')]
import numpy as np
from q2_data import load_data,decode,save_json,make_route
from q2_joint import archive_add,JointModel
from q2_verify import verify_plan
from independent_raw_verify import raw_data,verify

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    data=load_data();raw=raw_data();archive=[];sources=[]
    for path in [OLD/'联合非支配档案.json',HERE/'cover_search/combined_archive.json']:
        if path.exists():
            sources.append(str(path))
            for p in read(path):archive_add(archive,p)
    for path in (HERE/'type_polish').glob('plan_*.json'):
        if path.name.endswith('_solver.json'):continue
        p=read(path)
        if 'objective' not in p:continue
        sources.append(str(path));archive_add(archive,p)
    pre=len(archive);new=[];polish=[]
    scale=np.asarray(read(Q2/'冻结评价配置.json')['scale'])
    # Small complete route selections: final dominance refinement at all four caps.
    for i,p in enumerate(archive):
        model=JointModel(data,deepcopy(p['routes']),mandatory=True,warm=p,
            cap=dict(zip('NECL',p['objective'])),scope=f'release_polish_{i}')
        q,m=model.solve([1/s for s in scale],seconds=5,seed=2026112400+i)
        if q is None:q=p
        q['source']='release_polish_of_'+p.get('source',str(i))
        checks,errors,_=verify_plan(data,q)
        if not checks['all']:raise AssertionError(errors)
        audit=verify(q,raw)
        if not audit['all']:raise AssertionError('raw verification')
        archive_add(new,q);polish.append(dict(solver=m,objective=q['objective']))
    archive=new
    with gzip.open(OLD/'frozen_evaluation_candidates.json.gz','rt',encoding='utf-8') as f:pool=json.load(f)
    ids={r['candidate_id']:r for r in pool}
    # Reusing a same-library bound is allowed only after coefficient identity checks.
    for p in archive:
        for r in p['routes']:
            if r['candidate_id'] not in ids:raise ValueError('New route requires redoing evaluation LP')
            orig=ids[r['candidate_id']]
            for field in ['energy','duration','charge_s']:
                if abs(r[field]-orig[field])>1e-8:raise AssertionError('coefficient identity')
            if r['box_ids']!=orig['box_ids'] or r['offsets']!=orig['offsets']:raise AssertionError('route identity')
    bases=deepcopy(read(OLD/'偏好极点基准_扩大库松弛.json'))
    for b in bases:b['upper']=min(float(np.asarray(b['coefficients'])@p['objective']) for p in archive)
    for p in archive:
        vals=[float(np.asarray(b['coefficients'])@p['objective']) for b in bases]
        p['regret_lower']=max(0.,max(v-b['upper'] for v,b in zip(vals,bases)))
        p['regret_upper']=max(0.,max(v-b['lower'] for v,b in zip(vals,bases)))
    archive.sort(key=lambda p:(p['regret_upper'],p['objective'][2],p['objective'][3]))
    final=archive[0]
    checks,errors,rec=verify_plan(data,final)
    independent=verify(final,raw)
    save_json(HERE/'最终方案.json',final);save_json(HERE/'联合非支配档案.json',archive)
    save_json(HERE/'独立核验.json',dict(checks=checks,errors=errors,recomputed=rec))
    save_json(HERE/'原始数据核验.json',independent)
    save_json(HERE/'终端精修.json',polish)
    save_json(HERE/'偏好极点基准_扩大库松弛.json',bases)
    shutil.copyfile(OLD/'frozen_evaluation_candidates.json.gz',HERE/'frozen_evaluation_candidates.json.gz')
    shutil.copyfile(OLD/'双GPU全候选复算.json',HERE/'双GPU全候选复算_同库证据.json')
    save_json(HERE/'汇总.json',dict(objective=final['objective'],archive_count=len(archive),
        route_count=len(pool),library_coefficient_sha256=read(OLD/'汇总.json')['library_coefficient_sha256'],
        source_library_file_sha256=sha(OLD/'frozen_evaluation_candidates.json.gz'),
        scope='Verified feasible representative with O01-only battery exchanges; not a global optimum certificate for unrestricted routes or off-depot exchanges.',
        physics='Original task physical rules with explicitly stated horizontal calibration and potential-energy climb assumptions.',
        frozen_scale=scale.tolist(),regret_interval=[final['regret_lower'],final['regret_upper']],
        source_paths=sources,pre_polish_count=pre,raw_checks=independent['checks_count'],
        selected_by='minimum common worst-case regret upper bound',
        exact_global_optimum=False,route_count_not_fixed=True,off_depot_operation_used=False))
    # Explicit physical battery movements for this final plan.
    batlogs=[]
    for b,g in data['batteries'].items():
        ready=0.;loc='O01';seq=sorted([r for r in final['routes'] if r['battery_id']==b],key=lambda r:r['start'])
        batlogs.append(dict(battery=b,event='initial',time=0.,location=loc,soc=1.))
        for r in seq:
            assert ready<=r['start']+2e-5 and loc=='O01';energy=data['vehicles'][g]['battery']
            batlogs.append(dict(battery=b,event='install',time=r['start'],location=loc,uav=r['uav'],soc=1.,spares=0))
            for leg in r['segments']:
                assert loc==leg['from'];loc=leg['to'];energy-=leg['energy']
                batlogs.append(dict(battery=b,event='arrive',time=r['start']+leg['arrival'],location=loc,uav=r['uav'],soc=energy/data['vehicles'][g]['battery']))
            assert loc=='O01';ready=r['recharge']
            batlogs.append(dict(battery=b,event='charge_complete',time=ready,location=loc,soc=1.))
    save_json(HERE/'电池位置核验.json',dict(passed=True,events=batlogs,
        no_carried_spare=True,initial_all_O01=True,off_depot_exchange_used=False))
    print('SELECTED',final['objective'],'REGRET',final['regret_lower'],final['regret_upper'],flush=True)

if __name__=='__main__':main()
