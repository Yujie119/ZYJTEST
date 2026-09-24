"""Summarize completed, bounded Q3 searches without rerunning or changing them."""
from pathlib import Path
import json
import math

Q3 = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((Q3/path).read_text(encoding='utf-8'))


def main():
    witness = load('审查资料/本轮复核/直接模型基准映射.json')
    assert witness['status'] == 'PASS'
    original_manifest = load('全局直接求解/20260924_直接联合120秒/冻结候选库清单.json')
    old = load('子问题二/最终方案.json')
    polish = load('搜索精修/扩展固定结构精修_v1/精修摘要.json')
    improved = load('搜索精修/扩展固定结构精修_v1/official/已核验方案.json')
    rows = []
    mode_index = {m: i for i, m in enumerate(['N', 'E', 'C', 'L'])}
    for mode in ['C', 'E', 'L', 'N']:
        folder = f'全局直接求解/扩展搜索_v3/{mode}'
        run = load(folder+'/直接联合MILP结果.json')
        manifest = load(folder+'/冻结候选库清单.json')
        same = all(manifest[k] == original_manifest[k] for k in
                   ['source_sha256', 'relay_candidate_sha256', 'records'])
        same &= run['scope']['horizon_s'] == witness['scope']['horizon_s']
        same &= run['scope']['relay_slots_per_uav'] == witness['scope']['slots_per_uav']
        caps_ok = all(witness['four_objectives'][mode_index[k]] <= cap+1e-7
                      for k, cap in run['epsilon_caps'].items())
        assert same and caps_ok, 'Cannot combine bounds across different models or caps'
        ub = witness['four_objectives'][mode_index[mode]]
        lb = run['finite_model_valid_lower_bound']
        assert lb is not None and math.isfinite(lb) and lb <= ub+1e-7
        rows.append(dict(mode=mode, caps=run['epsilon_caps'], elapsed_s=run['elapsed_s'],
                         rounds=run['iteration_count'], lower_bound=lb,
                         external_witness_upper_bound=ub, relative_gap=(ub-lb)/ub if ub else 0.,
                         same_frozen_scope_verified=same, external_witness_satisfies_caps=caps_ok,
                         new_complete_incumbent=run['candidate_plan'] is not None,
                         status=run['status'], file=folder+'/直接联合MILP结果.json'))
    summary = dict(scope='O01-only battery replacement; no carried spare batteries; fixed route/relay library',
                   expert_extended_swap_model_solved=False, direct_runs=rows,
                   summed_process_elapsed_s=sum(r['elapsed_s'] for r in rows),
                   note='Summed process elapsed is not total wall clock or measured CPU time; the four runs were concurrent.',
                   fixed_structure_elapsed_s=polish['elapsed_s'],
                   fixed_structure_verified_count=polish['verified_count'],
                   old_objective=old['objective'], improved_objective=improved['objective'],
                   improved_minus_old=[b-a for a, b in zip(old['objective'], improved['objective'])],
                   full_space_global_optimality=False)
    output = Q3/'搜索精修/扩展固定结构精修_v1'
    (output/'扩展搜索汇总.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 问题三扩展搜索结果与专家换电补充', '',
             '日期：2026-09-24。以下均为实际完成的计算；所有数值方案未携带备用电池，只在O01换电。专家允许在实际有电池的其他地点换电，故这些结果是允许域内的受限可行策略，不能视为已覆盖异地换电的完整优化。', '',
             '## 已核验的实际改进', '',
             '| 指标 | 历史正式代表 | 本轮同结构精修 | 改变量 |',
             '|---|---:|---:|---:|']
    for name, a, b in zip(['总架次（20运输＋4中继）', '总能耗/kWh', '联合最晚返O01/s', '加权迟到/s'],
                           old['objective'], improved['objective']):
        lines.append(f'| {name} | {a:.9f} | {b:.9f} | {b-a:+.9f} |')
    lines += ['', '精修保持箱组、访问路线、实体机体与电池、资源先后、中继位置及原子保障指派，只优化时序和组件充电分支。8个来源均通过原始算术和完整DEM核验，实际耗时%.3f s；相同目标的两个来源不算两个不同改进。正式结构对应452项原始算术、1015项DEM核验，新增电池位置检查307项、错误注入17项均通过。' % polish['elapsed_s'], '',
              '[改进方案表](改进方案表/改进方案说明.md)包含20条运输、80条逐箱、4条中继记录，CSV保存完整精度。历史正式Excel未覆盖；本方案不是新专家扩展模型最优或已认证的全域遗憾最优。', '',
              '## 四个全库ε条件搜索', '',
              '冻结1290个物理模式、1445个独立执行实例、24个中继位置、每机3个中继任务槽和30000 s时域。四个单线程CPU进程并行，各300 s；本轮没有新增GPU整数优化。原有双GPU几何预筛只构成既有预处理来源。', '',
              '| 主目标 | 其他目标上限（ε） | 实际进程耗时/s | 轮次 | 有效下界 | 外部已核验见证上界 | 界差（上界作分母） | 新完整可行解 |',
              '|---|---|---:|---:|---:|---:|---:|---|']
    for r in rows:
        cap = '；'.join(f'{k}≤{v}' for k, v in r['caps'].items())
        lines.append(f"| {r['mode']} | {cap} | {r['elapsed_s']:.3f} | {r['rounds']} | {r['lower_bound']:.6f} | {r['external_witness_upper_bound']:.6f} | {100*r['relative_gap']:.2f}% | {'有' if r['new_complete_incumbent'] else '未找到'} |")
    lines += ['', '上界来自此前通过原始数据、DEM及直接模型矩阵代入的10秒平移见证，并非本轮全库求解器新发现。汇总脚本核对了候选指纹、时域、槽数以及该见证满足每行ε上限。界差是相同受限模型的上下界区间，既不是真实次优比例，也不能用于允许异地换电的扩展域。冲突、缺少通信块的中间解一律不作为可行解；限时无解不等于不可行。', '',
              '此前无ε的C模型下界5689.347242 s与对应外部见证上界9165.853228 s给出37.93%的受限模型界差；它与上表含ε的C下界6786.438812 s属于不同子问题，应分别标注。', '',
              '四个进程的耗时之和为%.3f s，它们并行执行，不能把该和称为实际等待时长或测量CPU时间。早期JSON参数错误、未完成可行核验的15架次覆盖试跑均不纳入结果。' % summary['summed_process_elapsed_s'], '',
              '## 其他搜索与范围', '',
              '用最新问题二的28运输架次结构补通信，按C/L/E各60 s执行。C轮得到28运输＋5中继方案，四目标为(33,81.051258385 kWh,10644.226610315 s,576.101158553 s)，556项算术和1307项DEM检查通过；L/E轮限时无incumbent。该新结构四目标均被已有基准支配，作为初始化可行性证据保留，不作为改进。见[Q2新种子记录](../../全局直接求解/Q2新种子/搜索说明.md)。', '',
              '补充枚举发现现路线库缺少134个物理可行单站模式，尚未将其纳入本轮全库结果。因此即使当前库达到零界差，也不能据此认证全路线最优。现有Python环境只有SciPy/HiGHS可用，不支持MIP start；未安装新包。', '',
              '## 专家补充后的模型处理', '',
              '已将“不能带备用电池、允许有电池地点换电、初始O01”写入正文，并补充位置与库存守恒。异地电池可以来自已抵达并拆下工作电池的机体，不能凭空初始化。原附录整架次能耗≤单组可用能量80%的限制仍保留。异地充电、途中重新装机是否要求满电、换电耗时及落地与30m投送高度的衔接尚待明确，故不伪造一套扩展求解结果。', '',
              '[专家建模影响](../../审查资料/专家换电补充_建模影响.md)；[电池位置核验](../../审查资料/专家换电补充核验/电池位置核验.json)；[异地库存推导](../../审查资料/禁止备用电池下的异地库存守恒.md)。', '',
              '重现本汇总：运行 `问题三/审查资料/summarize_search_extension.py`。它只读取既有结果和证据，不再求解，也不覆盖正式提交文件。']
    (output/'扩展搜索与专家补充.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({'status':'PASS', 'report':str(output/'扩展搜索与专家补充.md'),
                      'four_runs_checked':len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
