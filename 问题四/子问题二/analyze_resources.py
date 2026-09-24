"""Subproblem 2: certify selected configurations and explain inventory gaps.
Does not select a new partition; consumes subproblem 1's chosen partitions.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from q4_core import ROOT,R,load,save,csvout,build,evaluate,assignment,peak
from q4_paths import output,ensure_dirs

def main():
    ensure_dirs();c=build(ROOT/'输入快照/主方案')
    source=load(output('最终代表方案.json'))
    assert c['source_sha256']==source['source_sha256']
    chosen={int(g):evaluate(c,tuple(tuple(gr) for gr in x['partition'])) for g,x in source['solutions'].items()}
    assignments=[];certs=[];groups=[];tasks=[];boxes=[];gaps=[];merges=[]
    for g,x in chosen.items():
        assert x['D']==source['solutions'][str(g)]['D']
        aa,cc=assignment(c,x);assignments+=aa;certs+=cc
        lookup={(a['task'],a['resource_type'][0]):a['new_resource'] for a in aa}
        for h,gr in enumerate(x['groups'],1):
            gid=f'G{g}-{h:02}';services=set(gr['services'])
            rt=[r for r in c['routes'].values() if set(r['zones'])<=services]
            rr=[r for j,r in c['relays'].items() if any(k['route_id'] in c['relations'][j] for k in rt)]
            groups.append({'G':g,'group':gid,'services':gr['services'],'resources':gr['resources'],
                           'transport_tasks':len(rt),'relay_tasks':len(rr),'box_count':sum(r['nbox'] for r in rt),
                           'mass_kg':sum(r['mass'] for r in rt),'transport_work_s':gr['transport_work_s'],
                           'relay_work_s':gr['relay_work_s']})
            for mode,items in [('运输',rt),('中继',rr)]:
                for r in items:
                    k=r['route_id'] if mode=='运输' else r['relay_id']
                    tasks.append({'G':g,'group':gid,'type':mode,'task':k,
                                  'vehicle_type':r['vehicle'] if mode=='运输' else 'R',
                                  'start':r['start'],'finish':r['finish'],'energy_kwh':r['energy'],
                                  'new_uav':lookup[k,'U'],'new_battery_or_component':lookup[k,'P'],
                                  'source_sha256':c['source_sha256']})
            for b in c['plan']['boxes']:
                if b['zone'] in services:
                    boxes.append({'G':g,'group':gid,'box':b['box'],'zone':b['zone'],'task':b['route_id'],
                                  'delivery':b['delivery'],'hard':b['hard'],
                                  'hard_deadline':b['deadline'] if b['hard'] else '',
                                  'expected_delivery':b['expected'],
                                  'new_uav':lookup[b['route_id'],'U'],'new_battery':lookup[b['route_id'],'P']})
        for r in R:
            gaps.append({'G':g,'resource':r,'inventory':c['inventory'][r],'central_P':c['P'][r],
                         'demand':x['D'][r],'split_loss':x['split_loss'][r],'gap':x['gaps'][r],
                         'stock_left':x['stock'][r],
                         'peak_certificates':f'资源峰值证书.json: G={g}, resource={r}'})
        # A concrete left-to-right binary merge tree; gains telescope exactly.
        accumulated=set(x['groups'][0]['units']);left=x['groups'][0]['resources']
        gain_sum={r:0 for r in R}
        for h,group in enumerate(x['groups'][1:],2):
            units=accumulated|set(group['units'])
            merged={r:peak([e for e in c['events'] if e['component'] in units and e['resource_type']==r])[0] for r in R}
            for r in R:
                gain=left[r]+group['resources'][r]-merged[r];assert gain>=0;gain_sum[r]+=gain
                merges.append({'G':g,'merge_step':h-1,'resource':r,'left_units':sorted(accumulated),
                               'right_units':group['units'],'left_peak':left[r],'right_peak':group['resources'][r],
                               'merged_peak':merged[r],'reuse_gain':gain})
            accumulated=units;left=merged
        assert gain_sum==x['split_loss']
    csvout(output('组内资源分配见证.csv'),assignments);save(output('资源峰值证书.json'),certs)
    csvout(output('分组任务明细.csv'),tasks);csvout(output('分组汇总.csv'),groups)
    csvout(output('逐箱继承核验.csv'),boxes);csvout(output('库存缺口分析.csv'),gaps)
    csvout(output('固定资源事件.csv'),c['events']);csvout(output('合并复用收益.csv'),merges)
    analysis={'source_sha256':c['source_sha256'],'inventory':c['inventory'],'central_P':c['P'],
              'demand':{g:x['D'] for g,x in chosen.items()},'gaps':{g:x['gaps'] for g,x in chosen.items()},
              'split_loss':{g:x['split_loss'] for g,x in chosen.items()},
              'assignment_rows':len(assignments),'scope':'Exact fixed-task interval coloring and gap accounting; no rescheduling.'}
    save(output('独立配置分析.json'),analysis)
    lines=['# 子问题二：资源缺口与原因','',
           '固定任务的集中最低需求为 (1,2,2,1,4,4,2,3)，原库存为 (4,2,2,6,4,4,2,6)。',
           '八类顺序为A/B/C运输机、A/B/C电池、中继机和中继能源组件。','',
           '| 组数 | 资源 | 集中需求 | 分区附加需求 | 独立需求 | 库存 | 缺口 | 剩余 |',
           '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in gaps:
        lines.append('| '+' | '.join(str(row[k]) for k in ['G','resource','central_P','split_loss','demand','inventory','gap','stock_left'])+' |')
    lines+=['','两组需要补配B型机1架、C型机1架、B型电池1组和C型电池2组。三组需要补配B型机1架、C型机2架、B型电池1组和C型电池2组。',
            '三组代表将S006从小组分离，原来可错峰复用的C型机必须独立配置，因而多1架C型机；电池在充电期间仍被占用，两方案各需6组C型电池。',
            '中继架次全部位于同一不可拆单元，分组不损失其中继机和组件的复用机会，需求保持2架/3组，分区附加需求与缺口均为0。','',
            '资源编号以任务组为前缀。同型机与能源分别按开始时刻分配，释放事件先于同刻开始事件；每一配置数量都有同时占用任务证书。原始资源身份仅保留追溯。',
            '`合并复用收益.csv`给出一棵明确的合并树，各步收益相加等于独立需求减集中需求；不能将任意组对收益全部相加。',
            '本分析不更换子问题一的代表。已有库存内是否存在其他方案，已由完整13种分区和加入库存约束的MILP单独检查，答案为不存在。']
    output('资源缺口原因.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Subproblem 2: resource witnesses, gaps, peak certificates and merge-gain analysis written.')

if __name__=='__main__':main()
