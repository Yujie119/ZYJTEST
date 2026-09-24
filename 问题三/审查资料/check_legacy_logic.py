"""Small reproducible tests of the specific legacy modeling interfaces.

Synthetic counterexamples are expressly separate from the published plan.
"""
from pathlib import Path
import sys,json,copy,itertools
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
Q3=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Q3))
import q3_common as common
import solve_q3 as legacy

ctx=common.Context(); common.prepare_candidates(ctx); common.prepare_geometry(ctx)
plan=common.load(Q3/'子问题二/最终方案.json')
sample=plan['routes'][0]
a=legacy.register(ctx,sample['vehicle'],sample['deliveries'])
b=legacy.register(ctx,sample['vehicle'],sample['deliveries'])
one=milp([1.],integrality=[1],bounds=Bounds([0],[1]),constraints=LinearConstraint([[2.]],[8.],[8.]),options={'threads':1})
four=milp([1.]*4,integrality=[1]*4,bounds=Bounds([0]*4,[1]*4),constraints=LinearConstraint([[2.]*4],[8.],[8.]),options={'threads':1})
merged=common.profile(ctx,sample,merge=True)
atomic=common.profile(ctx,sample,merge=False)
fused_real=[]
for route in plan['routes']:
 p=common.profile(ctx,route,merge=True);q=common.profile(ctx,route,merge=False)
 if len(q['needs'])>len(p['needs']):
  fused_real.append({'route_id':route['route_id'],'merged_needs':len(p['needs']),'atomic_needs':len(q['needs'])})
geometry=common.load(Q3/'缓存/区间几何.json')
oldkeys=set(geometry)
qs=ctx.qs
swapped=[qs[1],qs[0]]+qs[2:]
legacy_cache_accepts=(geometry['candidate_count']==len(swapped) and geometry['step_m']==200.)

# Prove the legacy relay charging disjunction pins each tested energy to the
# expected piecewise value, by optimizing charge in both directions.
from q3_milp import LinearModel
charging=[]
for ee in [0.,.01,.16,.32,.321,1.,2.,2.56]:
 vals=[]
 for sense in [1,-1]:
  m=LinearModel();en=m.var('energy',ee,ee);y=m.var('on',1,1,True)
  ch=m.var('charge',0,1540);branch=m.var('branch',0,1,True)
  m.add({branch:1,y:-1},hi=0);m.add({en:1,y:-.32,branch:-2.24},hi=0);m.add({en:1,branch:-.32},lo=0)
  for sign in [1,-1]:
   m.add({ch:sign,en:-1968.75*sign,branch:-6000},hi=0)
   m.add({ch:sign,en:-406.25*sign,y:-500*sign-6000,branch:6000},hi=0)
  res=m.run({ch:sense},5)
  vals.append(None if res.x is None else float(res.x[ch]))
 expected=1968.75*ee if ee<=.32 else 406.25*ee+500
 charging.append({'energy':ee,'minimum':vals[0],'maximum':vals[1],'expected':expected,
                  'passed':all(v is not None and abs(v-expected)<1e-7 for v in vals)})

# This synthetic interval pair tests the *interface restriction*, not whether
# the real plan happens to require an 8000-second uninterrupted cover.
q=next(q for q in qs if q['qid']=='Q006')
interval_case={'label':'synthetic, not an observed violation of the published plan',
              'intervals':[[1000,5000],[5000,9000]],'same_position_mask':True,
              'one_relay_max_service_s':q['dmax'],
              'two_4000s_tasks_each_fit':q['dmax']>=4000,
              'merged_8000s_one_task_fits':q['dmax']>=8000}
result={'register_same_object':a is b,'register_same_id':a['route_id']==b['route_id'],
        'synthetic_cover_one_binary_status':int(one.status),
        'synthetic_cover_four_binary_status':int(four.status),
        'published_routes_with_deleted_switch_boundaries':fused_real,
        'synthetic_handoff':interval_case,
        'cache_identity_keys':sorted(oldkeys),
        'candidate_reordering_accepted_by_old_cache_predicate':legacy_cache_accepts,
        'cached_candidate_rows':len(qs),
        'published_candidate_csv_rows':len(common.pd.read_csv(Q3/'子问题一/中继候选位置.csv')),
        'exact_charging_regressions':charging,
        'scope':'Only specified interfaces tested; no synthetic failure is labelled as an actual constraint violation of the submitted plan.'}
p=Q3/'审查资料/本轮复核/旧实现逻辑复现.json';p.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'repeat_pattern_bug':a is b and one.status==2 and four.status==0,
                  'actual_merged_routes':len(fused_real),'charging_pass':all(x['passed'] for x in charging)},ensure_ascii=False))
