"""Audit summaries from stored evidence, without overwriting submitted results."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
Q2=HERE.parent
def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

old=read(Q2/'子问题二/最终方案.json')
new=read(HERE/'implementation/fixed_resources_timing_witness.json')['plan']
baselines=read(Q2/'子问题二/偏好极点基准.json')
archive=read(Q2/'子问题二/联合非支配档案.json')
frozen=read(Q2/'冻结评价配置.json')

def timing(p):
    uavs={}
    for r in p['routes']:
        uavs[r['uav']]=max(uavs.get(r['uav'],0.),r['start']+r['duration'])
    return dict(last_delivery=max(b['delivery'] for b in p['boxes']),
        last_return=max(r['start']+r['duration'] for r in p['routes']),
        last_recharge=max(r['start']+r['duration']+r['charge_s'] for r in p['routes']),
        cumulative_duration=sum(r['duration'] for r in p['routes']),
        per_uav_last_return=uavs)

uppers=[min(sum(a*b for a,b in zip(h['coefficients'],p['objective']))
            for p in archive+[new]) for h in baselines]
def regret(p):
    vals=[sum(a*b for a,b in zip(h['coefficients'],p['objective'])) for h in baselines]
    return [max(0.,max(v-u for v,u in zip(vals,uppers))),
            max(0.,max(v-h['lower'] for v,h in zip(vals,baselines)))]

delta=old['objective'][3]-new['objective'][3]
min_w=min(h['weight'][3] for h in baselines)
result=dict(old_objective=old['objective'],witness_objective=new['objective'],
    timing_original=timing(old),timing_witness=timing(new),
    lateness_reduction=delta,lateness_reduction_percent=100*delta/old['objective'][3],
    frozen_library_regret_original_reassessed=regret(old),
    frozen_library_regret_witness=regret(new),
    actual_regret_strict_improvement_lower_bound=min_w*delta/frozen['scale'][3],
    interpretation='Same K0 coefficients and preference lower bounds; witness is an audit counterexample, not a new global optimum.',
    sha256={str(p.relative_to(Q2)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [Q2/'子问题二/最终方案.json', HERE/'implementation/fixed_resources_timing_witness.json',
                  Q2/'子问题二/偏好极点基准.json',Q2/'冻结评价配置.json']})
(HERE/'关键数值与完成时间口径.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
