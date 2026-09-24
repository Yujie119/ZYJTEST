from pathlib import Path
from collections import Counter
from copy import deepcopy
import hashlib,json,math,sys
import numpy as np
import openpyxl
ROOT=Path(__file__).resolve().parents[3]; OUT=Path(__file__).resolve().parent;Q=ROOT/'问题二'
sys.path.insert(0,str(Q))
from q2_data import load_data,make_route
def read(n):return json.loads((Q/n).read_text(encoding='utf-8'))
def write(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

data=load_data();plan=read('子问题二/最终方案.json');pool=read('子问题一/联合候选库.json');logs=read('子问题二/完整联合运行日志.json');arc=read('子问题二/联合非支配档案.json');init=read('子问题二/构造初始化档案.json');prefs=read('子问题二/偏好极点基准.json');frozen=read('冻结评价配置.json')
ph=hashlib.sha256((Q/'子问题二/最终方案.json').read_bytes()).hexdigest()
summary=read('求解摘要.json'); lower=read('子问题二/单目标有效下界.json')['lower_bounds']
result={'final_sha256':ph,'summary_hash_matches':ph==summary['final_plan_sha256'],
    'input_manifest_matches':all(hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'] for r in read('输入指纹.json')),
    'last_delivery':max(b['delivery'] for b in plan['boxes']),'last_return':max(r['finish'] for r in plan['routes']),
    'last_full_recharge':max(r['recharge'] for r in plan['routes']),'total_duration':sum(r['duration'] for r in plan['routes']),
    'uav_duration_sums':{u:sum(r['duration'] for r in plan['routes'] if r['uav']==u) for u in data['uavs']},
    'last_return_route':max(plan['routes'],key=lambda r:r['finish'])['route_id'],
    'late_boxes':[{'box':b['box'],'delivery':b['delivery'],'expected':b['expected'],'weight':b['priority']} for b in plan['boxes'] if not b['hard'] and b['delivery']>b['expected']+1e-5]}
stages=[(r['job']['label'],m) for r in logs for m in r['stages']]
result['statuses']=dict(Counter(m['status'] for _,m in stages));result['mip_nodes']=dict(Counter(m['nodes'] for _,m in stages if not m.get('relaxation')))
result['warm_fallback_tasks']=[label for label,m in stages if m.get('warm_fallback')]
result['global_mip_run_summary']=[{'label':label,'status':m['status'],'nodes':m['nodes'],'lower':m['lower_bound'],'upper':m['upper_bound'],'seconds':m['seconds'],'warm_fallback':m['warm_fallback']} for label,m in stages if not m.get('relaxation')]
result['initializer_archive_objectives']=[p['objective'] for p in init]
result['archive_all_from_initial_objectives']=all(any(np.allclose(p['objective'],q['objective'],atol=1e-7,rtol=0) for q in init) for p in arc)
result['number_candidates']=len(pool);result['candidates_visit_counts']=dict(Counter(len(r['events']) for r in pool));result['repeated_visit_candidates']=sum(len(set(r['zones']))<len(r['zones']) for r in pool)
result['catalog_and_missing_single']= {'catalog':read('子问题一/候选生成统计.json')['catalog_count'],'working_single':sum(len(r['events'])==1 for r in pool)}
result['catalog_and_missing_single']['omitted_single']=result['catalog_and_missing_single']['catalog']-result['catalog_and_missing_single']['working_single']
result['lower_bounds_from_anchors']=[]
for j in range(4):
    m=next(m for label,m in stages if label=='global_anchor_'+'NECL'[j])
    result['lower_bounds_from_anchors'].append({'j':j,'exported':lower[j],'solver':m['lower_bound'],'status':m['status'],'cap':m['epsilon']})
regrets=[]
for p in arc:
    vals=[float(np.dot(v['coefficients'],p['objective'])) for v in prefs]
    ri=[max(0,max(a-v['upper'] for a,v in zip(vals,prefs))),max(0,max(a-v['lower'] for a,v in zip(vals,prefs)))]
    regrets.append({'objective':p['objective'],'calculated':ri,'saved':[p['regret_lower'],p['regret_upper']],'matches':bool(np.allclose(ri,[p['regret_lower'],p['regret_upper']],atol=1e-10,rtol=0))})
result['regret_recalculations']=regrets
result['preference_upper_from_archive']=all(abs(v['upper']-min(float(np.dot(v['coefficients'],p['objective'])) for p in arc))<1e-10 for v in prefs)
result['preference_coefficients_match_frozen_scale']=all(np.allclose(np.array(v['weight'])/frozen['scale'],v['coefficients'],atol=1e-12,rtol=0) for v in prefs)
res=read('子问题二/ALNS对照日志.json');current=read('子问题二/固定原资源反例复现.json')['plan']['objective'];alns=[]
for r in res:
    candidate=r['objective'];delta=None if candidate is None else candidate[2]-current[2]
    alns.append({'iteration':r['iteration'],'operator':r['operator'],'accepted':r['accepted'],'new_nondominated':r['new_nondominated'],'candidate_C_minus_current':delta})
    if r['accepted']:current=candidate
result['alns_acceptance']=alns

# Independent original-template cell readback (no calls into report_q2.py).
wb=openpyxl.load_workbook(Q/'问题二_结果提交.xlsx',data_only=True)
template=openpyxl.load_workbook(ROOT/'D题/结果提交模板.xlsx',data_only=True)
expected_flights=[[r['route_id'],r['uav'],r['vehicle'],r['battery_id'],r['start'],'→'.join(['O01']+r['zones']+['O01']),r['finish'],r['energy']] for r in plan['routes']]
expected_boxes=[[b['box'],b['route_id'],b['zone'],b['delivery']] for b in sorted(plan['boxes'],key=lambda b:b['box'])]
exportchecks=[]
for name,expected in [('Q2_运输架次',expected_flights),('Q2_逐箱交付',expected_boxes)]:
    actual=list(wb[name].values);headers=list(next(template[name].values));errs=[]
    if list(actual[0])!=headers:errs.append('header differs from original template')
    if len(actual)!=1+len(expected):errs.append('row count')
    for i,(a,b) in enumerate(zip(actual[1:],expected),2):
        for j,(x,y) in enumerate(zip(a,b),1):
            if not (abs(x-y)<1e-8 if isinstance(y,(int,float)) else x==y):errs.append(f'{i},{j}')
    exportchecks.append({'sheet':name,'passed':not errs,'errors':errs,'rows':len(actual)-1})
result['xlsx_readback']=exportchecks

# Identity fingerprint insufficiency: in-memory parameter change only.
r=plan['routes'][0];d2=deepcopy(data);d2['vehicles'][r['vehicle']]['speed']*=.99
q=make_route(d2,r['vehicle'],r['events'])
result['identity_hash_parameter_mutation']={'same_candidate_id':q['candidate_id']==r['candidate_id'],'old_duration':r['duration'],'new_duration':q['duration'],'old_energy':r['energy'],'new_energy':q['energy'],'note':'No production input altered; route identity intentionally omits coefficients, so it cannot alone serve as model-scope fingerprint.'}
write('result_consistency.json',result)
print(json.dumps({k:result[k] for k in ['last_delivery','last_return','last_full_recharge','total_duration','uav_duration_sums','statuses','mip_nodes','archive_all_from_initial_objectives','catalog_and_missing_single','repeated_visit_candidates','xlsx_readback','identity_hash_parameter_mutation']},ensure_ascii=False,indent=2))
