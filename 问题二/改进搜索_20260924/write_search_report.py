"""Human-readable report and immutable evidence index for completed searches."""
import json,hashlib,shutil
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
HERE=Path(__file__).resolve().parent
Q2=HERE.parent
ROOT=Q2.parent
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    arc=read(HERE/'联合非支配档案.json');final=read(HERE/'最终方案.json')
    old=read(Q2/'子问题二/最终方案.json');summary=read(HERE/'汇总.json')
    independent=read(HERE/'independent_review/summary.json')
    bounds=read(HERE/'89分钟与20至22架次_下界核查.json')
    rows=['|方案|架次|能耗/kWh|最晚返场/s|最晚返场/min|加权迟到/s|',
          '|---|---:|---:|---:|---:|---:|']
    selections=[('旧正式方案',old),('本轮综合代表',final)]
    for n in [20,21,22,23,24]:
        feasible=[p for p in arc if p['objective'][0]==n]
        if feasible:selections.append((f'{n}架次：本档案返场最早',min(feasible,key=lambda p:p['objective'][2])))
    constrained=[p for p in arc if p['objective'][0]<=22 and p['objective'][1]<=66]
    if constrained:selections.append(('不超过22架次且66 kWh：本档案返场最早',min(constrained,key=lambda p:p['objective'][2])))
    zerolate=[p for p in constrained if p['objective'][3]<=1e-7]
    if zerolate:selections.append(('不超过22架次且66 kWh：零迟到代表',min(zerolate,key=lambda p:p['objective'][2])))
    for name,p in selections:
        n,e,c,l=p['objective'];rows.append(f'|{name}|{n}|{e:.6f}|{c:.6f}|{c/60:.3f}|{l:.6f}|')
    alltables=['|编号|N|E/kWh|C/s|L/s|遗憾下界|遗憾上界|多点架次数|',
               '|---|---:|---:|---:|---:|---:|---:|---:|']
    for i,p in enumerate(arc,1):
        n,e,c,l=p['objective'];multi=sum(len(r['events'])>1 for r in p['routes'])
        alltables.append(f'|PF{i:04d}|{n}|{e:.6f}|{c:.6f}|{l:.6f}|{p["regret_lower"]:.6f}|{p["regret_upper"]:.6f}|{multi}|')
    lbrows=['|LP条件|下界/s|下界/min|','|---|---:|---:|']
    for r in bounds['records']:lbrows.append(f'|{r["name"]}|{r["lower_seconds"]:.6f}|{r["lower_minutes"]:.3f}|')
    new=final['objective'];prev=old['objective'];types=Counter(r['vehicle'] for r in final['routes'])
    multi=sum(len(r['events'])>1 for r in final['routes'])
    logs=[]
    for folder in [HERE,HERE/'run2',HERE/'target_20_22']:
        for f in folder.glob('worker_*_log.json'):logs+=read(f)
    forced=[r for r in logs if r['forced_candidate'] is not None]
    worseaccepted=sum(r['accepted'] and r['objective'] is not None for r in forced)
    text=fr'''# 问题二扩大搜索结果与核验

## 当前适用范围：O01充换电的可行基准

用户在搜索过程中补充专家规则：**不能携带备用电池；可以在有电池的地点更换，不限O01；初始共享电池全在O01。** 本轮全部数值方案均整架次使用一块电池、只在O01充换电，满足不携备用及位置要求，但只是专家新规则允许操作的一个子集。

服务区能否充电、途中换入是否必须满电，以及中途换电与原题整个架次能量上限的衔接尚待明确。**本文不把受限模型的最优、下界或未找到解解释为允许站外换电完整问题的结论。** 模型扩展及电池实体流约束见[专家补充](../源头核查_20260924/专家补充_电池位置与站外换电.md)。

## 1. 完成的搜索与主要结果

本轮主搜索没有固定28架次。路线选择、箱组、机型、具体无人机、电池与开始时间均可改变；N是目标或ε上界。固定旧28条候选的计算仅用于构造审计反例及得到可行初始解，之后对一般路线库继续搜索。

当前综合代表为 **N={new[0]}，E={new[1]:.6f} kWh，C={new[2]:.6f} s（{new[2]/60:.3f} min），L={new[3]:.6f} s**。相比旧正式方案，减少{prev[0]-new[0]}架次，节能{prev[1]-new[1]:.6f} kWh，提前返场{prev[2]-new[2]:.6f} s，软物资迟到降至0；因此在原四目标下严格支配旧代表。

所有80箱恰好交付一次，31硬箱均满足时限；最终使用8架无人机和14块电池的既定库存，具体占用以工作簿为准。机型架次分布为{dict(types)}，其中{multi}架次访问多站。该事实同时说明“先前最终全单点”不能用来证明多点访问没有价值。

当前保留{len(arc)}个互不支配方案，最终由统一冻结尺度和偏好集合下**最坏遗憾上界最小**选择，提交表只输出这一套方案；档案表用于权衡分析。

{chr(10).join(rows)}

这些都是各自完整的实际调度，不把不同方案的最低架次、能耗与最早返场拼成一套虚构结果。用户已进一步明确：“大部分人可能在22架次左右”只是参考中心，**不是N≤22的题目约束，也不是必须求到N=22**。本轮主搜索始终允许N自由变化并保留23、25等方案；20/21/22上限和66 kWh只用于部分ε探测，不作为最终代表的硬筛选。物理参数、需求、时限和核验规则没有为迎合外部数字而改变。

## 2. 89分钟的含义及本轮独立下界

89 min为5340 s。我们独立构造了“逐箱覆盖+各机型无人机累计工作量”的LP松弛：

$$
\sum_k a_{{bk}}x_k=1,\quad 0\le x_k\le1,\qquad
\sum_{{k:g_k=g}}T_kx_k\le |\mathcal U_g|C.
$$

删除具体设备时序、电池竞争和绝对交付等限制后，任何该库中的可行整数调度仍可映射为LP可行点，所以LP最优给出相同库/条件下的有效下界。按需要增加N、E的ε上限。

{chr(10).join(lbrows)}

不加架次/能耗ε时，本轮算得89.799 min，说明“约89 min”可能描述某个松弛下界，**并不意味着已达到的真实完成时间**。我们没有对方的模型和证明，不能确认两者来源相同。固定库、O01换电的限制意味着这些界不能用于否定库外路线或站外换电可能达到更短时间，也不能外推为完整题目的全局下界。

## 3. 实际计算规模与方法

- 完整单点逐箱目录19525条；一般混合货类的多点随机生成尝试24000次，再在搜索中加入释放箱组的组合和顺序替代；最终评价库共{summary['route_count']}条，物理系数指纹为`{summary['library_coefficient_sha256']}`。
- 第一轮6个进程×40步；第二轮8个进程×80步；20—22架次定向4个进程×60步，共**{len(logs)}次局部联合MILP搜索**；另有4个直接联合工作库任务、固定路线反例搜索、逐方案资源精修、12偏好LP及5个完成时间下界任务。
- 共800次新构造初始化尝试；构造失败没有计为可行方案。原已核验方案作为可选warm start，新增入口没有历史迟到数字必须复现的门槛。
- 主搜索联合改变选列、箱组/路线/机型、全部具体资源和开始时间。每次只开放当前邻域中的路线替代，是有限搜索，不是对整个评价库同时建立全规模成对资源MILP。
- 真实探索分支强制一条当前方案之外的候选且不给原warm回退，共{len(forced)}次，其中{sum(r['objective'] is not None for r in forced)}次得到可行调度，{worseaccepted}次通过接受准则；“被接受”不自动代表该次目标更差，详细数值见逐步日志。
- 终端对合并后的24个代表开放具体资源并在四目标不恶化条件下精修，然后再次过滤和统一评价。这里固定每个待精修方案的路线属于附加改进步骤，不是把整个主搜索的架次数固定为28。
- CPU并行用于HiGHS整数规划；两块RTX3080Ti分别以float64复算14108条候选，合计28216条。GPU复算核对能耗、时间、SOC和充电系数，不声称HiGHS在GPU上求解。

新算法继续使用已核验的`q2_data.py`与`JointModel`，未为不同搜索分支另写不同物理公式。首次/第二轮恢复时，历史路线编号混入纯候选造成的重复ID被独立核验拦截，已通过候选清理修正；失败日志保留，失败执行不计为成功实验。

## 4. 偏好选择及认证范围

继续沿用原冻结尺度：{summary['frozen_scale']}；权重中心(0.25,0.25,0.25,0.25)，L1半径0.3，共12个合法极点。没有根据本轮最终结果重设权重。

评价库扩展后，原K0的最优值或下界不再被当作新库下界。以新评价库的覆盖/工作量松弛给各权重下界，以统一可行档案给上界；原始四目标、平移常数处理和尺度保持一致。遗憾区间为**[{final['regret_lower']:.6f}, {final['regret_upper']:.6f}]**，仍较宽；不能把上界最小的选择说成已经精确求得完整最小最大遗憾解，也不能将此区间与旧K0区间作同域优劣比较。

{chr(10).join(alltables)}

## 5. 核验与证据

1. 原题、十项参考资料、公共假设、正文和实现逐条核查见[源头核查总报告](../源头核查_20260924/问题二_源头核查总报告.md)。独立小实例22项生产矩阵—穷举真值检查通过。
2. 最终方案从原始XLSX与GeoTIFF独立重算，{independent['final_raw_checks']}项通过；11个最终档案方案均通过原始核验且互不支配。原始几何以另一套矩形相交算法构建，不依赖生产像元采样。
3. 扩大库12个偏好LP换列/行顺序重新求解一致，并保存弱对偶证书；所有档案的基准上界、遗憾及最终选择均重算一致。
4. 电池逐段位置轨迹、初始O01、一机一块且无备用、同型匹配与返场充电位置检查通过，见`电池位置与无备用电池核验.json`。它只验证当前没有站外换电的方案，不冒充站外事件模型。
5. 双GPU复算全通过，最大能耗误差约1.78×10^-15 kWh、时间/充电误差不超过9.10×10^-13 s。
6. 提交工作簿保留原Q2列名和样式，25架次、80箱与源JSON一致；876个Excel公式缓存回读核对通过；原正式工作簿未覆盖。工作簿说明页首部明确专家补充后的受限范围。

## 6. 文件与复现

- `问题二_改进搜索结果.xlsx`：当前单一综合代表提交表、逐箱、机体/电池资源表、独立档案和范围说明。
- `最终方案.json`、`联合非支配档案.json`：完整事件与实际四目标；`frozen_evaluation_candidates.json.gz`：评价库。
- `search_expanded.py`、`run2/search_expanded_run2.py`、`search_targeted.py`、`direct_joint_search.py`：各轮Python搜索；`merge_and_finalize.py`：合并、终端精修和原始核验。
- `independent_expanded_review.py`、`verify_battery_locations_and_time_bounds.py`：偏好/LP/位置及下界复核。
- `export_search.py`：从当前最终JSON重建工作簿；`run1_snapshot/`保留第一轮代表与评价结果。

所有脚本使用指定的`E:/tool/anaconda3/python.exe`，无需安装软件包。仅重导表可执行：

```powershell
& 'E:/tool/anaconda3/python.exe' '问题二/改进搜索_20260924/export_search.py'
```

本轮没有覆盖旧正文第5章数值和旧提交表，以免在站外换电规则未明确前将受限基准冒充完整新结果。后续完整模型必须补入电池位置/SOC与合法换装事件，或在明确条件下证明站外换电不可能，才可确定能否沿用整架次单电池模型。
'''
    (HERE/'搜索结果与核验.md').write_text(text,encoding='utf-8')
    summary['battery_exchange_scope']='O01-only charging/exchange feasible subset under expert addendum; off-depot exchange not modeled'
    summary['unresolved_rules']=['off-depot charging availability','SOC requirement for mid-sortie installation','sortie-total energy rule when swapping mid-sortie']
    (HERE/'汇总.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    trace=ROOT/'.aris/traces/experiment-audit/2026-09-24_q2_source';trace.mkdir(parents=True,exist_ok=True)
    evidence=Q2/'源头核查_20260924/implementation'
    for name in ['review_request.txt','review_response.md','input_hashes.json','EXPERIMENT_AUDIT.json']:
        shutil.copyfile(evidence/name,trace/name)
    metadata=dict(review_independence='same-family',acceptance_status='provisional',
        reviewer_model='gpt-6-astra',reviewer_reasoning='ultra',reviewer_agent='/root/q2_code_fresh',
        source_model_agent_status='ERROR: capacity twice; never recorded as PASS',
        generated_at=datetime.now(timezone.utc).isoformat(),
        latest_expert_addendum=str((Q2/'源头核查_20260924/专家补充_电池位置与站外换电.md').relative_to(ROOT)),
        trace_hashes={p.name:sha(p) for p in trace.iterdir() if p.is_file()})
    (trace/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    paths=[p for p in HERE.rglob('*') if p.is_file() and p.suffix in {'.py','.json','.xlsx','.md','.gz'} and p.name!='交付指纹.json' and '__pycache__' not in p.parts]
    manifest={str(p.relative_to(HERE)):sha(p) for p in paths}
    (HERE/'交付指纹.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\n'.join(rows))
if __name__=='__main__':main()
