"""Position audit and conditional workload LP bounds; no battery teleportation."""
import os
for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']:os.environ[k]='1'
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
import sys,json,gzip,hashlib
from pathlib import Path
from collections import defaultdict
HERE=Path(__file__).resolve().parent
Q2=HERE.parent
sys.path.insert(0,str(Q2))
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from q2_data import load_data,save_json
def read(p):return json.loads(p.read_text(encoding='utf-8'))

def main():
    data=load_data();plan=read(HERE/'最终方案.json');events=[];passed=True
    byb=defaultdict(list)
    for r in plan['routes']:byb[r['battery_id']].append(r)
    for b,g in data['batteries'].items():
        location='O01';ready=0.;soc=1.
        events.append(dict(battery=b,type='initial',time=0.,location=location,soc=soc))
        for r in sorted(byb[b],key=lambda r:r['start']):
            assert location=='O01' and ready<=r['start']+2e-5
            assert r['vehicle']==g and data['uavs'][r['uav']]==g
            # One chosen resource supplies every leg; no spare battery variable.
            e=data['vehicles'][g]['battery']
            events.append(dict(battery=b,uav=r['uav'],route=r['route_id'],type='install',
                time=r['start'],location='O01',soc=1.,spare_count=0))
            for leg in r['segments']:
                assert location==leg['from'];e-=leg['energy'];location=leg['to']
                events.append(dict(battery=b,uav=r['uav'],route=r['route_id'],type='arrive',
                    time=r['start']+leg['arrival'],location=location,soc=e/data['vehicles'][g]['battery']))
            assert location=='O01'
            ready=r['finish']+r['charge_s'];soc=1.
            events.append(dict(battery=b,type='charged',time=ready,location=location,soc=1.))
    save_json(HERE/'电池位置与无备用电池核验.json',dict(passed=passed,events=events,
        scope='Current O01-only exchange schedules meet the expert location and no-spare constraints; no off-depot charging capability is assumed.'))
    with gzip.open(HERE/'frozen_evaluation_candidates.json.gz','rt',encoding='utf-8') as f:pool=json.load(f)
    boxes=list(data['boxes']);bi={b:i for i,b in enumerate(boxes)};nr=len(pool)
    rows=[];cols=[];vals=[]
    for j,r in enumerate(pool):
        for b in r['box_ids']:rows.append(bi[b]);cols.append(j);vals.append(1.)
    aeq=coo_matrix((vals,(rows,cols)),shape=(len(boxes),nr+1)).tocsr()
    workload=[]
    for g in data['vehicles']:
        workload.append([r['duration'] if r['vehicle']==g else 0. for r in pool]+[-sum(t==g for t in data['uavs'].values())])
    specs=[dict(name='all_generated_routes',cap={}),
        dict(name='at_most_20',cap={'N':20}),dict(name='at_most_21',cap={'N':21}),
        dict(name='at_most_22',cap={'N':22}),
        dict(name='N22_E66',cap={'N':22,'E':66.})]
    records=[]
    for spec in specs:
        aub=list(workload);rhs=[0.]*len(workload)
        for k,v in spec['cap'].items():
            aub.append([1. if k=='N' else r['energy'] for r in pool]+[0.]);rhs.append(v)
        cost=np.r_[np.zeros(nr),1.]
        res=linprog(cost,A_eq=aeq,b_eq=np.ones(len(boxes)),A_ub=np.asarray(aub),b_ub=rhs,
            bounds=[(0,1)]*nr+[(0,None)],method='highs',options={'time_limit':60.})
        records.append(dict(**spec,status=res.message,optimal=bool(res.success),
            lower_seconds=float(res.fun) if res.success else None,
            lower_minutes=float(res.fun)/60 if res.success else None,
            seconds_above_89min=float(res.fun)-5340 if res.success else None))
    save_json(HERE/'89分钟与20至22架次_下界核查.json',dict(records=records,reference_seconds=5340,
        library_sha256=hashlib.sha256((HERE/'frozen_evaluation_candidates.json.gz').read_bytes()).hexdigest(),
        scope='Finite generated library with O01-only battery use. Valid LP bounds for this scope only; neither full-route nor off-depot exchange global bounds.',
        conclusion='An externally mentioned lower bound is unverified without its model, relaxation and proof. A lower bound is not an achieved schedule.'))
    print(json.dumps(records,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
