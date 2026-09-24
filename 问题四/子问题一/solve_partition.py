"""Q4 exact solution. Fixed tasks, group-exclusive reassigned resources.
All Q3 files are read-only; output is confined to this directory.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor
from collections import defaultdict
from fractions import Fraction as F
from pathlib import Path
import json
import platform
import time
from q4_core import (ROOT,R,build,load,save,csvout,digest,frac,enumerate_case,select,front,assignment)
from q4_checks import milp_checks,gpu_peak_check

from q4_paths import output,ensure_dirs

def brief(row):
    keys=['G','partition_code','A','BT','BR','B','Q','regret_lo','regret_hi','regret_max',
          'D','gaps','stock','split_loss','H_stock','inventory_feasible']
    return {**{k:row[k] for k in keys},
            'exact_rational':{k:str(row[k]) for k in ['A','BT','BR','B','regret_lo','regret_hi','regret_max']}}

def precision_audit(directory):
    """Do not snap or round source times. Report exact decimal overlaps."""
    p=load(directory/'方案.json');by=defaultdict(list)
    for mode,items in [('T',p['routes']),('R',p['relays'])]:
        for x in items:
            k=x['route_id'] if mode=='T' else x['relay_id']
            by[('U',x['uav'])].append((frac(x['start']),frac(x['finish'] if mode=='T' else x['body_ready']),k))
            by[('P',x['battery_id'] if mode=='T' else x['component'])].append((frac(x['start']),frac(x['recharge']),k))
    errors=[]
    for (r,identity),items in by.items():
        items.sort()
        for a,b in zip(items,items[1:]):
            if b[0]<a[1]:
                errors.append({'type':r,'old_resource':identity,'previous':a[2],'next':b[2],
                               'overlap_s':a[1]-b[0],'exact_overlap':str(a[1]-b[0])})
    return errors

def scenario_worker(directory):
    directory=Path(directory);t0=time.perf_counter();p=load(directory/'方案.json')
    precision=precision_audit(directory)
    if precision:
        return {'snapshot':directory.name,'status':'PRECISION_PENDING','objective':p['objective'],
                'reason':'原资源交接存在严格十进制重叠；冻结任务未修改，不进入正式跨快照比较。',
                'overlap_records':precision,'source_sha256':digest(directory/'方案.json')}
    c=build(directory);cases={};beta_rows=[]
    for g in [2,3]:
        if c['M']<g:
            cases[str(g)]={'status':'STRUCTURALLY_INFEASIBLE'};continue
        rows,_=enumerate_case(c,g);rows,chosen,meta=select(rows)
        cases[str(g)]={'status':'EXACT','count':len(rows),'chosen':brief(chosen),
                       'rows':[brief(r) for r in rows],'inventory_feasible_count':sum(x['inventory_feasible'] for x in rows)}
        for beta in [F(4,5),F(17,20),F(9,10),F(1)]:
            eligible=[x for x in rows if x['B']<=beta]
            best=min(eligible,key=lambda x:(x['A'],x['B'],x['H_stock'],x['partition_code'])) if eligible else None
            beta_rows.append({'snapshot':directory.name,'G':g,'beta':beta,
                              'status':'FEASIBLE_WITH_REPORTED_STOCK' if best else 'BALANCE_INFEASIBLE',
                              'A_star':best['A'] if best else None,'B':best['B'] if best else None,
                              'partition_code':best['partition_code'] if best else None,
                              'D':best['D'] if best else None,'gaps':best['gaps'] if best else None})
    return {'snapshot':directory.name,'status':'EXACT','source_sha256':c['source_sha256'],
            'objective':p['objective'],'M_T':c['M_T'],'M':c['M'],'components':c['components'],'P':c['P'],
            'workT':c['workT'],'workR':c['workR'],'cases':cases,'beta_rows':beta_rows,
            'seconds':time.perf_counter()-t0}

def workbook(rows):
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment,Font,PatternFill,Border,Side
    from openpyxl.utils import get_column_letter
    w=load_workbook(ROOT/'输入快照/原始附件/结果提交模板.xlsx');s=w['Q4_分区配置']
    headers=[s.cell(1,j).value for j in range(1,12)]
    s.row_dimensions[1].height=42
    for j,width in enumerate([12,14,36,16,16,16,14,14,14,16,18],1):
        s.column_dimensions[get_column_letter(j)].width=width
    edge=Side(style='thin',color='D9E1E8')
    for row in s.iter_rows(min_row=1,max_row=6,max_col=11):
        for cell in row:
            header=cell.row==1
            cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
            cell.font=Font(name='微软雅黑',size=10,bold=header,color='FFFFFF' if header else '1F2933')
            cell.fill=PatternFill('solid',fgColor='203E57' if header else 'F0F5F8' if cell.row in [3,5] else 'FFFFFF')
            cell.border=Border(left=edge,right=edge,top=edge,bottom=edge)
            if not header and cell.column>=4:cell.number_format='0'
    for i,values in enumerate(rows,2):
        for j,v in enumerate(values,1):s.cell(i,j,v)
        s.cell(i,3).alignment=Alignment(horizontal='left',vertical='center',wrap_text=True)
        s.row_dimensions[i].height=80 if len(values[2])>40 else 30
    s.freeze_panes='D2';s.print_area='A1:K6';s.page_setup.orientation='landscape'
    s.sheet_view.zoomScale=80
    s.page_setup.paperSize=s.PAPERSIZE_A3;s.page_setup.fitToWidth=1;s.page_setup.fitToHeight=1
    s.sheet_properties.pageSetUpPr.fitToPage=True
    w.save(output('问题四_结果提交.xlsx'))
    csvout(output('Q4_分区配置.csv'),[dict(zip(headers,r)) for r in rows])

def main():
    started=time.perf_counter();ensure_dirs()
    import numpy as np
    import scipy,psutil,torch
    memory0=psutil.Process().memory_info().rss
    directory=ROOT/'输入快照/主方案';assert not precision_audit(directory)
    c=build(directory);allrows={};chosen={};metas={};caches={};milp_logs=[]
    for g in [2,3]:
        rows,caches[g]=enumerate_case(c,g);allrows[g],chosen[g],metas[g]=select(rows)
        milp_logs.append(milp_checks(c,g,allrows[g],caches[g],chosen[g],metas[g]))
    snapshots=[directory]+sorted((ROOT/'输入快照/备选方案').glob('*'))
    with ProcessPoolExecutor(max_workers=4) as pool:
        alt=list(pool.map(scenario_worker,snapshots))
    assert torch.cuda.device_count()>=2,'Two requested GPUs are not available'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(gpu_peak_check,c,g,caches[g],device) for device,g in enumerate([2,3])]
        gpu=[f.result() for f in futures]
    save(output('完整分区档案.json'),{str(g):allrows[g] for g in allrows})
    csvout(output('分区枚举明细.csv'),[brief(r) for rows in allrows.values() for r in rows])
    csvout(output('非支配档案.csv'),[brief(r) for rows in allrows.values() for r in front(rows)])
    save(output('MILP与LP核验.json'),milp_logs)
    csvout(output('epsilon搜索记录.csv'),[v for log in milp_logs for v in log['epsilon']])
    selected={'source':str(directory/'方案.json'),'source_sha256':c['source_sha256'],
              'objective':c['plan']['objective'],'inventory':c['inventory'],'resource_order':R,
              'M_T':c['M_T'],'M':c['M'],'components':c['components'],
              'selection':{str(g):{**brief(chosen[g]),'preference':metas[g]} for g in chosen},
              'solutions':{str(g):chosen[g] for g in chosen},
              'scope':'Exact over all partitions of this frozen Q3 snapshot; complete relay ownership and O01 interval resources.'}
    save(output('最终代表方案.json'),selected)
    result_rows=[]
    for g,x in chosen.items():
        for h,gr in enumerate(x['groups'],1):
            result_rows.append([g,f'G{g}-{h:02}','、'.join(gr['services']),*[gr['resources'][r] for r in R]])
    workbook(result_rows)
    structure={'components':[{'code':i,'label':f'C{i+1}','zones':zs,'transport_work_s':c['workT'][i],
                              'relay_work_s':c['workR'][i]} for i,zs in enumerate(c['components'])],
               'M_T':c['M_T'],'M':c['M'],'slot_to_task':c['slots'],'relations':c['relations'],
               'merge_sources':c['merge_sources'],'actual_provider_evidence':c['edge_proof']}
    save(ROOT/'输入快照/结构与字段映射.json',structure)
    csvout(ROOT/'输入快照/通信关联.csv',c['edge_proof'])
    csvout(ROOT/'输入快照/slot_中继架次映射.csv',[{'slot':s,'relay_task':j} for s,j in sorted(c['slots'].items())])
    save(output('备选快照比较.json'),alt)
    csvout(output('共同均衡上限比较.csv'),[r for a in alt for r in a.get('beta_rows',[])])
    sensitivity=[]
    for g,rows in allrows.items():
        for delta in [F(0),F(1,10),F(3,10),F(1,2),F(1)]:
            _,best,meta=select(rows,delta)
            sensitivity.append({'G':g,'experiment':'preference_delta','value':str(delta),'choice':brief(best),'parameters':meta})
        for label,types in [('transport_uav',['U_A','U_B','U_C']),('transport_battery',['P_A','P_B','P_C']),('relay',['U_R','P_R'])]:
            raw={r:F(3,2) if r in types else F(1) for r in R};total=sum(raw.values())
            weights={r:w/total for r,w in raw.items()};_,best,meta=select(rows,weights=weights)
            sensitivity.append({'G':g,'experiment':'resource_weight_x1.5','value':label,
                                'choice':brief(best),'parameters':meta,
                                'note':'Q retains baseline code; weighted A is evaluated directly as a rational.'})
    save(output('偏好与类别权重敏感性.json'),sensitivity)
    performance={'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,'torch':torch.__version__,
                 'cpu_logical':psutil.cpu_count(),'memory_total_bytes':psutil.virtual_memory().total,
                 'rss_before_bytes':memory0,'rss_after_bytes':psutil.Process().memory_info().rss,
                 'peak_working_set_bytes':getattr(psutil.Process().memory_info(),'peak_wset',None),
                 'snapshot_processes':4,'gpu':gpu,'solver_wall_seconds':time.perf_counter()-started,
                 'scope':'Snapshot evaluation, MILP/LP, GPU initialization/checks, exports; excludes prior freeze/DEM reconstruction.',
                 'memory_policy':'Complete groups and partitions cached in RAM. No artificial RAM/GPU workload.'}
    save(output('计算资源记录.json'),performance)
    manifest={'main_source_sha256':c['source_sha256'],'main_objective':c['plan']['objective'],
              'immutable_inputs':{str(p.relative_to(ROOT)):digest(p) for p in (ROOT/'输入快照').rglob('*') if p.is_file()},
              'helpers':{str(p.relative_to(ROOT)):digest(p) for p in (ROOT/'冻结几何依赖').glob('*.py')},'scope':selected['scope']}
    save(ROOT/'输入快照冻结清单.json',manifest)
    print(json.dumps({'selected':{str(g):{k:float(chosen[g][k]) for k in ['A','B','regret_max']} for g in chosen},
                      'alternatives':[(a['snapshot'],a['status']) for a in alt],
                      'seconds':performance['solver_wall_seconds']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
