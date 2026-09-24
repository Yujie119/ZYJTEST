"""Export an isolated full-precision table package; never writes official XLSX."""
from pathlib import Path
import csv
import json
import math
from collections import Counter
import sys
import openpyxl

OUT=Path(__file__).resolve().parent
SOURCE=OUT.parent/'official/已核验方案.json'
ROOT=OUT.parents[3]


def emit(name,rows):
    path=OUT/name
    with path.open('w',encoding='utf-8-sig',newline='') as fh:
        writer=csv.DictWriter(fh,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    with path.open(encoding='utf-8-sig',newline='') as fh:
        reread=list(csv.DictReader(fh))
    assert len(reread)==len(rows)
    for expected,actual in zip(rows,reread):
        for key,value in expected.items():
            assert (float(actual[key])==float(value)) if isinstance(value,(int,float)) else actual[key]==value
    assert path.read_bytes()[:3]==b'\xef\xbb\xbf'
    return len(reread)


def md_table(rows):
    keys=list(rows[0])
    def txt(v):return str(v).replace('|','\\|').replace('\n',' ')
    return '| '+' | '.join(keys)+' |\n| '+' | '.join('---' for _ in keys)+' |\n'+''.join('| '+' | '.join(txt(r[k]) for k in keys)+' |\n' for r in rows)


def main():
    p=json.loads(SOURCE.read_text(encoding='utf-8'))
    routes=sorted(p['routes'],key=lambda r:(r['start'],r['route_id']))
    relays=sorted(p['relays'],key=lambda r:(r['start'],r['relay_id']))
    boxes=sorted(p['boxes'],key=lambda b:b['box'])
    assert len({r['route_id'] for r in routes})==len(routes)
    assert len({r['relay_id'] for r in relays})==len(relays)
    assert len({b['box'] for b in boxes})==len(boxes)
    assert len({r['slot'] for r in relays})==len(relays)
    route_by_id={r['route_id']:r for r in routes}
    tid={r['route_id']:f'Q3-T{i:03d}' for i,r in enumerate(routes,1)}
    rid={r['relay_id']:f'Q3-R{i:03d}' for i,r in enumerate(relays,1)}
    rawwb=openpyxl.load_workbook(ROOT/'D题/数据/无人机应急物资运输基础数据/物资需求与配送时限.xlsx',read_only=True,data_only=True)
    raw={r[0]:r for r in list(rawwb['逐箱货箱清单'].values)[1:] if r[0]}
    rawwb.close()
    assert set(raw)=={b['box'] for b in boxes}
    for b in boxes:
        assert b['route_id'] in route_by_id
        r=route_by_id[b['route_id']]
        assert b['zone']==raw[b['box']][1] and b['kind']==raw[b['box']][2]
        assert b['uav']==r['uav'] and b['battery_id']==r['battery_id']
        assert b['zone'] in r['zones']
        assert abs(b['delivery']-r['start']-r['offsets'][b['category']])<=2e-4
    for r in routes:
        bb=[b for b in boxes if b['route_id']==r['route_id']]
        assert Counter(b['category'] for b in bb)==Counter(r['counts'])
        assert len(r['zones'])==len(r['deliveries'])
        for zone,event in zip(r['zones'],r['deliveries']):
            assert zone==event['zone'] and all(cat.startswith(zone+'|') for cat in event['counts'])
        assert r['segments'][0]['from']=='O01' and r['segments'][-1]['to']=='O01'
        assert abs(sum(float(raw[b['box']][3]) for b in bb)-r['mass'])<=1e-7
        assert isinstance(r['battery_id'],str)
    assert all(isinstance(r['component'],str) for r in relays)
    trans=[{'架次编号':tid[r['route_id']],'无人机编号':r['uav'],'机型编号':r['vehicle'],'电池编号':r['battery_id'],
            '开始时刻（s）':r['start'],'访问服务区顺序':'→'.join(['O01']+r['zones']+['O01']),
            '返回O01时刻（s）':r['finish'],'架次能耗（kWh）':r['energy']} for r in routes]
    boxrows=[{'货箱编号':b['box'],'架次编号':tid[b['route_id']],'服务区编号':b['zone'],'交付完成时刻（s）':b['delivery']} for b in boxes]
    relayrows=[{'中继架次编号':rid[r['relay_id']],'中继无人机编号':r['uav'],'能源组件编号':r['component'],
                '开始时刻（s）':r['start'],'悬停经度（°）':r['position']['lon'],'悬停纬度（°）':r['position']['lat'],
                '悬停海拔（m）':r['position']['z'],'建链完成时刻（s）':r['alpha'],'服务结束时刻（s）':r['beta'],
                '返回O01时刻（s）':r['finish'],'架次能耗（kWh）':r['energy']} for r in relays]
    maprows=[{'类型':'运输','源方案架次编号':r['route_id'],'本目录表格架次编号':tid[r['route_id']]} for r in routes]+[
             {'类型':'中继','源方案架次编号':r['relay_id'],'本目录表格架次编号':rid[r['relay_id']]} for r in relays]
    template=openpyxl.load_workbook(ROOT/'D题/结果提交模板.xlsx',read_only=True,data_only=True)
    for sheet,rows in [('Q2_运输架次',trans),('Q2_逐箱交付',boxrows),('Q3_中继架次',relayrows)]:
        headers=[v for v in next(template[sheet].values) if v is not None]
        assert list(rows[0])==headers,(sheet,list(rows[0]),headers)
    template.close()
    export_counts={name:emit(name,rows) for name,rows in [('运输架次.csv',trans),('逐箱交付.csv',boxrows),
                                                          ('中继架次.csv',relayrows),('架次编号映射.csv',maprows)]}
    et=sum(r['energy'] for r in routes);er=sum(r['energy'] for r in relays)
    c=max(r['finish'] for r in routes+relays)
    soft=[b for b in boxes if not b['hard']]
    late=sum(b['priority']*max(b['delivery']-b['expected'],0) for b in soft)/sum(b['priority'] for b in soft)
    objective=[len(routes)+len(relays),et+er,c,late]
    assert all(abs(a-b)<2e-4 for a,b in zip(objective,p['objective']))
    assert p['NT']==len(routes) and p['NR']==len(relays)
    assert abs(p['ET']-et)<2e-6 and abs(p['ER']-er)<2e-6
    record=json.loads((SOURCE.parent/'记录.json').read_text(encoding='utf-8'))
    vr=json.loads((SOURCE.parent/'独立DEM核验.json').read_text(encoding='utf-8'))
    ar=json.loads((SOURCE.parent/'原始数据结构审计.json').read_text(encoding='utf-8'))
    assert record['status']=='PASS' and vr['passed'] and ar['status']=='PASS'
    assert all(abs(a-b)<2e-4 for a,b in zip(vr['objective_stored'],p['objective']))
    metadata={'status':'PASS','source':str(SOURCE),'source_objective':p['objective'],'table_objective_recomputed':objective,
              'objective_difference':[a-b for a,b in zip(objective,p['objective'])],
              'counts':export_counts,'transport_energy':et,'relay_energy':er,
              'hard_boxes':len(boxes)-len(soft),'soft_boxes':len(soft),'soft_priority_sum':sum(b['priority'] for b in soft),
              'unique_ID_and_association_checks':True,'source_XLSX_box_ids_match':True,
              'CSV_BOM_and_full_float_round_trip':True,'template_headers_match':True,
              'numeric_rounding_applied':False,'official_XLSX_written':False,
              'swap_policy':'Only O01 exchange; one installed energy unit per sortie; no spare carried.',
              'not_claimed':['full expert-rule domain optimality','new minimax regret optimum','all-library global optimum'],
              'source_verification':{'DEM_status':vr['status'],'DEM_checks':len(vr['checks']),'raw_status':ar['status'],'raw_checks':len(ar['checks'])}}
    (OUT/'导出一致性核验.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    summary=[{'指标':'运输架次','本版值':len(routes)},{'指标':'中继架次','本版值':len(relays)},
             {'指标':'已交付货箱','本版值':len(boxes)},{'指标':'总架次','本版值':p['objective'][0]},
             {'指标':'运输能耗/kWh','本版值':p['ET']},{'指标':'中继能耗/kWh','本版值':p['ER']},
             {'指标':'总能耗/kWh','本版值':p['objective'][1]},{'指标':'联合最晚返场/s','本版值':p['objective'][2]},
             {'指标':'普通物资加权平均迟到/s','本版值':p['objective'][3]}]
    compare=[{'指标':name,'原历史方案':a,'本版方案':b,'本版减原版':b-a} for name,a,b in zip(
        ['总架次','总能耗/kWh','联合最晚返场/s','普通物资加权平均迟到/s'],record['source_objective'],p['objective'])]
    note='# 受限换电策略改进方案表\n\n'
    note+='本目录为单独导出版本，源文件为 `../official/已核验方案.json`，未覆盖正式提交Excel。表中开始时刻均为开始准备，所有时间单位为秒；CSV为UTF-8 BOM，浮点数直接保留源JSON完整精度，没有格式化舍入。\n\n'
    note+='本方案采用**仅O01换电基准策略**：全部共享电池初始在O01，各架次只使用一组已装电池/能源组件，不携带备用电池。它属于专家允许规则下的受限可行策略；未搜索服务点换电与电池位置迁移，不是专家新规则完整可行域的最优解，也不是重新认证的新最小最大遗憾最优方案。\n\n'
    note+='此次改进固定运输箱组/路线、资源身份与先后、中继位置/组件和原子区间保障主体，精修时刻与充电分支。源结果记录原DEM检查1015项、原始数据结构检查452项全部通过。本次只进行导出与关联复核，未重复声称开展新的完整物理核验。\n\n'
    note+='## 汇总\n\n'+md_table(summary)+'\n## 与原历史方案比较\n\n'+md_table(compare)
    note+='\n迟到下降约0.0000465秒，远小于实际业务时间尺度；应如实保留数值，主要改善体现在能耗和返场时间。分层求解允许微小数值容差，不扩大解释为完整问题的严格全局最优性。\n\n'
    note+='## 文件和编号\n\n运输表、逐箱表、中继表沿用题目提交字段。运输表使用模板 `Q2_运输架次`字段作为Q3运输扩展，逐箱表同理；中继表严格使用 `Q3_中继架次`字段。\n\n'
    note+='- [运输架次.csv](运输架次.csv)：20条。\n- [逐箱交付.csv](逐箱交付.csv)：80条。\n- [中继架次.csv](中继架次.csv)：4条。\n- [架次编号映射.csv](架次编号映射.csv)：保留源ID到本目录展示ID的对应。\n- [导出一致性核验.json](导出一致性核验.json)：编号唯一、80箱原始ID、目的地/架次关联、目标汇总、模板字段及完整精度回读检查。\n\n'
    note+='表格编号按本版开始时刻排序，仅在本目录内使用；不得不经映射与其他版本同名架次直接拼接。逐箱架次引用已随本版映射同步。\n\n'
    note+='## 运输架次\n\n'+md_table(trans)+'\n## 中继架次\n\n'+md_table(relayrows)
    note+='\n全部80箱交付时刻见逐箱CSV；未将箱号压缩合并，也未遗漏零迟到箱。\n'
    (OUT/'改进方案说明.md').write_text(note,encoding='utf-8')
    print(json.dumps(metadata,ensure_ascii=False,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
