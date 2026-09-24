"""Write release documentation/CSVs from the final verified JSON, never re-solve."""
from pathlib import Path
from collections import Counter
import csv, json, hashlib

HERE = Path(__file__).resolve().parent
Q2 = HERE.parent
OLD = Q2 / '改进搜索_20260924'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def main():
    final = read(HERE / '最终方案.json')
    arc = read(HERE / '联合非支配档案.json')
    audit = read(HERE / 'final_evaluation_audit/summary.json')
    raw = read(HERE / '原始数据核验.json')
    export = read(HERE / '导出核验.json')
    expert = read(HERE / '专家口径_当前方案有界核验.json')
    assert audit['selection_matches'] and raw['all']
    assert export['all_formula_caches_verified'] and export['one_final_solution_only']
    assert export['source_objective'] == final['objective']
    n, e, c, late = final['objective']
    routes = sorted(final['routes'], key=lambda r: (r['start'], r['route_id']))
    boxes = sorted(final['boxes'], key=lambda b: b['box'])
    types = Counter(r['vehicle'] for r in routes)
    multi = sum(len(r['zones']) > 1 for r in routes)
    used_u = len({r['uav'] for r in routes})
    used_b = len({r['battery_id'] for r in routes})
    slack = min(b['deadline'] - b['delivery'] for b in boxes if b['hard'])
    soc = min(r['soc'] for r in routes)
    last = max(routes, key=lambda r: r['finish'])
    header = ['架次编号', '无人机编号', '机型编号', '电池编号', '开始时刻（s）', '访问服务区顺序', '返回O01时刻（s）', '架次能耗（kWh）']
    rows = [[r['route_id'], r['uav'], r['vehicle'], r['battery_id'], r['start'], '→'.join(['O01'] + r['zones'] + ['O01']), r['finish'], r['energy']] for r in routes]
    with (HERE / '最终方案_运输架次.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    with (HERE / '最终方案_逐箱交付.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['货箱编号', '架次编号', '服务区编号', '交付完成时刻（s）'])
        w.writerows([[b['box'], b['route_id'], b['zone'], b['delivery']] for b in boxes])
    table = '|' + '|'.join(header) + '|\n|' + '|'.join(['---'] * 8) + '|\n'
    for row in rows:
        table += '|' + '|'.join(f'{v:.6f}' if isinstance(v, float) else str(v) for v in row) + '|\n'
    (HERE / '最终架次表.md').write_text('# 问题二最终提交架次表\n\n开始时刻为准备开始；返场时间不包含最后充电。显示保留六位小数，计算与工作簿保留原精度。\n\n' + table, encoding='utf-8')
    old28 = [28, 75.711315969, 7567.094096939, 200.565886509]
    old25 = read(OLD / '最终方案.json')['objective']
    bounds = read(OLD / '89分钟与20至22架次_下界核查.json')
    lb = bounds['records'][0]['lower_seconds']
    lb66 = next(b['lower_seconds'] for b in bounds['records'] if b['name'] == 'N22_E66')
    best_c = min(arc, key=lambda p: p['objective'][2])['objective'][2]
    choose20 = min((p for p in arc if p['objective'][0] == 20 and p['objective'][3] == 0), key=lambda p: p['objective'][2])['objective']
    faster = min(arc, key=lambda p: p['objective'][2])['objective']
    economical = next(p['objective'] for p in arc if abs(p['objective'][1] - 64.6002294794056) < 1e-7)
    selected = [final, min(arc, key=lambda p: p['objective'][2]),
        min((p for p in arc if p['objective'][0] == 20 and p['objective'][3] == 0), key=lambda p: p['objective'][2]),
        next(p for p in arc if p['objective'] == economical), min(arc, key=lambda p: p['objective'][1])]
    names = ['最终综合代表', '当前档案最早返场', '20架次零迟到代表', '较低能耗22架次代表', '当前档案最低能耗']
    trade = '|方案|N|E/kWh|最晚返场/min|加权迟到/s|最坏遗憾区间|\n|---|---:|---:|---:|---:|---|\n'
    for name, p in zip(names, selected):
        f = p['objective']
        trade += f'|{name}|{f[0]}|{f[1]:.6f}|{f[2]/60:.6f}|{f[3]:.6f}|[{p["regret_lower"]:.6f}, {p["regret_upper"]:.6f}]|\n'
    archive_table = '|档案编号|N|E/kWh|C/s|L/s|遗憾下界|遗憾上界|\n|---|---:|---:|---:|---:|---:|---:|\n'
    for i, p in enumerate(arc):
        a = p['objective']
        archive_table += f'|PF{i+1:04d}|{a[0]}|{a[1]:.6f}|{a[2]:.6f}|{a[3]:.6f}|{p["regret_lower"]:.6f}|{p["regret_upper"]:.6f}|\n'
    text = rf'''# 问题二最终方案说明与核查报告

本次交付选定 **{n}架次、运输能耗{e:.6f} kWh、最晚返场{c:.6f} s（{c/60:.6f} min）、软箱加权平均迟到{late:.6f} s**。提交工作簿只含这一套完整方案。它是在既定物理假设、28216条有限候选和冻结偏好下，从本轮合并的14个已核验方案中选出的代表；未认证完整路线与站外换电空间的全局最优。

## 1. 交付文件与实际执行结构

- [问题二_结果提交.xlsx](问题二_结果提交.xlsx)：一套架次表、80箱交付表，另附资源、核验、指标及非支配档案页。
- [最终架次表.md](最终架次表.md)：完整{n}行、用户指定的8列格式；同目录两个CSV可直接使用。
- [最终方案.json](最终方案.json)：逐航段、服务事件、箱号、机体、电池、时间和SOC的完整可执行记录。
- [专家口径复核.md](专家口径复核.md)：专家补充的逻辑边界与本方案兼容性。
- [源头核查总报告](../源头核查_20260924/问题二_源头核查总报告.md)：原题、十项资料、正文、约束和代码的逐项依据。

A/B/C分别执行{types['A']}/{types['B']}/{types['C']}架次，{multi}架次访问多个服务区；实际使用{used_u}架无人机和{used_b}块电池。附件库存仍是8架机、14块电池，U01本方案未使用，不能把库存数量写成实际使用数量。每架次从O01满电领取一块匹配电池，不带备用电池，交付后返回O01，后续复用前充满。

## 2. 核查结论：定义、约束与依据

**完成时间定义正确。** 原题明确为所有运输无人机完成末架次并返回O01的最晚时刻。每条路线只归属一架无人机，因此按所有已选路线取返场最大值与按各机末次返场取最大值等价：

$$
C_{{\max}}=\max_d\max_{{k\in\mathcal K_d}}(s_k+T_k)=\max_{{k:x_k=1}}(s_k+T_k).
$$

本方案末次货箱交付为{max(b['delivery'] for b in boxes):.6f} s，末次返场为{c:.6f} s（{last['uav']}，{last['route_id']}），末电池充满为{max(r['recharge'] for r in routes):.6f} s。只有中间这个量是题目完成时间；不使用累计飞行时间、最后交货或充电结束替代。

|核查项|结论|
|---|---|
|80箱完整、不可拆分、恰好交一次及目的地|全部通过|
|16医疗、30首批，交集15|硬时限并集31箱；适用截止取最小，全部满足|
|硬时限最小裕度|{slack:.6f} s|
|其余49箱迟到指标|软权重分母460；本方案所有软箱均无迟到|
|载重、容积、各段剩余载荷|从原始箱重/体积独立复算通过|
|DEM、净空、时间和能耗|原始GeoTIFF采用独立矩形相交算法复算通过|
|资源匹配与不重叠|机体、电池分别核查；同型电池可跨机，均通过|
|初始位置、无备用、复用前100%|逐电池位置事件核查通过|
|最小返场SOC|{soc*100:.9f}%，不低于20%|
|生产核验与原始核验|14类生产检查通过；最终方案{raw['checks_count']}项原始检查通过|
|所有档案及偏好评价|14方案原始核验全部通过；完整四维支配对为0|
|提交表|{n}架次/80箱；{export['formula_count']}个公式与缓存回读一致，关键数值均为数值类型|

核查不等于能宣布所有建模解释唯一正确。水平能耗中的校准电量取电池可用能量、爬升采用势能除等效效率、准备开始即占用满电池、同批箱在交接完成时统一送达，均是明确补充假设。交接悬停能耗当前没有另行加项，已在正文共同假设5明示，不能声称文献证明实际悬停耗电为零。原题十项资料按实际全文/摘要访问层级已登记；Dorling等支持载荷和分段核算思路，不直接给出本文两条闭合式。R2具体算法和R4具体遗憾公式未获全文确认，因此只作研究背景，本文具体构造自行定义和推导。

## 3. 原结果为何较差，以及哪些实现仍应谨慎

原正式28架次方案可行，但确实搜索不足：不换路线和具体资源、仅调整开始时刻，就能降低迟到；固定28路线、开放全部同型资源，更可同时减小完成时间并达到零迟到。这是可重现的支配反例，说明结果差异不只可能来自物理公式错误，也可能来自搜索和停止策略。

本轮明确发现/处理：旧ALNS的初解回退及先锁定完成时间阻碍探索；旧工作库抽样偏窄；终端排程精修不足；候选库只按ID哈希不能隔离参数变化；旧入口绑定历史迟到数字。新增搜索独立存放，不再依靠旧入口复现某个历史目标值；本轮以完整系数哈希核对评价范围。核心联合MILP的22项微型穷举真值比对已通过，未发现这些受检结构的约束矩阵错误。

以下不能作为“已全面无误”的结论：`q2_run.py`旧入口仍用于历史流程，应使用本目录及扩大搜索目录的脚本复现新结果；有限候选没有穷尽所有多点和无交付中转路线；站外换电尚未加入完整位置/SOC事件优化。因此，新工作簿、JSON、报告必须成套使用，不混入根目录旧28架次表。

## 4. 最终求解流程与实际计算

1. 沿用已核验的物理参数、逐箱候选生成与联合MILP。上一轮已完成1120次局部联合搜索、800次初始化尝试、4个直接联合工作库任务，以及路线/资源精修。
2. 本轮对同一28216列评价库进行32次覆盖主问题与实际资源调度探测，4进程运行，19次得到核验通过的完整调度；首轮24任务126.364 s，补充8任务59.459 s。架次数始终为变量，若干N或E上限只是ε探测情景，没有设置最终N=22或N≤22。
3. 覆盖主问题中的机型工作量是搜索代理，不是可执行完成时间；必须将选择的箱组送入真实双资源调度，安排机体、电池、开始时刻及逐箱时限后才能入档。该分支不能表述为已对28216条路线同时精确求解完整成对排程MILP。
4. 并行对上一轮11个方案按机型分解、固定路线精修资源与时序；5个阶段限时，只接受经核验改进，不称为精确最优。之后合并“旧扩大搜索档案+本轮覆盖搜索档案+11个精修档案”，四维过滤后对14代表各做5 s终端精修，再原始核验。
5. 冻结尺度和偏好不变；同库12极点LP下界按完整系数哈希复用，极点可行上界由新合并档案重算，按最坏遗憾上界最小选择单一方案。

主问题及固定路线排程日志中的Optimal仅对应该次模型、权重和精度。特别是固定路线以C与L的正权和求精，不能据此称纯C全局最优。终端限时不等于不可行，已有核验解可保留。

双RTX3080Ti已对同一库各14108条候选作float64复算，全部通过。最终未新增库外路线、系数哈希一致，因此本轮复用该证据并明确不是新一轮GPU整数优化。HiGHS整数规划使用CPU并行；候选和几何数据在内存复用，不以无效占满内存为性能指标。

## 5. 多目标取舍与最终选择

{trade}

相对20架次零迟到方案，最终方案增加2架次、能耗仅增加{e-choose20[1]:.6f} kWh，最晚返场提前{(choose20[2]-c)/60:.6f} min。改用当前最快23架次方案会增加1架次和{faster[1]-e:.6f} kWh，只缩短{(c-faster[2])/60:.6f} min。另一个22架次方案能耗降低{e-economical[1]:.6f} kWh，但返场推迟{(economical[2]-c)/60:.6f} min且出现{economical[3]:.6f} s加权迟到。这些是完整方案之间的离散权衡，不能拼接单项最好值。

相对旧正式28架次，最终减少{old28[0]-n}架次，节能{old28[1]-e:.6f} kWh（{100*(old28[1]-e)/old28[1]:.3f}%），返场提前{(old28[2]-c)/60:.6f} min（{100*(old28[2]-c)/old28[2]:.3f}%），迟到从{old28[3]:.6f} s降为0。相对上一轮25架次，减少{old25[0]-n}架次，节能{old25[1]-e:.6f} kWh，返场提前{(old25[2]-c)/60:.6f} min。二者均被最终方案严格支配。

继续采用等权中心、L1半径0.3、12个偏好极点，以及冻结正尺度[15.0, 27.77981480435046, 1596.4547661131937, 459.283422915773]。平移常数在遗憾差值中抵消，无需将新方案比旧参考更好的分量截断为0。对极点v，记相同库的标量最优基准为z_v，已知LB_v≤z_v≤UB_v，则

$$
\max_v\{{\phi_v(X)-UB_v\}}\le R(X)\le\max_v\{{\phi_v(X)-LB_v\}}.
$$

两侧按遗憾非负性取不小于0。最终区间为 **[{final['regret_lower']:.12f}, {final['regret_upper']:.12f}]**，上界在14方案中最小。区间尚重叠，不能证明最终方案的真实遗憾必定小于其他每个方案，也没有精确稳健最优认证。它符合正文“基准未求精时按遗憾上界保守选择”的约定，并非根据他人22/66的数字调权。

## 6. 约89分钟到底是什么

同一有限库、O01充换电子模型的覆盖+机型累计工作量LP给出 **{lb/60:.6f} min** 下界。该松弛删除了具体机体、电池和部分时间关系，可行整数调度必满足其约束，因此在相同库与条件下下界有效；它本身不是可执行调度。

本轮最快可行方案为{best_c/60:.6f} min，同库松弛相对差距按(可行值−下界)/可行值为{100*(best_c-lb)/best_c:.3f}%。最终综合代表是{c/60:.6f} min，不能把它的综合选择误解为纯时间最小。若另设N≤22、E≤66，则同库LP下界为{lb66/60:.6f} min，最终方案满足这些额外上限，距该界{(c-lb66)/60:.6f} min；这只是情景诊断，不是最终选择的硬约束。

上述界均不是完整路线、途中换电模型的全局下界；没有对方证明也不能断言别人89 min就是相同LP。

## 7. 专家补充与最终资格

已落实“不能携带备用电池；共享电池初始均在O01”。“有电池处可换电”是许可，不要求最终方案必须执行站外换电。本方案没有站外换电、站外充电或额外库存，因此兼容当前补充规则。

但是，初始服务区无电池不等于后续不能存在电池。两机可在同地点带来各自装机电池；部分SOC能否互换、站外能否充电、换装耗时及其与整架次能量式的关系尚不明确。不能未经证明把站外换电删去并称无损。本次交付的准确名称是“已核验可行代表/最终提交方案”，不是“完整专家规则下已证全局最优”。

## 8. 复现与证据

搜索脚本在`cover_search/`与`type_polish/`；`finalize_submission.py`合并精修、计算遗憾并选定方案；`final_evaluation_audit.py`独立核查原始数据、库身份、遗憾和选择；`check_expert_plan.py`核查位置与满电复用；工作簿由既有Python导出器生成。

```powershell
& 'E:/tool/anaconda3/python.exe' '问题二/最终求解_20260924/final_evaluation_audit.py'
& 'E:/tool/anaconda3/python.exe' '问题二/改进搜索_20260924/export_search.py' --input-dir '问题二/最终求解_20260924' --output '问题二/最终求解_20260924/问题二_结果提交.xlsx'
& 'E:/tool/anaconda3/python.exe' '问题二/最终求解_20260924/write_final_report.py'
```

独立审查结论为`PASS_WITH_SCOPE_WARNINGS`；唯一提示是合并来源包含上一轮旧档案，已在本报告第4节明确，所有来源仍在同一物理库重评，非数学错误。完整系数哈希为`{read(HERE/'汇总.json')['library_coefficient_sha256']}`。同库LP证书在`../改进搜索_20260924/independent_review/LP_dual_certificates.json`；本轮身份、上界与遗憾复核在`final_evaluation_audit/`。正式10种子同预算消融及参数敏感性尚未完成，正文相应图表继续保留占位，不填造结果。

## 附：共同档案

{archive_table}
'''
    (HERE / '最终方案说明与核查报告.md').write_text(text, encoding='utf-8')
    manifest = {}
    for p in sorted(HERE.rglob('*')):
        if p.is_file() and p.name != '交付指纹.json' and '__pycache__' not in p.parts:
            manifest[str(p.relative_to(HERE))] = hashlib.sha256(p.read_bytes()).hexdigest()
    (HERE / '交付指纹.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'objective': final['objective'], 'used_uavs': used_u, 'used_batteries': used_b, 'files_hashed': len(manifest), 'report': str(HERE/'最终方案说明与核查报告.md')}, ensure_ascii=False))

if __name__ == '__main__':
    main()
