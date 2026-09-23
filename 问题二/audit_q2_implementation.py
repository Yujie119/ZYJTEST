"""Fail-closed regressions from F01--F10 and independent DEM slab-intersection audit."""
from copy import deepcopy
import os
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['MKL_NUM_THREADS']='1'
import argparse,itertools,json,math,subprocess,sys
from pathlib import Path
import numpy as np
from scipy.io import loadmat
from q2_data import OUT,load_data,load_baseline,make_route,decode,save_json,locate
from q2_joint import JointModel,vertices,archive_add,dominates
from q2_verify import verify_plan

def independent_dem(data):
    raster=loadmat(locate(OUT.parent,'镇龙乡及周边30米DEM.mat'));dem=raster['dem'];dx,_,left,_,dy,top=raster['transform'].ravel()
    result=[]
    for (i,j),geo in data['geos'].items():
        a,b=data['nodes'][i],data['nodes'][j]
        x0,y0=(a['lon']-left)/dx,(a['lat']-top)/dy;x1,y1=(b['lon']-left)/dx,(b['lat']-top)/dy
        cc,rr=np.meshgrid(np.arange(max(0,math.floor(min(x0,x1))-1),min(dem.shape[1],math.ceil(max(x0,x1))+1)),
                           np.arange(max(0,math.floor(min(y0,y1))-1),min(dem.shape[0],math.ceil(max(y0,y1))+1)))
        lower=np.zeros_like(cc,dtype=float);upper=np.ones_like(cc,dtype=float)
        for start,end,cell in [(x0,x1,cc),(y0,y1,rr)]:
            if abs(end-start)<1e-14:
                inside=(cell<=start+1e-9)&(cell+1>=start-1e-9);upper=np.where(inside,upper,-1)
            else:
                t0=(cell-start)/(end-start);t1=(cell+1-start)/(end-start)
                lower=np.maximum(lower,np.minimum(t0,t1));upper=np.minimum(upper,np.maximum(t0,t1))
        hit=lower<=upper+1e-12;vals=dem[rr[hit],cc[hit]]
        terrain=float(vals.max());ok=abs(terrain-geo['terrain'])<1e-8 and int(hit.sum())==geo['cells']
        result.append(dict(source=i,target=j,terrain=terrain,pixel_count=int(hit.sum()),passed=ok))
    return result

def run():
    data=load_data();base=load_baseline(data);tests={};details={}
    tests['legacy_plan_passes']=verify_plan(data,base)[0]['all']
    mutations={
        'unknown_uav':lambda p:p['routes'][0].update(uav='U99'),
        'unknown_battery':lambda p:p['routes'][0].update(battery_id='A-BAT-99'),
        'wrong_type_battery':lambda p:p['routes'][0].update(battery_id=('B' if p['routes'][0]['vehicle']=='A' else 'A')+'-BAT-01'),
        'missing_route_reference':lambda p:p['boxes'][0].update(route_id='R_DOES_NOT_EXIST'),
        'forged_delivery':lambda p:p['boxes'][0].update(delivery=0.),
        'forged_recharge':lambda p:p['routes'][0].update(recharge=2000.),
        'forged_soc':lambda p:p['routes'][0].update(soc=1.),
        'forged_objective':lambda p:p.update(objective=[20,1,1,0]),
        'forged_hard_metadata':lambda p:next(b for b in p['boxes'] if b['hard']).update(hard=False,deadline=None),
        'forged_candidate_identity':lambda p:p['routes'][0].update(candidate_id='K_FORGED'),
        'forged_row_candidate':lambda p:p['boxes'][0].update(candidate_id='K_FORGED'),
        'forged_latest_start':lambda p:next(r for r in p['routes'] if math.isfinite(r['latest_start'])).update(latest_start=999999.),
        'forged_leg_load':lambda p:p['routes'][0]['segments'][0].update(load=0.),
        'nonfinite_start':lambda p:p['routes'][0].update(start=float('nan')),
        'nonfinite_delivery':lambda p:p['boxes'][0].update(delivery=float('nan')),
        'duplicate_exported_box':lambda p:p['boxes'].append(deepcopy(p['boxes'][0])),
        'missing_box_row':lambda p:p['boxes'].pop(),
        'unknown_event_box':lambda p:p['routes'][0]['events'][0]['boxes'].append('FAKE')}
    for name,fn in mutations.items():
        p=deepcopy(base);fn(p)
        checks,errors,_=verify_plan(data,p);tests[name+'_rejected']=not checks['all'];details[name]=errors[:4]
    # Physically consistent cached fields must not conceal a true schedule
    # violation: alter the schedule then regenerate its rows/derived caches.
    records=deepcopy(base['routes']);same=next([r for r in records if r['vehicle']==g] for g in data['vehicles'] if sum(r['vehicle']==g for r in records)>=2)
    same[0]['start']=same[1]['start']=0.;same[1]['uav']=same[0]['uav'];same[1]['battery_id']=same[0]['battery_id']
    overlap=decode(data,records);c,e,_=verify_plan(data,overlap)
    tests['consistent_double_booking_rejected']=not c['uav_nonoverlap'] and not c['battery_nonoverlap'];details['double_booking']=e[:6]
    records=deepcopy(base['routes']);late=next(r for r in records if math.isfinite(r['latest_start']));late['start']=late['latest_start']+100.
    c,e,_=verify_plan(data,decode(data,records));tests['consistent_hard_deadline_violation_rejected']=not c['hard_deadlines'];details['hard_late']=e[:6]
    m=JointModel(data,deepcopy(base['routes']),mandatory=True,fixed_resources=True,warm=base,cap={'C':base['objective'][2]},scope='audit_fixed_original_resources')
    p,status=m.solve([0,0,0,1],seconds=10)
    tests['counterexample_fixed_resources']=bool(p and p['objective'][3]<=520.7998072166129+2e-5 and verify_plan(data,p)[0]['all'])
    details['counterexample']=dict(objective=p['objective'] if p else None,solver=status)
    m=JointModel(data,deepcopy(base['routes']),mandatory=True,warm=base)
    p,status=m.solve([0,0,1,0],seconds=0.)
    tests['limit_incumbent_kept_and_checked']=bool(p and verify_plan(data,p)[0]['all']);details['limit']=status
    water=sorted(b for b,v in data['boxes'].items() if v['zone']=='S001' and v['kind']=='饮用水')
    small=dict(data,boxes={b:data['boxes'][b] for b in water})
    routes=[make_route(small,'B',[dict(zone='S001',boxes=water[k:k+2])]) for k in range(0,8,2)]
    model=JointModel(small,routes,mandatory=True,scope='four_repeated_patterns')
    p,stages=model.lexsolve(seconds=2.)
    tests['repeat_pattern_four_instances']=bool(p and len(p['routes'])==4 and verify_plan(small,p)[0]['all'] and max(b['delivery'] for b in p['boxes'])<3600)
    details['repeat']=dict(objective=p['objective'] if p else None,stages=stages)
    # Isolate the SOFT lateness row using one real box with a synthetic expected
    # deadline; the original workbook and production parameters are untouched.
    b=water[-1];unit=dict(data,boxes={b:dict(data['boxes'][b],hard=False,deadline=None,expected=1.)})
    r=make_route(unit,'B',[dict(zone='S001',boxes=[b])]);minimal_lateness=r['offsets'][b]-1.
    model=JointModel(unit,[r],mandatory=True,cap={'L':minimal_lateness-10.},scope='test_epsilon_L')
    p,status=model.solve([0,0,1,0],seconds=2.)
    tests['epsilon_L_rejects_too_tight_cap']=p is None and status['status']=='Infeasible'
    model=JointModel(unit,[r],mandatory=True,cap={'L':minimal_lateness+1e-7},scope='test_epsilon_L_boundary')
    p,status=model.solve([0,0,1,0],seconds=2.)
    tests['epsilon_L_accepts_boundary']=bool(p and abs(p['objective'][3]-minimal_lateness)<1e-6 and verify_plan(unit,p)[0]['all'])
    details['epsilon_L']=dict(minimum_lateness=minimal_lateness,boundary_status=status)
    four=make_route(data,'B',[dict(zone=z,boxes=[f'{z}-MED-01']) for z in ['S006','S011','S001','S013']])
    tests['four_station_supported']=four is not None and abs(four['energy']-2.6694252202594675)<1e-8
    repeat=make_route(data,'B',[dict(zone='S001',boxes=['S001-MED-01']),dict(zone='S006',boxes=['S006-MED-01']),dict(zone='S001',boxes=['S001-MED-02'])])
    tests['repeat_visit_supported']=repeat is not None
    for delta,expected in [(0.,1),(.3,12),(1.5,4)]:
        w=vertices(delta=delta);tests[f'weight_polytope_{delta}']=len(w)==expected and np.all(w>=-1e-10) and np.all(abs(w.sum(1)-1)<1e-10) and np.all(abs(w-.25).sum(1)<=delta+1e-10)
    arc=[dict(objective=[20,60.,9163.,500.])];new=dict(objective=[20,60.,9162.99,500.]);archive_add(arc,new)
    tests['absolute_dominance_tolerance']=len(arc)==1 and arc[0]['objective']==new['objective']
    code="import sys,json;sys.path.insert(0,"+repr(str(OUT))+");from q2_data import OUT,load_data;from q2_candidates import construct_initial;d=load_data();k=json.loads((OUT/'子问题一/联合候选库.json').read_text(encoding='utf-8'));print(json.dumps([(p['objective'] if p else None) for seed in [202600,202601,202602,202603] for p in [construct_initial(d,k,seed,seed%4)]]))"
    repeat_outputs=[]
    for hashseed in ['1','2']:
        env=dict(os.environ,PYTHONHASHSEED=hashseed)
        run=subprocess.run([sys.executable,'-X','utf8','-c',code],env=env,capture_output=True,text=True,encoding='utf-8',check=True)
        repeat_outputs.append(json.loads(run.stdout))
    tests['initializer_independent_of_hashseed']=repeat_outputs[0]==repeat_outputs[1]
    details['hashseed_initialization']=repeat_outputs
    terrain=independent_dem(data);tests['independent_dem_all_240']=all(r['passed'] for r in terrain);details['DEM_edges']=terrain
    finalpath=OUT/'子问题二/最终方案.json'
    if finalpath.exists():
        final=json.loads(finalpath.read_text(encoding='utf-8'));checks,errors,recomputed=verify_plan(data,final)
        tests['final_independent_rebuild']=checks['all'];details['final']=dict(checks=checks,errors=errors,objective=recomputed['objective'])
    result=dict(tests=tests,all=all(tests.values()),details=details)
    save_json(OUT/'子问题二/实现审计回归.json',result)
    print(json.dumps(dict(all=result['all'],tests={k:bool(v) for k,v in tests.items()}),ensure_ascii=False,indent=2))
    if not result['all']:raise SystemExit(1)

if __name__=='__main__':run()
