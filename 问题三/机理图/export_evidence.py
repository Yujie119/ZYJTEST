"""Export plot evidence, verify plotted quantities, and emit LaTeX includes."""
from pathlib import Path
import csv
import hashlib
import json
import math

OUT = Path(__file__).resolve().parent
Q3 = OUT.parent


def main():
    data = json.loads((OUT / 'mechanism_data.json').read_text(encoding='utf-8'))
    target = OUT / '数据摘录'
    target.mkdir(exist_ok=True)
    checks = {}

    def check(name, condition):
        checks[name] = bool(condition)
        if not condition:
            raise ValueError(name)

    def write_csv(name, fields, rows):
        with (target / name).open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    check('source_sha256_match', all(hashlib.sha256((Q3 / s['path']).read_bytes()).hexdigest() == s['sha256'] for s in data['sources']))
    check('six_finite_archive_vectors', len(data['archive']) == 6 and all(math.isfinite(v) for r in data['archive'] for v in r['objective']))
    selections = [data['archive'][r['best']]['id'] if r['best'] is not None else None for r in data['filters']]
    check('lexicographic_representatives_C_L_E_N', selections == ['CA04', 'CA01', None])
    check('epsilon_eligible_counts', [len(r['eligible']) for r in data['filters']] == [4, 1, 0])
    rows = [r for c in data['chains'] for r in c['rows']]
    check('64_calls_19_solver_returns', len(rows) == 64 and sum(bool(r['feasible']) for r in rows) == 19)
    check('weights_finite_positive', all(math.isfinite(v) and v > 0 for r in rows for v in r['operator_weights']))
    check('historical_forced_fifth_step', data['chains'][0]['rows'][4]['operator'] == 'global_resource_retime')
    check('same_domain_bounds_recorded', all(r['same_frozen_scope_verified'] and r['external_witness_satisfies_caps'] for r in data['old_bounds']))
    check('old_gap_arithmetic', all(math.isclose(r['relative_gap'], (r['external_witness_upper_bound'] - r['lower_bound']) / max(1, abs(r['external_witness_upper_bound'])), abs_tol=1e-12) for r in data['old_bounds']))
    run = next(r for r in data['long_runs'] if r['scalar_objective'] == 'C')
    duals = [r['dual_bound'] for r in run['iterations'] if r.get('dual_bound') is not None]
    check('C_lower_bound_matches_maximum', math.isclose(max(duals), run['finite_model_valid_lower_bound'], abs_tol=1e-8))
    check('C_has_no_new_complete_incumbent', not any(r.get('accepted_as_feasible', False) for r in run['iterations']))
    toy = data['toy']
    check('toy_LP_IP_consistency', math.isclose(sum(toy['LP']), toy['LB']) and min(map(sum, toy['integers'])) == toy['UB'])

    write_csv('历史核验档案.csv', ['id', 'N', 'E_kWh', 'C_joint_s', 'L_s'], [dict(zip(['id', 'N', 'E_kWh', 'C_joint_s', 'L_s'], [r['id'], *r['objective']])) for r in data['archive']])
    write_csv('图1_事后阈值.csv', ['scenario', 'N_cap', 'E_cap', 'L_cap', 'known_eligible', 'representative'], [dict(scenario=i+1, N_cap=r['caps']['N'], E_cap=r['caps']['E'], L_cap=r['caps']['L'], known_eligible=len(r['eligible']), representative=selections[i] or '') for i,r in enumerate(data['filters'])])
    write_csv('图2_历史阈值.csv', ['seed', 'wave', 'N_cap', 'E_cap', 'L_cap', 'solver_return_count'], [dict(seed=c['seed'], wave=c['wave']+1, N_cap=c['caps']['N'], E_cap=c['caps']['E'], L_cap=c['caps']['L'], solver_return_count=c['returned_count']) for c in data['chains']])
    fields = ['seed', 'iteration', 'operator', 'solver_returned', 'w_random', 'w_communication', 'w_energy', 'w_relay_linked']
    write_csv('图2图3_历史调用及权重.csv', fields, [dict(zip(fields, [r['seed'], r['iteration']+1, r['operator'], r['feasible'], *r['operator_weights']])) for r in rows])
    write_csv('图5_旧库界差.csv', ['objective', 'LB', 'UB', 'gap', 'caps'], [dict(objective=r['mode'], LB=r['lower_bound'], UB=r['external_witness_upper_bound'], gap=r['relative_gap'], caps=json.dumps(r['caps'], ensure_ascii=False)) for r in data['old_bounds']])
    crows = []
    elapsed = 0
    best = None
    for r in run['iterations']:
        elapsed += r['elapsed_s']
        dual = r.get('dual_bound')
        if dual is not None:
            best = dual if best is None else max(best, dual)
        crows.append(dict(iteration=r['iteration']+1, cumulative_solver_s=elapsed, raw_dual_bound_s=dual, running_LB_s=best, incumbent_returned=r['incumbent_available'], accepted_as_feasible=r.get('accepted_as_feasible', False)))
    write_csv('图5_新库C下界.csv', list(crows[0]), crows)

    names = ['图1_epsilon约束与联合目标条件筛选', '图2_自适应阈值空间与实际探索状态', '图3_ALNS关联破坏修复与算子自适应', '图4_连续松弛与逐轮补约束的解空间', '图5_同域界差与扩库后的下界进展']
    captions = [
        '历史核验档案的事后ε条件筛选。空心点被阈值排除，叉号是档案内按联合完成时间、迟到、能耗、架次数顺序选出的条件代表。阴影仅表示目标阈值；空档案不等于模型不可行。',
        '自适应ε搜索的区域示意与历史记录。(a)概念性区域细分；(b)两波实际阈值；(c)64次历史调用的候选返回状态。19次求解器返回不等于19次独立核验通过，8条链也不是独立重复实验。',
        '运输—中继关联驱动的ALNS。(a)邻域和修复点为示意；(b)Q3-R001全部9条保障关联中的4条摘录，其余5条省略，实际修复须覆盖全部受影响关系；(c)完整核验后入档的规范流程；(d)历史链202631的更新后归一化算子权重。第5次执行全局资源重排，权重轨迹不能解释为独立算子效果比较。',
        '连续松弛及延迟补约束的几何解释。(a)合成二维整数规划，LP下界为8/3、整数最优值为3；(b)冻结候选库、阈值、目标和时域后外松弛包含完整有限模型。示意边界不代表实际无人机物理解空间。',
        '固定模型下的界差与下界进展。(a)1445实例库四个不同ε子问题的上下界，各自以上界归一化；(b)1596实例库C子问题在各轮结束时记录的累计有效下界，横轴为累计求解时间。底部叉号仅为不完整松弛候选的状态。两库证书分别解释，本轮没有新增完整核验方案。',
    ]
    tex = ['% Compile with XeLaTeX and a Chinese-capable document class; requires graphicx.', '% Paths below assume a .tex file in 正文/. All caps, library scopes and schematic labels must be retained.']
    for i, (name, cap) in enumerate(zip(names, captions), 1):
        if i in [1, 2, 3, 5]:
            cap += '实际方案、搜索及相应证书限于禁止携带备用电池、仅O01换电的受限策略。'
        if i == 5:
            cap += '各标量子问题的冻结阈值见随附机理图说明第5节的ε约束表；纳入正文时应同步引用该表。'
        tex.extend([r'\begin{figure}[htbp]', r'\centering', r'\includegraphics[width=0.98\textwidth]{../问题三/机理图/' + name + '.pdf}', '\\caption{' + cap.replace('ε', r'$\varepsilon$') + '}', '\\label{fig:q3-mechanism-' + str(i) + '}', r'\end{figure}', ''])
    (OUT / 'latex_includes.tex').write_text('\n'.join(tex), encoding='utf-8')
    artifacts = []
    for name in names:
        for ext in ['png', 'pdf', 'svg']:
            p = OUT / (name + '.' + ext)
            check('export_nonempty_' + p.name, p.exists() and p.stat().st_size > 1000)
            artifacts.append(dict(file=p.name, bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    report = dict(scope='Plot evidence and export verification only; not a new physical feasibility audit or solver run.', checks=checks, all_passed=all(checks.values()), sources=data['sources'], artifacts=artifacts)
    (OUT / '核验记录.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('PLOT_EVIDENCE_CHECKED', len(checks), 'checks', len(artifacts), 'figure exports')


if __name__ == '__main__':
    main()
