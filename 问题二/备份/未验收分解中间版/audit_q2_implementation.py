"""Deterministic regression checks for the Question 2 implementation fixes."""
from __future__ import annotations
import json, sys, copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from q2_data import load_data,load_legacy
from q2_verify import verify_plan
from q2_model import FixedSchedule

ROOT=Path(__file__).resolve().parent

def main():
    data=load_data(); old=load_legacy(data,ROOT/'备份'/'审计修正前_20260924_005823'/'子问题二'/'最终方案.json')
    checks={};base,_,_=verify_plan(data,old);checks['legacy_plan_passes']=base['all']
    bad=copy.deepcopy(old);bad['routes'][0]['uav']='U99';checks['unknown_uav_rejected']=not verify_plan(data,bad)[0]['all']
    bad=copy.deepcopy(old);bad['boxes'][0]['delivery']=0.;checks['tampered_delivery_rejected']=not verify_plan(data,bad)[0]['all']
    bad=copy.deepcopy(old);bad['routes'][0]['recharge']+=1000.;checks['tampered_recharge_rejected']=not verify_plan(data,bad)[0]['all']
    bad=copy.deepcopy(old);bad['boxes']=bad['boxes'][:-1];checks['missing_box_rejected']=not verify_plan(data,bad)[0]['all']
    p,meta=FixedSchedule(data,old['routes']).solve_lex(seconds=8,seed=202611)
    checks['time_limited_incumbent_retained']=p is not None and all(m['has_incumbent'] for m in meta)
    checks['fixed_routes_lateness_not_worse_than_old']=p is not None and p['objective'][3] <= old['objective'][3]+1e-6
    result={'checks':checks,'all':all(checks.values()),'legacy_objective':old['objective'],'fixed_route_objective':p['objective'] if p else None,'schedule_meta':meta}
    (ROOT/'子问题二'/'实现审计回归.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['all']:raise SystemExit(1)

if __name__=='__main__':main()
