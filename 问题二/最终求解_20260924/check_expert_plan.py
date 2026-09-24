"""Bounded evidence check for the O01-only representative; no model changes."""
from pathlib import Path
from collections import defaultdict
import argparse
import hashlib
import json
import math
import openpyxl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / '问题二' / '改进搜索_20260924'

def check(path, audit_path=None, output_path=None, update_report=False):
    path = Path(path).resolve()
    source_bytes = path.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    plan = json.loads(source_bytes.decode('utf-8'))
    raw = next((ROOT / 'D题').rglob('运输无人机数据.xlsx'))
    rows = list(openpyxl.load_workbook(raw, data_only=True).active.values)
    vehicles = {r[0]: {'energy':float(r[8]), 'reserve':float(r[9])/100}
                for r in rows if r[0] in ['A','B','C'] and isinstance(r[1],str)}
    idx = next(i for i,r in enumerate(rows) if r[0]=='共享电池库存')
    stock = {r[0]: (int(r[1]),float(r[2])) for r in rows[idx+2:] if r[0]}
    batteries = {f'{g}-BAT-{i:02d}':g for g,(n,_) in stock.items() for i in range(1,n+1)}
    uavs = {r[0]:r[1] for r in rows if r[0] and str(r[0]).startswith('U')}
    routes, boxes = plan['routes'], plan['boxes']
    assertions=[]
    def record(name, truth):
        assertions.append({'check':name,'passed':bool(truth)})
    record('Unique 80 delivered boxes',len(boxes)==80 and len({b['box'] for b in boxes})==80)
    record('All hard deadlines',all(b['delivery']<=b['deadline']+1e-6 for b in boxes if b['hard']))
    grouped=defaultdict(list)
    ugrouped=defaultdict(list)
    for r in routes:
        g=r['vehicle'];battery=r['battery_id'];grouped[battery].append(r);ugrouped[r['uav']].append(r)
        record(r['route_id']+' resource matching',batteries.get(battery)==g and uavs.get(r['uav'])==g)
        record(r['route_id']+' starts/ends O01',r['segments'][0]['from']=='O01' and r['segments'][-1]['to']=='O01')
        record(r['route_id']+' one route battery identifier',isinstance(battery,str) and all(s.get('battery_id',battery)==battery for s in r['segments']))
        energy=sum(s['energy'] for s in r['segments'])
        soc=1-energy/vehicles[g]['energy']
        record(r['route_id']+' accounting SOC',abs(soc-r['soc'])<1e-9 and soc>=vehicles[g]['reserve']-1e-9)
        tc=stock[g][1]*(.65*(.9-soc)/.9+.35) if soc<.9 else stock[g][1]*.35*(1-soc)/.1
        record(r['route_id']+' recharge from raw Tfull',abs(tc-r['charge_s'])<1e-5 and abs(r['recharge']-(r['finish']+tc))<1e-5)
    battery_chains=[]
    for b,g in batteries.items():
        seq=sorted(grouped[b],key=lambda r:r['start']);ready=0.;loc='O01'
        for r in seq:
            record(r['route_id']+' available full battery at O01',loc=='O01' and ready<=r['start']+1e-5)
            ready=r['recharge'];loc='O01'
        battery_chains.append({'battery':b,'initial_location':'O01','initial_soc':1.,'route_ids':[r['route_id'] for r in seq],'off_depot_swap_events':0})
    for u,seq in ugrouped.items():
        seq=sorted(seq,key=lambda r:r['start'])
        record(u+' nonoverlap',all(a['finish']<=b['start']+1e-5 for a,b in zip(seq,seq[1:])))
    soft=[b for b in boxes if not b['hard']];den=sum(b['priority'] for b in soft)
    obj=[len(routes),sum(r['energy'] for r in routes),max(r['finish'] for r in routes),sum(b['priority']*max(0,b['delivery']-b['expected']) for b in soft)/den]
    record('Four objective arithmetic',all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(obj,plan['objective'])))
    existing_record=None
    if audit_path is None:
        audit_path=next((p for p in [path.parent/'原始数据核验.json',path.parent/'最终原始数据独立核验.json'] if p.exists()),None)
    if audit_path is not None:
        audit_path=Path(audit_path).resolve()
        existing=json.loads(audit_path.read_text(encoding='utf-8'))
        audit=existing.get('final',existing)
        audit_obj=audit.get('objective')
        existing_record={'source':str(audit_path),'sha256':hashlib.sha256(audit_path.read_bytes()).hexdigest(),
                         'all':audit.get('all'),'checks_count':audit.get('checks_count'),
                         'objective':audit_obj,'objective_matches':bool(audit_obj and len(audit_obj)==len(obj) and all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(audit_obj,obj))),
                         'scope':existing.get('scope','Read from explicitly selected source-directory audit; no broader optimality claim.')}
    record('Source unchanged while checking',hashlib.sha256(path.read_bytes()).hexdigest()==source_sha)
    result={'source':str(path),'sha256':source_sha,'objective':obj,
            'all_bounded_checks':all(x['passed'] for x in assertions),'assertions_count':len(assertions),
            'assertions':assertions,'battery_chains':battery_chains,'uav_count_used':len(ugrouped),
            'battery_count_used':len(grouped),'minimum_route_end_soc':min(r['soc'] for r in routes),
            'hard_boxes':len(boxes)-len(soft),'soft_boxes':len(soft),'soft_priority_sum':den,
            'existing_raw_audit':existing_record,
            'scope':'O01-only full-charge reuse and source-JSON arithmetic; does not rederive geometry/energy or prove off-depot exchange invalid; no spare cargo is represented in the submitted route plan.'}
    OUT.mkdir(parents=True,exist_ok=True)
    output_path=Path(output_path or OUT/'专家口径_当前方案有界核验.json')
    if output_path.exists():
        prior=json.loads(output_path.read_text(encoding='utf-8'))
        if prior.get('sha256')!=source_sha and prior.get('objective',[None])[0]==25:
            history=OUT/'专家口径_历史25架次有界核验.json'
            if not history.exists():history.write_bytes(output_path.read_bytes())
    output_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if update_report:
        if not result['all_bounded_checks']:raise ValueError('Cannot update report after failed checks')
        update_report_text(result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['assertions','battery_chains']},ensure_ascii=False,indent=2))

def update_report_text(result):
    report=OUT/'专家口径复核.md'
    text=report.read_text(encoding='utf-8').split('## 6.')[0]
    text=text.replace('当前仅在O01充换电的25架次方案','当前仅在O01充换电的提交方案')
    n,e,c,l=result['objective'];audit=result.get('existing_raw_audit')
    if audit and audit.get('objective_matches') and audit.get('all'):
        audit_text=f"另读取同一提交目录的 `{Path(audit['source']).name}`，其中{audit['checks_count']}项原始核验记录为通过，记录四目标与当前方案匹配。它仍限于现有题设闭合假设与仅O01充换电方案，不能被扩大为完整站外换电问题的最优性证据。"
    else:
        audit_text='本次未取得与当前四目标匹配的通过状态原始数据核验记录；不得借用历史25架次方案的399项核验为当前方案背书。'
    history=SOURCE/'最终方案.json'
    hist=json.loads(history.read_text(encoding='utf-8')) if history.exists() else None
    hist_obj=hist['objective'] if hist else [25,71.31909210428417,6672.014331816174,0.]
    hist_sha=hashlib.sha256(history.read_bytes()).hexdigest() if hist else '未重读'
    dominates=all(a<=b+1e-8 for a,b in zip(result['objective'],hist_obj)) and any(a<b-1e-8 for a,b in zip(result['objective'],hist_obj))
    comparison=('按同一四目标最小化口径，新最终提交逐项不劣且至少一项更优，严格支配该历史代表。这个具体比较不等于对全部允许方案的最优性证明。'
                if dominates else '新最终提交与历史代表之间须按上表逐项比较；“最终”二字不自动构成逐目标支配或理论全局最优的证明。')
    text+=f'''## 6. 新最终提交与历史25架次方案的区分

本节已改为核验最终合并筛选后的文件 `{Path(result['source']).relative_to(ROOT)}`。**当前最终提交是下表所列{n}架次方案，旧25架次方案仅保留作历史对照，不再是本目录当前最终提交对象。**

| 对象 | N | E/kWh | C/s | L/s |
|---|---:|---:|---:|---:|
| 新最终提交 | {n} | {e:.12f} | {c:.12f} | {l:.12f} |
| 历史扩大搜索代表 | {hist_obj[0]} | {hist_obj[1]:.12f} | {hist_obj[2]:.12f} | {hist_obj[3]:.12f} |

新最终提交最晚返场为{c/60:.9f} min。当前文件SHA256为：

`{result['sha256']}`

历史扩大搜索代表位于 `改进搜索_20260924/最终方案.json`，其SHA256为 `{hist_sha}`。{comparison}

当前方案有80个唯一货箱、{result['hard_boxes']}个硬时限箱和{result['soft_boxes']}个软时限箱，软权重和{result['soft_priority_sum']:g}；使用{result['uav_count_used']}架实体无人机、{result['battery_count_used']}块共享电池。所有架次从O01出发并返O01，一架次只指定一块电池，计划没有携带备用电池或站外换装事件。按原始运输附件的电量和充电时间检查，每块电池初始在O01满电，后续复用前均有足够返场充电时间；最小返场SOC为{result['minimum_route_end_soc']:.10f}，高于0.2下限。

本次 `check_expert_plan.py`针对上述**新最终文件**完成{result['assertions_count']}项有界检查，结果见 `专家口径_当前方案有界核验.json`；历史25架次有界结果保留在 `专家口径_历史25架次有界核验.json`。这些是位置、满电复用、硬时限、资源时序与JSON算术检查，不重复声称重新推导了DEM和能耗。{audit_text}

**建议最终交付措辞：**

> 本文交付一套已核验的可行代表方案：{n}架次、{e:.6f} kWh、最晚返场{c:.6f} s，80箱均完成交付，医疗与首批硬时限满足，软箱加权迟到为{l:.6f} s。方案每架次使用一块电池、不携带备用电池，全部充换电在O01完成，兼容当前专家补充的电池初始位置与换电许可。该方案是在既定能耗假设、有限候选库及冻结偏好下选出的当前提交代表；未证明允许站外换电的完整问题全局最优。

“当前最终提交”表示本轮合并筛选后选定并交付的一套代表，不是“理论上已达最优”的同义词。缺少站外条件时，应保留并交付这套可行代表，准确披露认证范围；不能补设库存/充电能力填补题意，也不能宣称站外换电已经被证明无效。
'''
    report.write_text(text,encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--plan',type=Path,default=OUT/'最终方案.json')
    parser.add_argument('--raw-audit',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--update-report',action='store_true')
    args=parser.parse_args()
    check(args.plan,args.raw_audit,args.output,args.update_report)
