"""Direct joint MILP with variable sortie counts on a logged working library."""
import os
for key in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']:
    os.environ[key]='1'
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
import sys,json,gzip,time,random,hashlib
from pathlib import Path
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor,as_completed
HERE=Path(__file__).resolve().parent
Q2=HERE.parent
sys.path.insert(0,str(Q2))
from q2_data import load_data,make_route,save_json
from q2_joint import JointModel,archive_add
from q2_verify import verify_plan
DEST=HERE/'direct_joint'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def job(spec):
    data=load_data();pool=read(DEST/'working_candidates.json');archive=read(HERE/'联合非支配档案.json')
    cap=spec.get('cap',{});scale=read(Q2/'冻结评价配置.json')['scale']
    eligible=[p for p in archive if all(p['objective']['NECL'.index(k)]<=v+1e-7 for k,v in cap.items())]
    coeff=[w/s for w,s in zip(spec['weights'],scale)]
    warm=min(eligible,key=lambda p:sum(a*b for a,b in zip(coeff,p['objective']))) if eligible else None
    model=JointModel(data,deepcopy(pool),warm=warm,cap=cap,scope='direct_expanded_'+spec['name'])
    p,m=model.solve(coeff,seconds=spec['seconds'],seed=20261001+spec['seed'])
    verify=None
    if p is not None:
        checks,errors,extra=verify_plan(data,p)
        verify=dict(checks=checks,errors=errors,recomputed=extra)
        if not checks['all']:raise AssertionError(errors)
        p['source']='direct_expanded_'+spec['name']
    save_json(DEST/(spec['name']+'.json'),dict(plan=p,solver=m,verification=verify,spec=spec))
    print(spec['name'],p['objective'] if p else None,m['status'],flush=True)
    return p,m
def main():
    DEST.mkdir(exist_ok=True)
    data=load_data();archive=read(HERE/'联合非支配档案.json')
    pool={r['candidate_id']:make_route(data,r['vehicle'],r['events']) for p in archive for r in p['routes']}
    with gzip.open(HERE/'frozen_evaluation_candidates.json.gz','rt',encoding='utf-8') as f:allr=json.load(f)
    rng=random.Random(20261001)
    extra=[r for r in allr if r['candidate_id'] not in pool]
    # All incumbents remain available; a broad spread of other groups/routes is added.
    for r in rng.sample(extra,min(80,len(extra))):pool[r['candidate_id']]=make_route(data,r['vehicle'],r['events'])
    pool={k:r for k,r in pool.items() if r is not None}
    save_json(DEST/'working_candidates.json',list(pool.values()))
    save_json(DEST/'scope.json',dict(columns=len(pool),count_is_fixed=False,physical_inputs=data['manifest'],
        coefficient_sha256=hashlib.sha256((DEST/'working_candidates.json').read_bytes()).hexdigest(),
        note='Direct joint optimization over a finite working subset; all x, resource assignments and start times are free.'))
    jobs=[dict(name='N24_C',cap={'N':24},weights=[0,0,1,0],seconds=60,seed=1),
          dict(name='N26_C',cap={'N':26},weights=[0,0,1,0],seconds=60,seed=2),
          dict(name='zero_late_weighted',cap={'L':0},weights=[.2,.2,.6,0],seconds=60,seed=3),
          dict(name='equal_preference',cap={},weights=[.25]*4,seconds=60,seed=4)]
    with ProcessPoolExecutor(max_workers=4) as ex:
        out=[f.result() for f in as_completed([ex.submit(job,j) for j in jobs])]
    arc=[]
    for p,m in out:
        if p:archive_add(arc,p)
    save_json(DEST/'archive.json',arc)
if __name__=='__main__':main()
