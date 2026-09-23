"""Targeted route repairs, frozen-Q2 comparator and certified selection update."""
from q3_common import *
from q3_milp import solve_joint
from solve_q3 import nondom_add, relax_bound
from verify_q3 import Verifier
from concurrent.futures import ThreadPoolExecutor
import itertools, copy

def verify(p):
    v=Verifier(p);v.verify_routes();v.verify_boxes();v.verify_relays()
    result=v.finish()
    return result

def main():
    started=time.perf_counter();ctx=Context();prepare_candidates(ctx);prepare_geometry(ctx)
    initialbase=OUT/'缓存/补充实验初始方案.json'
    if not initialbase.exists():save(initialbase,load(OUT/'子问题二/最终方案_待独立核验.json'))
    base=load(initialbase)
    archive=load(OUT/'子问题一/非支配方案明细.json')
    book={r['route_id']:r for r in load(OUT/'子问题一/累计候选路线.json')}
    cases=[];newid=len(book)
    def make(g,ds):
        nonlocal newid
        newid+=1
        r=make_route(ctx,g,ds,f'K{newid:06d}')
        if r:book[r['route_id']]=r
        return r
    # B sorties whose payload also fits A are retasked to currently idle A
    # resources. Their task times, batteries and relays are reoptimized jointly.
    for g in ['A']:
        replacements={}
        for r in base['routes']:
            if r['vehicle']==g:continue
            new=make(g,r['deliveries'])
            if new:replacements[r['route_id']]=new
        for mode in ['C','L','E','N']:
            pool=[replacements.get(r['route_id'],book[r['route_id']]) for r in base['routes']]
            refs={r['route_id']:r for r in base['routes'] if r['route_id'] not in replacements}
            cases.append((f'reassign_A_{mode}',pool,refs,None,mode))
    # Replace the final C sortie to S001 by a feasible A+B split, retaining
    # exactly the same named-category demand. Distinct route copies allow the
    # same payload pattern on more than one physical sortie.
    tail=next(r for r in base['routes'] if r['route_id']=='K000019')
    a=make('A',[dict(zone='S001',counts={'S001|生活卫生用品':1,'S001|饮用水':1})])
    b=make('B',[dict(zone='S001',counts={'S001|饮用水':2})])
    if a and b:
        for use_A in [False,True]:
            pool=[];refs={}
            for r in base['routes']:
                if r['route_id']==tail['route_id']:continue
                rr=book[r['route_id']]
                if use_A:
                    other=make('A',r['deliveries'])
                    if other:rr=other
                pool.append(rr)
                if rr['route_id']==r['route_id']:refs[r['route_id']]=r
            pool += [a,b]
            for mode in ['C','E']:
                cases.append((f'tail_split_A{int(use_A)}_{mode}',pool,refs,None,mode))
    old=load(OUT/'缓存/问题二初始化快照.json');frozen={}
    for r in old['routes']:
        rr=next(t for t in base['routes'] if t['vehicle']==r['vehicle'] and t['deliveries']==r['deliveries'])
        frozen[rr['route_id']]=dict(r,route_id=rr['route_id'])
    cases.append(('frozen_Q2',[book[r['route_id']] for r in base['routes']],{},frozen,'E'))
    def work(case):
        label,pool,refs,frozen,mode=case
        p,meta=solve_joint(ctx,pool,required=[r['route_id'] for r in pool],reference=refs,
                          frozen=frozen,mode=mode,seconds=60,lex=True)
        result=verify(p) if p else None
        if p:p['source']=label
        print(label, p['objective'] if p else None,result['status'] if result else '',flush=True)
        return label,p,meta,result
    results=[];allplans=load(OUT/'子问题一/全部可行搜索方案.json')
    with ThreadPoolExecutor(max_workers=4) as ex:
        for label,p,meta,res in ex.map(work,cases):
            results.append(dict(label=label,objective=p['objective'] if p else None,
                                verified=res['passed'] if res else False,meta=meta))
            if p and res['passed']:
                save(OUT/f'子问题一/对照_{label}.json',p)
                if label!='frozen_Q2':allplans.append(p);nondom_add(archive,p)
    # Re-certify every nondominated contender before preference aggregation.
    accepted=[];certs=[]
    for i,p in enumerate(archive):
        v=verify(p);certs.append(dict(index=i,source=p.get('source'),status=v['status'],failures=v['failures']))
        if v['passed']:accepted.append(p)
    if not accepted:raise RuntimeError('No certified candidate')
    frozen=load(OUT/'子问题一/冻结比较尺度.json');ideal=np.array(frozen['ideal_reference']);scale=np.array(frozen['scale'])
    weights=[]
    for i,j in itertools.permutations(range(4),2):
        w=np.ones(4)/4;w[i]+=.15;w[j]-=.15;weights.append(w)
    F=np.array([p['objective'] for p in accepted]);norm=(F-ideal)/scale
    basevals=np.array([min(norm@w) for w in weights])
    lbs=[relax_bound(ctx,book,weight=w,scale=scale,ideal=ideal) for w in weights]
    for i,p in enumerate(accepted):
        p['regret_archive']=float(max(norm[i]@w-b for w,b in zip(weights,basevals)))
        p['regret_lower']=max(0.,p['regret_archive'])
        p['regret_upper']=float(max(norm[i]@w-b for w,b in zip(weights,lbs)))
    final=min(accepted,key=lambda p:(p['regret_upper'],p['objective'][2]))
    final['completion_time_lower_bound']=relax_bound(ctx,book,caps=dict(zip(['N','E','C','L'],final['objective'])))
    final['verification_status']='PASS'
    save(OUT/'子问题一/非支配方案明细.json',accepted)
    save(OUT/'子问题一/全部可行搜索方案.json',allplans)
    save(OUT/'子问题一/累计候选路线.json',list(book.values()))
    save(OUT/'子问题一/非支配档案独立核验.json',certs)
    save(OUT/'子问题一/补充修复与冻结对照.json',dict(results=results,elapsed_s=time.perf_counter()-started))
    save(OUT/'子问题一/偏好极点与有效下界.json',dict(weights=weights,archive_baselines=basevals,
         outer_relaxation_lower_bounds=lbs,scope='累计路线及其显式副本库内的外松弛；不是全路线全局下界'))
    save(OUT/'子问题二/最终方案_待独立核验.json',final)
    print('FINAL',final['objective'],final['source'],len(accepted),flush=True)
if __name__=='__main__':main()
