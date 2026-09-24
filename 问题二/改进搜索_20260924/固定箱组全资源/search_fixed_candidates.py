"""Same 28 candidate identities, all resource assignments/time/order open."""
from pathlib import Path
import sys,json,time,hashlib
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[3];Q=ROOT/'问题二';OUT=Path(__file__).resolve().parent
AUD=Q/'源头核查_20260924/implementation'
sys.path.insert(0,str(Q));sys.path.insert(0,str(AUD))
from q2_data import load_data,save_json
from q2_joint import JointModel
from q2_verify import verify_plan
from independent_raw_verify import raw_data,verify

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def check_and_save(label,plan,meta,data,raw,elapsed):
    checks,errors,recalc=verify_plan(data,plan)
    independent=verify(plan,raw)
    if not checks['all'] or not independent['all']:raise AssertionError((errors,independent))
    plan['source']='fixed_28_candidates_all_resources_'+label
    save_json(OUT/(label+'_plan.json'),plan)
    save_json(OUT/(label+'_verification.json'),{'production':{'checks':checks,'errors':errors,'recomputed':recalc},'independent_raw':independent})
    save_json(OUT/(label+'_solver.json'),meta)
    record={'label':label,'objective':plan['objective'],'status':meta['status'],'optimal':meta['optimal'],'lower_bound':meta['lower_bound'],'upper_bound':meta['upper_bound'],'gap':meta['gap'],'wall_seconds':elapsed,'production_verified':checks['all'],'raw_verified':independent['all']}
    print(json.dumps(record,ensure_ascii=False),flush=True)
    return record

def main():
    started=time.perf_counter();data=load_data();raw=raw_data()
    original=read(Q/'子问题二/最终方案.json');warm=read(AUD/'fixed_resources_timing_witness.json')['plan']
    save_json(OUT/'search_config.json',{'route_source':str(Q/'子问题二/最终方案.json'),'route_source_sha256':hashlib.sha256((Q/'子问题二/最终方案.json').read_bytes()).hexdigest(),'original_objective':original['objective'],'warm_objective':warm['objective'],'open_variables':['uav','battery','start','order'],'fixed_decisions':['all 28 candidate identities'],'per_objective_seconds':120,'seed':20260924,'no_global_route_optimality_claim':True})
    cap={'C':original['objective'][2],'L':warm['objective'][3]}
    records=[]
    for label,weights in [('L',[0,0,0,1]),('C',[0,0,1,0])]:
        begin=time.perf_counter()
        model=JointModel(data,deepcopy(original['routes']),mandatory=True,warm=warm,cap=cap,scope='fixed_formal_28_candidates_all_resources_'+label)
        plan,meta=model.solve(weights,120,20260924)
        if plan is None:raise RuntimeError('Lost verified warm incumbent')
        records.append(check_and_save(label,plan,meta,data,raw,time.perf_counter()-begin))
        warm=plan;cap={'C':min(original['objective'][2],plan['objective'][2]),'L':plan['objective'][3]+1e-7}
        save_json(OUT/'search_summary.json',{'original_objective':original['objective'],'stages':records,'latest_objective':warm['objective'],'total_seconds':time.perf_counter()-started})
    save_json(OUT/'best_plan.json',warm)

if __name__=='__main__':main()
