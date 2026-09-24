"""Bounded new-Q2 structural seeds for Q3; never overwrites official results."""
from __future__ import annotations
import os
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMBA_NUM_THREADS'):
    os.environ[k]='1'
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
import argparse
import copy
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
import numpy as np
from q3_common import Context, certificate, load, make_route, profile, save
from q3_milp import solve_joint
from verify_q3 import Verifier

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent


EXPERT_SCOPE={
    'spare_battery_carriage_allowed':False,
    'expert_swap_rule':'Swap where an eligible battery is available; not restricted to O01; all shared batteries initially at O01.',
    'implemented_swap_policy':'Only O01 swaps between complete O01-to-O01 sorties; one installed energy unit per sortie; no spare energy carried.',
    'full_expert_feasible_domain_searched':False,
    'interpretation':'These remain allowed restricted-policy candidates under the expert rule, but do not optimize service-node exchange or battery relocation.',
}


def annotate_expert_scope(output):
    """Annotate completed artifacts only; does not launch a solver."""
    import pandas as pd
    data=ROOT/'D题/数据/无人机应急物资运输基础数据'
    boxraw=pd.read_excel(data/'物资需求与配送时限.xlsx',sheet_name='逐箱货箱清单').set_index('货箱编号')
    vehicles=pd.read_excel(data/'运输无人机数据.xlsx',header=None)
    initial_uav_positions={str(vehicles.iloc[i,0]):str(vehicles.iloc[i,2]) for i in range(8,16)}
    checks=[]
    plans=list(output.glob('*_已核验方案.json'))
    for path in plans:
        plan=load(path)
        for route in plan['routes']:
            assigned=[b for b in plan['boxes'] if b['route_id']==route['route_id']]
            raw_mass=sum(float(boxraw.loc[b['box'],'单箱质量（kg）']) for b in assigned)
            checks.append({'plan':path.name,'route':route['route_id'],
                           'one_installed_battery':isinstance(route['battery_id'],str),
                           'payload_only_raw_cargo_no_spare_mass':abs(raw_mass-route['mass'])<1e-7,
                           'starts_and_returns_O01':route['segments'][0]['from']=='O01' and route['segments'][-1]['to']=='O01',
                           'airframe_initially_O01':initial_uav_positions.get(route['uav'])=='O01'})
        for relay in plan['relays']:
            checks.append({'plan':path.name,'relay':relay['relay_id'],
                           'one_installed_energy_component':isinstance(relay['component'],str),
                           'sortie_O01_out_and_back_by_model':True,
                           'no_spare_cargo_variable_or_extra_component_assigned':True})
    for path in output.glob('*.json'):
        if path.name=='专家口径适用性核查.json':continue
        obj=load(path)
        if isinstance(obj,dict):obj['expert_rule_scope']=EXPERT_SCOPE
        elif isinstance(obj,list):
            for item in obj:
                if isinstance(item,dict):item['expert_rule_scope']=EXPERT_SCOPE
        save(path,obj)
    predicate_values=[v for c in checks for k,v in c.items() if isinstance(v,bool)]
    save(output/'专家口径适用性核查.json',{'status':'PASS' if all(predicate_values) else 'FAIL',
         'scope':EXPERT_SCOPE,'checks':checks,'predicate_count':len(predicate_values),
         'passed':sum(predicate_values),'initial_shared_battery_location':'O01 (expert-given initial condition)',
         'limitation':'Checks establish what the modeled candidates carry and where they swap. No service-site battery relocation or exchange search was performed.'})
    explanation=output/'搜索说明.md'
    existing=explanation.read_text(encoding='utf-8') if explanation.exists() else ''
    note='\n\n专家新口径适用性：禁止携带备用电池，允许在有匹配电池的地点换电，初始共享电池均在O01。本次候选每架次仅分配一组已装能源，货物质量等于原始货箱质量之和，没有备用电池载荷；全部架次回O01后换电。因此它是专家允许域内的“仅O01换电”受限策略，不覆盖服务点换电或电池位置迁移的完整模型。仅完成已启动3×60秒预算，没有按旧口径追加求解。\n'
    if '专家新口径适用性：' not in existing:explanation.write_text(existing+note,encoding='utf-8')
    print('EXPERT_SCOPE_CHECK',len(plans),'plans',sum(predicate_values),'/',len(predicate_values),flush=True)


def build_geometry(ctx, edges, nodes):
    """Rebuild only required arcs against raw DEM; no geometry cache writes."""
    for i,j in sorted(edges):
        g=ctx.geos[i,j]
        p0=ctx.xyz[i].copy();p1=p0.copy();p1[2]=g['cruise']
        p3=ctx.xyz[j].copy();p2=p3.copy();p2[2]=g['cruise']
        arcs=[]
        for name,a,b,dist in [('爬升',p0,p1,g['up']),('巡航',p1,p2,g['distance']),('下降',p2,p3,g['down'])]:
            if dist<1e-9:continue
            count=max(1,math.ceil(dist/(200 if name=='巡航' else 100)))
            for h in range(count):
                aa=a+(b-a)*h/count;bb=a+(b-a)*(h+1)/count
                todo=[(aa,bb,dist/count,certificate(ctx,aa,bb),0)]
                while todo:
                    a0,b0,length,c,level=todo.pop(0)
                    if not c['direct'] and not c['mask'] and level<4:
                        mid=(a0+b0)/2
                        todo[:0]=[(a0,mid,length/2,certificate(ctx,a0,mid),level+1),
                                  (mid,b0,length/2,certificate(ctx,mid,b0),level+1)]
                    else:
                        arcs.append(dict(phase=name,a=a0.tolist(),b=b0.tolist(),length=length,**c))
        ctx.arc_cache[i,j]=arcs
    for i in sorted(nodes):
        ctx.node_cache[i]=certificate(ctx,ctx.xyz[i],ctx.xyz[i])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',default=str(ROOT/'问题二/子问题二/最终方案.json'))
    parser.add_argument('--output',default=str(HERE/'全局直接求解/Q2新种子'))
    parser.add_argument('--per-run-seconds',type=float,default=60)
    parser.add_argument('--annotate-only',action='store_true',help='Annotate expert-rule restricted scope without solving')
    args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    if args.annotate_only:
        annotate_expert_scope(output)
        return
    started=time.perf_counter();source=load(args.source);ctx=Context()
    oldpoints=load(HERE/'缓存/中继候选位置.json')
    # Coordinates are a frozen finite position list. All relay physics and
    # required link certificates are recomputed under current raw Context.
    points=[]
    for old in oldpoints:
        q=ctx.relay_geometry(float(old['x']),float(old['y']),float(old['height']))
        if q is None:raise ValueError('Existing finite position no longer feasible')
        q['qid']=old['qid'];points.append(q)
    ctx.qs=points
    edges=set();nodes={0};rawboxes=ctx.boxes.set_index('box')
    for old in source['routes']:
        ids=[0]+[int(e['zone'][1:]) for e in old['events']]+[0]
        edges.update(zip(ids,ids[1:]));nodes.update(ids)
    build_geometry(ctx,edges,nodes)
    routes=[];reference={};mapping=[]
    for i,old in enumerate(source['routes'],1):
        deliveries=[]
        for event in old['events']:
            counts=dict(Counter(str(rawboxes.loc[b,'category']) for b in event['boxes']))
            if any(not c.startswith(event['zone']+'|') for c in counts):
                raise ValueError('Q2 delivery/box zone mismatch')
            deliveries.append({'zone':event['zone'],'counts':counts})
        rid=f'Q2SEED-{len(source["routes"]):02d}-{i:03d}'
        route=make_route(ctx,old['vehicle'],deliveries,rid)
        if route is None:raise ValueError(f'New-Q2 route not Q3 candidate feasible: {old["route_id"]}')
        atomic=profile(ctx,route,merge=False)
        if atomic is None:raise ValueError('No atomic communication certificate')
        route['needs']=atomic['needs'];route['source_q2_id']=old['route_id']
        route['pattern_id']='Q2PAT-'+str((old['vehicle'],deliveries))
        routes.append(route)
        reference[rid]={'start':float(old['start']),'uav':old['uav'],'battery_id':old['battery_id']}
        mapping.append({'id':rid,'source_id':old['route_id'],'atomic_needs':len(route['needs']),
                        'energy_delta':route['energy']-old['energy'],'duration_delta':route['duration']-old['duration']})
    if Counter({c:sum(r['counts'].get(c,0) for r in routes) for c in ctx.catinfo}) != Counter(ctx.boxes.groupby('category').size().to_dict()):
        raise ValueError('Rebuilt routes do not cover original demand')
    setup={'source':str(args.source),'source_objective':source['objective'],'route_count':len(routes),
           'required_ids':[r['route_id'] for r in routes],'atomic_needs':sum(len(r['needs']) for r in routes),
           'position_count':len(points),'mapping':mapping,'preparation_s':time.perf_counter()-started,
           'solver_threads':1,'solver_processes':1,'geometry_cache_used':False,
           'scope':'Fixed Q2 route structure with unique execution instances; joint Q3 scheduling. Three bounded solves, not an all-library solve.'}
    save(output/'重建清单.json',setup);save(output/'重建路线.json',routes)
    print('REBUILT',len(routes),'ATOMIC_NEEDS',setup['atomic_needs'],'PREP',setup['preparation_s'],flush=True)
    sys.path.insert(0,str(HERE/'审查资料'))
    from audit_source_and_result import audit
    experiments=[];verified=[]
    for number,(mode,keep_reference) in enumerate([('C',True),('L',False),('E',False)],1):
        label=f'{number}_{mode}_'+('原运输资源次序' if keep_reference else '开放运输资源')
        print('SOLVE_BEGIN',label,flush=True);t0=time.perf_counter()
        plan,meta=solve_joint(ctx,routes,required=[r['route_id'] for r in routes],
                            reference=reference if keep_reference else None,mode=mode,
                            seconds=args.per_run_seconds,slots_per_uav=3,component_count=6,lex=False)
        record={'label':label,'mode':mode,'transport_resources_and_order_fixed':keep_reference,
                'seconds':time.perf_counter()-t0,'solver_meta':meta,'candidate_found':plan is not None}
        if plan is None:
            stages=meta.get('stages',[])
            record['status']=('restricted_model_infeasible_proved' if stages and stages[0].get('status')==2 else
                              'limited_or_rejected_no_feasible_incumbent')
        else:
            save(output/(label+'_候选待核验.json'),plan)
            ar=audit(plan);save(output/(label+'_原始算术核验.json'),ar)
            v=Verifier(plan);v.verify_routes();v.verify_boxes();v.verify_relays();vr=v.finish()
            vr['plan']=str(output/(label+'_候选待核验.json'))
            save(output/(label+'_原DEM核验.json'),vr)
            record.update(objective=plan['objective'],raw_arithmetic_status=ar['status'],
                          raw_arithmetic_checks=len(ar['checks']),dem_status=vr['status'],dem_checks=len(vr['checks']))
            if ar['status']=='PASS' and vr['passed']:
                plan['status']='verified_fixed_Q2_structure_Q3_candidate'
                plan['source']='new_Q2_seed_'+label
                save(output/(label+'_已核验方案.json'),plan);verified.append(plan)
                record['status']='verified_feasible_candidate_no_global_optimality_claim'
            else:record['status']='candidate_rejected_by_independent_checks'
        experiments.append(record);save(output/'搜索日志.json',experiments)
        print('SOLVE_END',json.dumps(record,ensure_ascii=False),flush=True)
    archive=[]
    for p in verified:
        z=p['objective']
        if any(all(a<=b+1e-6 for a,b in zip(q['objective'],z)) and any(a<b-1e-6 for a,b in zip(q['objective'],z)) for q in verified if q is not p):continue
        archive.append(p)
    save(output/'已核验非支配候选.json',archive)
    summary={'source':str(args.source),'source_objective':source['objective'],'experiments':experiments,
             'verified_count':len(verified),'archive_count':len(archive),'elapsed_s':time.perf_counter()-started,
             'scope':'Only fixed new-Q2 route structures; no old witness epsilon caps. Does not replace all-library direct search. Limits without incumbents are not proofs of infeasibility.',
             'independent_geometry_algorithm':False,'raw_arithmetic_independent_of_production_energy':True}
    save(output/'搜索摘要.json',summary)
    text='# 最新问题二结构的Q3补充搜索\n\n固定28架次箱组、机型和访问事件，独立执行实例；联合优化运输开始、中继位置/服务和能源资源。C轮保留原运输实体身份与先后，L/E轮开放运输资源。各轮预算为'+str(args.per_run_seconds)+'秒，不施加旧见证的目标上限。\n\n'
    for r in experiments:
        text+='- '+r['label']+'：'+r['status']+'；目标='+str(r.get('objective'))+'。\n'
    text+='\n仅已通过原始算术与原DEM核验的方案进入候选档案；原DEM核验复用现有几何核验器，不宣称跨算法独立几何证明。限时没有可行解不等于不可行；固定结构搜索不替代全库直接联合优化。\n'
    (output/'搜索说明.md').write_text(text,encoding='utf-8')
    annotate_expert_scope(output)
    print('DONE',json.dumps({'verified':len(verified),'archive':len(archive),'seconds':summary['elapsed_s']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
