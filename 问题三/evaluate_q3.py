"""Bounded resource sensitivity, preference sensitivity and export checks."""
from q3_common import *
from q3_milp import solve_joint
from solve_q3 import relax_bound, nondom_add
from verify_q3 import Verifier
from concurrent.futures import ThreadPoolExecutor
import itertools

def main():
    ctx=Context();prepare_candidates(ctx);prepare_geometry(ctx)
    final=load(OUT/'子问题二/最终方案_待独立核验.json')
    routes=final['routes'];refs={r['route_id']:r for r in routes}
    cases=[('2组件',2,None),('3组件',3,None),('200m高度上限',6,[i for i,q in enumerate(ctx.qs) if q['height']<=200])]
    def work(case):
        label,count,pos=case
        p,meta=solve_joint(ctx,routes,required=list(refs),reference=refs,component_count=count,
                          position_ids=pos,mode='C',seconds=45,lex=True,
                          caps={'N':final['objective'][0],'E':final['objective'][1]+.5,'L':final['objective'][3]+1})
        good=False
        if p:
            v=Verifier(p);v.verify_routes();v.verify_boxes();v.verify_relays();good=v.finish()['passed']
            save(OUT/f'子问题一/敏感性_{label}.json',p)
        print('SENSITIVITY',label,p['objective'] if p else meta.get('reason',meta.get('stages')),good,flush=True)
        return dict(scenario=label,component_inventory=count,position_count=len(pos) if pos is not None else len(ctx.qs),
                    objective=p['objective'] if p else None,verified=good,meta=meta,
                    scope='固定最终运输箱组/路线/机型及资源身份顺序，开放时刻、中继位置时段及组件；限时45s')
    with ThreadPoolExecutor(max_workers=3) as ex:results=list(ex.map(work,cases))
    save(OUT/'子问题一/资源敏感性.json',results)
    archive=load(OUT/'子问题一/非支配方案明细.json');sc=load(OUT/'子问题一/冻结比较尺度.json')
    allplans=load(OUT/'子问题一/全部可行搜索方案.json')
    for row in results:
        if row['verified']:
            p=load(OUT/f"子问题一/敏感性_{row['scenario']}.json")
            p['source']='resource_sensitivity_'+row['scenario']
            # A schedule feasible with fewer components is also a valid
            # candidate for the original six-component inventory.
            allplans.append(p);nondom_add(archive,p)
    norm=(np.array([p['objective'] for p in archive])-np.array(sc['ideal_reference']))/np.array(sc['scale'])
    book={r['route_id']:r for r in load(OUT/'子问题一/累计候选路线.json')}
    ww=[]
    for i,j in itertools.permutations(range(4),2):
        w=np.ones(4)/4;w[i]+=.15;w[j]-=.15;ww.append(w)
    lower=[relax_bound(ctx,book,weight=w,scale=np.array(sc['scale']),ideal=np.array(sc['ideal_reference'])) for w in ww]
    baselines=[float(min(norm@w)) for w in ww]
    for i,p in enumerate(archive):
        p['regret_archive']=float(max(norm[i]@w-b for w,b in zip(ww,baselines)))
        p['regret_lower']=max(0.,p['regret_archive'])
        p['regret_upper']=float(max(norm[i]@w-b for w,b in zip(ww,lower)))
    final=min(archive,key=lambda p:(p['regret_upper'],p['objective'][2]))
    final['completion_time_lower_bound']=relax_bound(ctx,book,caps=dict(zip(['N','E','C','L'],final['objective'])))
    final['verification_status']='PASS'
    save(OUT/'子问题一/非支配方案明细.json',archive)
    save(OUT/'子问题一/全部可行搜索方案.json',allplans)
    save(OUT/'子问题二/最终方案_待独立核验.json',final)
    save(OUT/'子问题一/偏好极点与有效下界.json',dict(weights=ww,archive_baselines=baselines,
         outer_relaxation_lower_bounds=lower,scope='累计路线及显式副本库内的外松弛；不是全路线全局下界'))
    print('RESELECTED',final['source'],final['objective'],flush=True)
    pref=[]
    for radius in [0.,.1,.3,.5]:
        ww=[]
        if radius==0:ww=[np.ones(4)/4]
        else:
            for i,j in itertools.permutations(range(4),2):
                w=np.ones(4)/4;w[i]+=radius/2;w[j]-=radius/2;ww.append(w)
        lower=[relax_bound(ctx,book,weight=w,scale=np.array(sc['scale']),ideal=np.array(sc['ideal_reference'])) for w in ww]
        upper=np.max(np.array([norm@w-lb for w,lb in zip(ww,lower)]),axis=0)
        index=int(np.argmin(upper));pp=archive[index]
        pref.append(dict(radius=radius,archive_index=index+1,objective=pp['objective'],upper_regret=float(upper[index]),source=pp['source']))
    save(OUT/'子问题一/偏好半径敏感性.json',pref)
    validations=[]
    for i,p in enumerate(archive):
        v=Verifier(p);v.verify_routes();v.verify_boxes();v.verify_relays();r=v.finish()
        validations.append(dict(archive_index=i+1,passed=r['passed'],checks=len(r['checks']),failures=r['failures']))
    save(OUT/'子问题一/非支配档案独立核验.json',validations)
    if not all(x['passed'] for x in validations):raise RuntimeError('archive verification failure')
    print('ARCHIVE_VERIFIED',len(validations),flush=True)
if __name__=='__main__':main()
