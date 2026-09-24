r"""Run all three subproblems. Uses only existing Python packages.

E:\tool\anaconda3\python.exe solve_q1.py
"""
from __future__ import annotations
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import json
import sys
import time
import numpy as np
import pandas as pd
import psutil

from q1_core import (
    WORK, ROOT, Model, load_inputs, generate_patterns, active_patterns,
    capacity_table, minimax, archive_insert, expand_plan, save_json, csv,
    OBJECTIVE_TOL, safe_load)
from gpu_q1 import gpu_capacity_worker
from parallel_q1 import init_worker, solve_scenario

SUB1, SUB2, SUB3 = [WORK / f"子问题{s}" for s in ("一", "二", "三")]


def adaptive_frontier(model, anchors):
    """Integer N sweep with result-driven T bounds; no fixed epsilon grid.

    If N>N_E, any efficient solution must have T<T_E, otherwise the global
    minimum-energy anchor dominates it. Maximise N subject to T<=T_E to get
    a certified bound. Each returned solution tightens T to its achieved
    value minus 0.001 s. Enumeration is complete to that numerical resolution.
    """
    nmin = round(anchors[0]["f"][0])
    energy_anchor = anchors[1]["f"]
    cap_solution = model.solve(-model.C[0], caps=[(model.C[2], energy_anchor[2] + 1e-4)],
                               tag="Pareto-N-upper-bound")
    nmax = max(round(energy_anchor[0]), round(cap_solution[1][0]))
    archive, regions = [], []
    for a in anchors:
        archive_insert(archive, a["x"], a["f"])
    for ncap in range(nmin, nmax + 1):
        tcap = np.inf
        for iteration in range(10000):
            caps = [(model.C[0], float(ncap))]
            if np.isfinite(tcap):
                caps.append((model.C[2], tcap))
            start = time.perf_counter()
            relax = model.solve(model.C[1], caps, lp=True,
                                tag=f"eps-N{ncap}-i{iteration}-LP")
            record = dict(region=len(regions)+1, N_cap=ncap,
                          T_cap_s=tcap if np.isfinite(tcap) else None,
                          LP_E_lower_kWh=relax[2] if relax else None)
            if relax is None:
                record.update(status="LP不可行剪枝", seconds=time.perf_counter()-start)
                regions.append(record)
                break
            result = model.lex([1, 0, 2], caps, tag=f"eps-N{ncap}-i{iteration}-IP")
            if result is None:
                record.update(status="整数不可行", seconds=time.perf_counter()-start)
                regions.append(record)
                break
            x, f, _ = result
            assert relax[2] <= f[1] + 1e-6
            record.update(status="整数最优", N=int(round(f[0])), E_kWh=f[1], T_s=f[2],
                          absolute_gap_kWh=f[1]-relax[2],
                          relative_gap=(f[1]-relax[2])/f[1],
                          seconds=time.perf_counter()-start)
            regions.append(record)
            archive_insert(archive, x, f)
            tcap = f[2] - .001
        else:
            raise RuntimeError("Adaptive search did not exhaust its regions")
    archive.sort(key=lambda p: tuple(p["f"]))
    return archive, regions, dict(N_min=nmin, N_max=nmax, time_resolution_s=.001,
                                 energy_tolerance_kWh=1e-7, all_regions_exhausted=True)


def pattern_rows(patterns):
    return [dict(**{k:v for k,v in p.items() if k != "counts"},
                 counts=json.dumps(p["counts"], ensure_ascii=False)) for p in patterns]


def main():
    start = time.perf_counter()
    for path in (SUB1, SUB2, SUB3):
        path.mkdir(exist_ok=True)
    boxes, vehicles, geometry, nodes, manifest = load_inputs()
    universe, demands, identities = generate_patterns(boxes, vehicles, geometry)
    patterns, raw = active_patterns(universe)
    csv(SUB1 / "航段几何.csv", geometry)
    csv(SUB1 / "最大安全载荷.csv", capacity_table(vehicles, geometry))
    csv(SUB1 / "完整候选模式.csv", pattern_rows(raw))
    csv(SUB1 / "支配筛选后模式.csv", pattern_rows(patterns))
    counts = []
    for zone in sorted(boxes.zone.unique()):
        for v in vehicles:
            rr = [p for p in raw if p["zone"]==zone and p["vehicle"]==v]
            pp = [p for p in patterns if p["zone"]==zone and p["vehicle"]==v]
            counts.append(dict(zone=zone, vehicle=v, candidate_patterns=len(rr),
                               labelled_candidates=sum(p["combinations"] for p in rr),
                               retained_patterns=len(pp)))
    csv(SUB1 / "候选规模统计.csv", counts)
    save_json(WORK / "输入文件校验.json", manifest)
    logs = []
    model = Model(patterns, demands, logs)
    dense_rhos=np.linspace(0,.6,1201)
    dense_etas=np.array([.6,.66,.72,.78,.84])
    physical_rows,physical_keys=[],[]
    for geo in geometry.to_dict("records"):
        for v in vehicles.values():
            physical_rows.append([v.empty,v.capacity,v.range_empty,v.range_full,v.battery,
                                  geo["distance_m"],geo["outbound_up_m"],geo["outbound_down_m"]])
            physical_keys.append((geo["zone"],v.name))
    gpu_pool=ProcessPoolExecutor(max_workers=2)
    shards=np.array_split(np.arange(len(physical_rows)),2)
    gpu_jobs=[gpu_pool.submit(gpu_capacity_worker,device,
                             [physical_rows[i] for i in shard],dense_rhos.tolist(),dense_etas.tolist())
              for device,shard in enumerate(shards)]
    anchors = []
    for label, order in [("最少架次", [0,1,2]), ("最小能耗",[1,0,2]), ("最短累计时间",[2,1,0])]:
        x, f, _ = model.lex(order, tag=label)
        anchors.append(dict(label=label, x=x, f=f))
        print(label, f, flush=True)
    csv(SUB2 / "单目标极值.csv",
        [dict(goal=a["label"], N=a["f"][0], E_kWh=a["f"][1], T_s=a["f"][2]) for a in anchors])
    lp_bounds = []
    for j, name in enumerate(["N", "E_kWh", "T_s"]):
        relaxation = model.solve(model.C[j]/[1,1,1000][j], lp=True, tag=f"global-LP-{name}")
        lb, ub = relaxation[1][j], anchors[j]["f"][j]
        lp_bounds.append(dict(objective=name, LP_lower_bound=lb, IP_optimum=ub,
                              absolute_gap=ub-lb, relative_gap=(ub-lb)/ub))
    csv(SUB2 / "全局连续松弛下界.csv", lp_bounds)
    archive, regions, search = adaptive_frontier(model, anchors)
    print("Pareto objectives", [p["f"].tolist() for p in archive], flush=True)
    csv(SUB2 / "自适应epsilon搜索日志.csv", regions)
    ideal = np.min([a["f"] for a in anchors], axis=0)
    nadir = np.max([p["f"] for p in archive], axis=0)
    scale = np.where(nadir > ideal + 1e-8, nadir - ideal, 1.)
    result = minimax(model, ideal, scale)
    assert result is not None
    assert any(np.all(np.abs(p["f"]-result["f"]) <= 5*OBJECTIVE_TOL) for p in archive)
    plan = expand_plan(model, result["x"], identities)
    save_json(SUB2 / "最终方案.json", plan)
    csv(SUB2 / "最终方案明细.csv", [{**p, "boxes":";".join(p["boxes"])} for p in plan])
    # This eight-column view is explicitly NOT a Q2 resource schedule.
    csv(SUB2 / "最终方案_八列架次视图.csv", [
        {"架次编号":p["sortie"], "无人机编号":None, "机型编号":p["vehicle"], "电池编号":None,
         "开始时刻（s）":None, "访问服务区顺序":f'O01→{p["zone"]}→O01',
         "返回O01时刻（s）":None, "架次能耗（kWh）":p["energy"]} for p in plan])
    pareto_rows, archive_json = [], []
    for i, p in enumerate(archive, 1):
        normalized = (p["f"] - ideal) / scale
        regret = result["weights"] @ normalized - result["optima"]
        selected = bool(np.all(np.abs(p["f"]-result["f"]) <= 5*OBJECTIVE_TOL))
        pareto_rows.append(dict(solution=f"PF{i:03}", N=int(round(p["f"][0])),
                                E_kWh=p["f"][1], T_s=p["f"][2],
                                normalized_N=normalized[0], normalized_E=normalized[1],
                                normalized_T=normalized[2], max_regret=regret.max(), selected=selected))
        archive_json.append(dict(id=f"PF{i:03}", objectives=p["f"],
                                 plan=expand_plan(model,p["x"],identities)))
    csv(SUB2 / "非支配方案.csv", pareto_rows)
    save_json(SUB2 / "非支配方案明细.json", archive_json)
    csv(SUB2 / "偏好极点核验.csv",
        [dict(vertex=i+1, w_N=w[0], w_E=w[1], w_T=w[2],
              best_value=result["optima"][i],
              selected_value=float(w @ ((result["f"]-ideal)/scale)),
              regret=float(w @ ((result["f"]-ideal)/scale)-result["optima"][i]))
         for i,w in enumerate(result["weights"])])
    jobs = []
    for center_label, center, deltas in [
            ("等权",(1/3,1/3,1/3),[0,1/6,1/3,2/3,4/3]),
            ("偏重能耗",(.2,.6,.2),[1/3]),
            ("偏重架次",(.6,.2,.2),[1/3]),
            ("偏重时间",(.2,.2,.6),[1/3])]:
        for delta in deltas:
            jobs.append(dict(id=f"preference-{center_label}-{delta}",kind="preference",
                             center_label=center_label,center=center,delta=delta))
    # Feasibility threshold is exact: all boxes can be flown individually.
    best_single = {}
    for key in demands:
        single = [p for p in universe if p["nbox"] == 1 and key in p["counts"]]
        best = max(single, key=lambda p:p["rho_crit"])
        best_single[key] = dict(critical_rho=best["rho_crit"], vehicle=best["vehicle"],
                                boxes=identities[key])
    rho_feasible = min(x["critical_rho"] for x in best_single.values())
    critical_keys = [k for k,v in best_single.items() if abs(v["critical_rho"]-rho_feasible)<1e-9]
    baseline_critical = min(p["return_soc"] for p in plan)
    critical = dict(global_feasible_rho=rho_feasible, limiting_groups=critical_keys,
                    group_thresholds=best_single, baseline_plan_feasible_rho=baseline_critical)
    save_json(SUB3 / "安全余量临界值.json", critical)
    scenarios = sorted(set([0., .1,.15,.2,.25,.3,.32,.34,.35,.36,.4,
                            baseline_critical-1e-6, baseline_critical+1e-6,
                            rho_feasible-1e-6, rho_feasible, rho_feasible+1e-6]))
    sensitivity, scenario_plans, capacity_rows, preference, eta_rows = [], [], [], [], []
    for rho in scenarios:
        jobs.append(dict(id=f"rho={rho:.9f}",kind="rho",rho=rho))
    for eta in [.6,.66,.72,.78,.84]:
        jobs.append(dict(id=f"eta={eta}",kind="eta",eta=eta))
    context=dict(universe=universe,demands=demands,identities=identities,vehicles=vehicles,
                 geometry=geometry,ideal=ideal,scale=scale,
                 baseline_critical=baseline_critical,rho_feasible=rho_feasible)
    with ProcessPoolExecutor(max_workers=8,initializer=init_worker,initargs=(context,)) as cpu_pool:
        futures=[cpu_pool.submit(solve_scenario,job) for job in jobs]
        for future in as_completed(futures):
            out=future.result()
            logs.extend(out["logs"])
            if out["job"]["kind"]=="rho":
                sensitivity.append(out["row"])
                capacity_rows.extend(out["capacities"])
                if out["plan"] is not None:
                    scenario_plans.append(dict(rho=out["row"]["rho"],plan=out["plan"]))
            elif out["job"]["kind"]=="eta":
                eta_rows.append(out["row"])
            else:
                preference.append(out["row"])
            print("Completed",out["job"]["id"],out["row"],flush=True)
    sensitivity.sort(key=lambda r:r["rho"])
    scenario_plans.sort(key=lambda r:r["rho"])
    capacity_rows.sort(key=lambda r:(r["rho"],r["zone"],r["vehicle"]))
    eta_rows.sort(key=lambda r:r["eta"])
    preference.sort(key=lambda r:(r["center"],r["delta"]))
    csv(SUB2 / "偏好敏感性.csv", preference)
    csv(SUB3 / "安全余量方案响应.csv",sensitivity)
    csv(SUB3 / "安全余量安全载荷.csv",capacity_rows)
    save_json(SUB3 / "安全余量各情景方案.json",scenario_plans)
    csv(SUB3 / "爬升效率敏感性.csv",eta_rows)
    dense_capacity=np.empty((len(physical_rows),len(dense_rhos),len(dense_etas)))
    gpu_info=[]
    for shard,future in zip(shards,gpu_jobs):
        values,info=future.result()
        dense_capacity[shard]=values
        gpu_info.append(info)
    gpu_pool.shutdown()
    # Deterministic CPU/GPU cross-checks, including infeasible boundaries.
    max_gpu_difference=0.
    for i in range(len(physical_rows)):
        zone,vehicle=physical_keys[i]
        geo=geometry[geometry.zone.eq(zone)].iloc[0].to_dict()
        for ri,ei in [(0,0),(400,2),(700,4),(1200,2)]:
            q,_=safe_load(vehicles[vehicle],geo,float(dense_rhos[ri]),float(dense_etas[ei]))
            qgpu=dense_capacity[i,ri,ei]
            assert np.isclose(q,qgpu,atol=1e-8,rtol=1e-9,equal_nan=True),(i,ri,ei,q,qgpu)
            if np.isfinite(q):
                max_gpu_difference=max(max_gpu_difference,abs(q-qgpu))
    np.savez_compressed(SUB3/"双GPU载荷响应曲面.npz",rho=dense_rhos,eta=dense_etas,
                        safe_load_kg=dense_capacity,keys=np.array(physical_keys))
    resources=dict(cpu_logical=psutil.cpu_count(),cpu_physical=psutil.cpu_count(logical=False),
                   memory_total_bytes=psutil.virtual_memory().total,
                   parent_rss_bytes=psutil.Process().memory_info().rss,cpu_worker_processes=8,
                   solver_threads_per_worker=1,parallel_scenarios=len(jobs),gpus=gpu_info,
                   gpu_cpu_comparisons=180,max_gpu_cpu_difference_kg=max_gpu_difference,
                   physical_cases=int(dense_capacity.size),
                   memory_policy="In-memory pattern library, sparse matrices and per-worker input cache; no artificial memory saturation",
                   gpu_role="Float64 batched safe-load bisection; CPU-only HiGHS solves LP/MILP",
                   openmp_policy="MKL_THREADING_LAYER=SEQUENTIAL; KMP_DUPLICATE_LIB_OK is not enabled")
    save_json(WORK/"计算资源记录.json",resources)
    csv(SUB2 / "全部求解器日志.csv",logs)
    model_counts=Counter(p["vehicle"] for p in plan)
    summary=dict(
        scope="Q1 only: no physical UAV, battery scheduling, deadlines or communication constraints",
        energy_assumptions="正文2.1假设1–4; E_cal=E_use; eta=0.72; baseline rho=0.20",
        boxes=len(boxes),zones=boxes.zone.nunique(),total_mass_kg=boxes.mass.sum(),
        total_volume_m3=boxes.volume.sum(),candidate_patterns=len(raw),
        labelled_candidates=sum(p["combinations"] for p in raw),retained_patterns=len(patterns),
        equivalent_pattern_variables="nonnegative integers; equivalent to labelled 0-1 set partition",
        search=search,pareto_count=len(archive),normalization_ideal=ideal,
        normalization_nadir=nadir,normalization_scale=scale,
        preference_center=[1/3]*3,preference_delta=1/3,
        final_objectives=result["f"],minimax_regret=result["regret"],
        minimax_lower_bound=result["solver_lower_bound"],
        model_counts=dict(model_counts),min_return_soc=min(p["return_soc"] for p in plan),
        baseline_plan_feasible_rho=baseline_critical,global_feasible_rho=rho_feasible,
        cumulative_flight_s=sum(p["fly_s"] for p in plan),
        elapsed_s=time.perf_counter()-start,solver="scipy.optimize.milp / HiGHS",
        resources=resources,
        guarantee="All epsilon regions exhausted at 0.001 s resolution; final minimax additionally solved on full integer set",
        submission_time_definition="往返时间(s)=outbound+return flight time; 累计作业时间 also includes preparation/loading/handoff",
        submission_Q2_schedule_fields="not applicable to Q1; leave blank, never invent UAV/battery/start timestamps")
    save_json(WORK/"求解摘要.json",summary)
    print("FINAL",json.dumps(summary,ensure_ascii=False,default=lambda x:x.tolist() if isinstance(x,np.ndarray) else int(x)),flush=True)
    if "--compute-only" not in sys.argv:
        from report_q1 import make_outputs
        make_outputs()


if __name__=="__main__":
    main()
