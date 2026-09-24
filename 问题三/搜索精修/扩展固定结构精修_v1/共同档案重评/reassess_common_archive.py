"""Reassess existing verified Q3 results on one frozen preference scale.

No optimization or physical verification is performed. Source PASS artifacts
are required and their stored/recomputed objectives checked. This is regret
inside the listed O01-exchange archive only, never a full-domain certificate.
"""
from __future__ import annotations
import csv
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

OUT=Path(__file__).resolve().parent
Q3=OUT.parents[2]
POLISH=OUT.parent
TOL=np.array([0.,2e-6,2e-4,2e-4])


def load(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def evidence(path):
    value=load(path)
    if value.get('status')!='PASS':raise ValueError(f'No PASS evidence: {path}')
    return value,dict(path=str(path.relative_to(Q3)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),status='PASS')


def main():
    scales_path=Q3/'子问题一/冻结比较尺度.json'
    weights_path=Q3/'子问题一/偏好极点与有效下界.json'
    scales=load(scales_path);old=load(weights_path)
    ideal=np.asarray(scales['ideal_reference'],float);scale=np.asarray(scales['scale'],float)
    weights=np.asarray(old['weights'],float)
    if weights.shape!=(12,4) or np.any(weights<0) or not np.allclose(weights.sum(1),1):
        raise ValueError('Invalid twelve preference vertices')
    expected=[]
    for i,j in itertools.permutations(range(4),2):
        w=np.asarray(scales['center'],float).copy();w[i]+=scales['delta']/2;w[j]-=scales['delta']/2;expected.append(w)
    if not np.allclose(weights,np.asarray(expected)):raise ValueError('Original vertices disagree with frozen preference region')
    if ideal.shape!=(4,) or scale.shape!=(4,) or np.any(scale<=0):raise ValueError('Invalid frozen normalization')
    specs=[]
    polish_summary=load(POLISH/'精修摘要.json')
    if polish_summary['verified_count']!=8:raise ValueError('Expected eight separately verified polish sources')
    for record in polish_summary['records']:
        if record['status']!='PASS':raise ValueError('Failed polish source in manifest')
        name=record['source'];folder=POLISH/name
        specs.append(('polish_'+name,folder/'已核验方案.json',folder/'独立DEM核验.json',folder/'原始数据结构审计.json'))
    audit=Q3/'审查资料/本轮复核'
    specs.extend([
        ('original_official',Q3/'子问题二/最终方案_待独立核验.json',audit/'baseline_完整DEM核验.json',audit/'原始工作簿独立算术复核.json'),
        ('ten_second_departure_witness',audit/'支配见证方案.json',audit/'witness_完整DEM核验.json',audit/'支配见证原始数据算术复核.json'),
        ('new_Q2_seed',Q3/'全局直接求解/Q2新种子/1_C_原运输资源次序_已核验方案.json',
         Q3/'全局直接求解/Q2新种子/1_C_原运输资源次序_原DEM核验.json',
         Q3/'全局直接求解/Q2新种子/1_C_原运输资源次序_原始算术核验.json')])
    sources=[];groups=[]
    for source,path,physical_path,raw_path in specs:
        plan=load(path);physical,pe=evidence(physical_path);raw,re=evidence(raw_path)
        f=np.asarray(plan['objective'],float)
        if f.shape!=(4,) or not np.all(np.isfinite(f)):raise ValueError('Invalid objective')
        for field in ('objective_stored','objective_recomputed'):
            if field not in physical or not np.all(abs(np.asarray(physical[field])-f)<=TOL+1e-9):
                raise ValueError(f'PASS objectives do not match source {source}: {field}')
        if physical.get('failure_count')!=0 or not physical.get('passed'):
            raise ValueError('Physical evidence contains failures')
        if physical.get('routes')!=len(plan['routes']) or physical.get('relays')!=len(plan['relays']) or physical.get('boxes')!=len(plan['boxes']):
            raise ValueError('Evidence plan counts mismatch')
        if abs(float(raw['transport_energy'])-float(plan['ET']))>2e-6 or abs(float(raw['weighted_lateness'])-float(f[3]))>2e-4:
            raise ValueError('Raw arithmetic evidence mismatch')
        item=dict(source=source,plan_path=str(path.relative_to(Q3)),plan_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  objective=f.tolist(),physical_evidence=pe,raw_evidence=re,
                  evidence_binding='Existing PASS artifacts; matching objectives, counts, transport energy and lateness. No repeated physical solve/check.')
        sources.append(item)
        matches=[g for g in groups if np.all(abs(np.asarray(g['objective'])-f)<=TOL)]
        if matches:matches[0]['sources'].append(source)
        else:groups.append(dict(id=f'CA{len(groups)+1:02d}',objective=f.tolist(),sources=[source],representative_path=item['plan_path']))
    F=np.asarray([g['objective'] for g in groups]);Z=(F-ideal)/scale
    utility=Z@weights.T;baseline=utility.min(axis=0)
    regret=utility-baseline[None,:]
    nondominated=[]
    for i,g in enumerate(groups):
        dominators=[groups[j]['id'] for j in range(len(groups)) if j!=i and
                    np.all(F[j]<=F[i]+TOL) and np.any(F[j]<F[i]-TOL)]
        g.update(dominated_by=dominators,nondominated=not dominators,
                 normalized_objective=Z[i].tolist(),regret_archive=float(regret[i].max()),
                 worst_vertex_indices=(np.flatnonzero(abs(regret[i]-regret[i].max())<=1e-12)+1).tolist(),
                 regrets_by_vertex=regret[i].tolist())
        if not dominators:nondominated.append(g)
    winner=min(nondominated,key=lambda g:(g['regret_archive'],g['objective'][2],g['id']))
    official=next(g for g in groups if 'polish_official' in g['sources'])
    vertex_records=[]
    for k,w in enumerate(weights):
        vertex_records.append(dict(vertex=k+1,weight=w.tolist(),archive_minimum_utility=float(baseline[k]),
                                   archive_optimum_ids=[groups[i]['id'] for i in range(len(groups)) if abs(utility[i,k]-baseline[k])<=1e-12]))
    summary=dict(status='PASS',input_source_count=len(sources),unique_objective_count=len(groups),
                 unique_nondominated_objective_count=len(nondominated),
                 objective_order=['total_sorties','total_energy_kWh','joint_return_s','weighted_mean_lateness_s'],
                 objective_dedup_and_dominance_tolerance=TOL.tolist(),
                 frozen_ideal_reference=ideal.tolist(),frozen_scale=scale.tolist(),weights=weights.tolist(),
                 representative_id=winner['id'],representative_sources=winner['sources'],
                 representative_objective=winner['objective'],representative_regret_archive=winner['regret_archive'],
                 polished_official_is_representative=winner['id']==official['id'],
                 scope='Only this explicitly listed O01-exchange restricted-strategy archive; no carried spare batteries; all complete-sortie original energy limits retained.',
                 full_domain_regret_claim=False,old_regret_upper_reused=False,physical_verification_repeated=False,
                 explanation='Maximum over the original twelve preference vertices of normalized utility minus the minimum utility in this common archive. A restricted-archive representative, not the optimum over all routes/swap locations.',
                 source_scale_file=str(scales_path.relative_to(Q3)),source_weights_file=str(weights_path.relative_to(Q3)))
    save('共同档案重评摘要.json',summary);save('输入来源与核验证据.json',sources)
    save('目标去重共同档案.json',groups);save('去重非支配档案.json',nondominated)
    save('十二偏好极点重评.json',vertex_records)
    with (OUT/'共同档案目标与遗憾.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['方案ID','全部来源','总架次','总能耗kWh','联合返场s','加权平均迟到s','非支配','支配该方案者','档案内最大遗憾','最坏极点'])
        for g in groups:writer.writerow([g['id'],';'.join(g['sources']),*g['objective'],g['nondominated'],';'.join(g['dominated_by']),g['regret_archive'],';'.join(map(str,g['worst_vertex_indices']))])
    with (OUT/'十二权重效用与遗憾.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['方案ID','极点','wN','wE','wC','wL','归一化加权效用','档案最佳效用','遗憾'])
        for i,g in enumerate(groups):
            for k,w in enumerate(weights):writer.writerow([g['id'],k+1,*w,utility[i,k],baseline[k],regret[i,k]])
    rows=['| 方案 | 来源 | 架次 | 能耗/kWh | 联合返场/s | 加权迟到/s | 档案内最大遗憾 |',
          '|---|---|---:|---:|---:|---:|---:|']
    for g in sorted(nondominated,key=lambda x:x['regret_archive']):
        n,e,c,l=g['objective'];rows.append(f"| {g['id']} | {'、'.join(g['sources'])} | {n} | {e:.9f} | {c:.6f} | {l:.6f} | {g['regret_archive']:.9f} |")
    text=fr'''# 共同档案重评

本次仅整理已有已核验结果，不进行重新求解。8 个精修来源、原正式方案、提前 10 秒的见证及问题二新种子唯一可行方案，共 **{len(sources)} 个来源**，合并数值重复目标后为 **{len(groups)} 组目标**，其中 **{len(nondominated)} 组不同非支配目标**。每个来源的完整 DEM 与原始算术 PASS 文件均存在，且目标、数量及能耗/迟到与本次输入一致；输入和证据路径、SHA-256 见 `输入来源与核验证据.json`。

沿用原冻结理想参考点与尺度，以及原 12 个偏好极点，重新计算

$$
z_k(x)=\frac{{f_k(x)-f_k^{{ref}}}}{{s_k}},\qquad
R_{{\mathcal A}}(x)=\max_{{w\in V(W)}}\left[w^Tz(x)-\min_{{y\in\mathcal A}}w^Tz(y)\right].
$$

代表方案为 **{winner['id']}**，来源为 **{'、'.join(winner['sources'])}**，目标为 **{winner['objective']}**，档案内最大遗憾为 **{winner['regret_archive']:.12f}**。因此，精修后的 official **{'仍是' if summary['polished_official_is_representative'] else '不是'}**这个小公共档案的代表方案。

本次零遗憾表示该方案在全部 12 个偏好极点上都取得当前档案中的最低归一化加权效用；不表示全可行域零遗憾或不存在更优方案。

{chr(10).join(rows)}

数值重复与支配比较容差按目标次序为 {TOL.tolist()}。保留所有来源，不把 official 与 mapped_witness 两个相同结果算成两种不同方案。冻结参考点是比较基准；个别归一化坐标为负属于方案优于历史参考点，不作截断。

结论仅适用于上述 **仅 O01 换电、无备用电池携带的受限策略档案**。原完整架次能耗约束继续保留。没有复用旧 `regret_upper` 或旧外松弛界；这里不是所有路线、所有异地换电策略上的最小最大遗憾证明。复现运行本目录 `reassess_common_archive.py` 即可。
'''
    (OUT/'共同档案重评说明.md').write_text(text,encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
