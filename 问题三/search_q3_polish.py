"""Exactly retime fixed discrete Q3 structures, then independently verify.

The selected transport boxes/routes, UAV/battery identities, resource orders,
relay positions/components, and atomic communication assignments are fixed.
Continuous event times and exact two-branch component charge times are free.
This is a bounded fixed-structure MILP, not a full routing/global optimum.
No official files are modified. Only independently verified plans enter the
output archive. Defaults: at most eight structures, two workers, 300 seconds.
"""
from __future__ import annotations
import argparse
import copy
import itertools
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
from q3_common import Context, OUT, load, make_route, profile, save
from q3_direct_milp import DirectModel
from verify_q3 import Verifier
sys.path.insert(0, str(OUT / "审查资料"))
from audit_source_and_result import audit


def atomic_plan(ctx, source):
    result = copy.deepcopy(source)
    relay_by_slot = {int(r["slot"]): r for r in source["relays"]}
    fresh_routes = []
    if len({r["route_id"] for r in source["routes"]}) != len(source["routes"]):
        raise ValueError("Duplicate route instance IDs")
    for old in source["routes"]:
        fresh = make_route(ctx, old["vehicle"], copy.deepcopy(old["deliveries"]), old["route_id"])
        if fresh is None:
            raise ValueError("Route no longer physically feasible")
        for key in ("duration", "energy", "charge_s", "prep_s"):
            if abs(fresh[key] - old[key]) > 2e-6:
                raise ValueError(f"Changed coefficient {old['route_id']} {key}")
        atoms = profile(ctx, fresh, merge=False)
        if atoms is None:
            raise ValueError("Uncovered atomic geometry")
        fresh["needs"] = atoms["needs"]
        fresh["links"] = []
        for atom in fresh["needs"]:
            provider = [link["relay_slot"] for link in old["links"]
                        if link["t0"] <= atom["t0"] + 1e-7 and link["t1"] >= atom["t1"] - 1e-7
                        and int(link["relay_slot"]) in relay_by_slot
                        and int(atom["mask"]) & (1 << int(relay_by_slot[int(link["relay_slot"])] ["qid"]))]
            if not provider:
                raise ValueError("Source provider cannot cover rebuilt atomic interval")
            fresh["links"].append(dict(atom, relay_slot=int(provider[0])))
        for key in ("start", "takeoff", "finish", "recharge", "uav", "battery_id"):
            fresh[key] = old[key]
        fresh_routes.append(fresh)
    result["routes"] = fresh_routes
    return result


def solve_fixed(ctx, plan, deadline):
    model = DirectModel(); H = 30000.; big = 10000.
    routes = plan["routes"]; relays = plan["relays"]
    start, rs, dur, alpha, beta, rf, en, ch = {}, {}, {}, {}, {}, {}, {}, {}
    route_by_id = {r["route_id"]: r for r in routes}
    for r in routes:
        start[r["route_id"]] = model.var(("start", r["route_id"]), 0, min(H-r["duration"], r["latest_start"]))
    C = model.var("C", 0, H)
    for r in routes:
        model.add({start[r["route_id"]]: 1, C: -1}, hi=-r["duration"])
    expected = ctx.boxes.set_index("box")
    L, E = {}, {}
    denominator = float(ctx.boxes.loc[~ctx.boxes.hard, "priority"].sum())
    for box in plan["boxes"]:
        raw = expected.loc[box["box"]]; route = route_by_id[box["route_id"]]
        s = start[box["route_id"]]; offset = route["offsets"][raw.category]
        if bool(raw.hard):
            model.add({s: 1}, hi=float(raw.deadline)-offset)
        else:
            late = model.var(("late", box["box"]), 0, H)
            model.add({s: 1, late: -1}, hi=float(raw.expected)-offset)
            L[late] = float(raw.priority)/denominator
    for key, end in [("uav", "duration"), ("battery_id", None)]:
        for resource in sorted({r[key] for r in routes}):
            ordered = sorted([r for r in routes if r[key] == resource], key=lambda r: (r["start"], r["route_id"]))
            for a, b in zip(ordered, ordered[1:]):
                occupancy = a["duration"] + (a["charge_s"] if end is None else 0)
                model.add({start[a["route_id"]]: 1, start[b["route_id"]]: -1}, hi=-occupancy)
    for relay in relays:
        j = int(relay["slot"]); q = relay["position"]
        rs[j] = model.var(("relay_start", j), 0, H)
        dur[j] = model.var(("service_duration", j), 0, q["dmax"])
        alpha[j] = model.var(("alpha", j), 0, H)
        beta[j] = model.var(("beta", j), 0, H)
        rf[j] = model.var(("relay_finish", j), 0, H)
        en[j] = model.var(("relay_energy", j), 0, 2.56); E[en[j]] = 1
        ch[j] = model.var(("charge", j), 0, 1540)
        model.eq({alpha[j]: 1, rs[j]: -1}, 180+q["out_s"]+30)
        model.eq({beta[j]: 1, alpha[j]: -1, dur[j]: -1})
        model.eq({rf[j]: 1, beta[j]: -1}, q["back_s"])
        model.eq({en[j]: 1, dur[j]: -1.1/3600}, q["e0"])
        model.add({rf[j]: 1, C: -1}, hi=0)
        branch = model.var(("charge_branch", j), 0, 1, True)
        model.add({en[j]: 1, branch: -2.24}, hi=.32)
        model.add({en[j]: 1, branch: -.32}, lo=0)
        for sign in (1, -1):
            model.add({ch[j]: sign, en[j]: -1968.75*sign, branch: -big}, hi=0)
            model.add({ch[j]: sign, en[j]: -406.25*sign, branch: big}, hi=big+500*sign)
    for key, turnaround in [("uav", 300.), ("component", None)]:
        for resource in sorted({r[key] for r in relays}):
            ordered = sorted([r for r in relays if r[key] == resource], key=lambda r: (r["start"], r["slot"]))
            for a, b in zip(ordered, ordered[1:]):
                j, k = int(a["slot"]), int(b["slot"])
                row = {rf[j]: 1, rs[k]: -1}
                if turnaround is None:
                    row[ch[j]] = 1; model.add(row, hi=0)
                else:
                    model.add(row, hi=-turnaround)
    for route in routes:
        s = start[route["route_id"]]
        for link in route["links"]:
            j = int(link["relay_slot"])
            model.add({alpha[j]: 1, s: -1}, hi=link["t0"])
            model.add({s: 1, beta[j]: -1}, hi=-link["t1"])
    transport_energy = sum(r["energy"] for r in routes)
    model.add({C: 1}, hi=float(plan["objective"][2])+1e-5)
    model.add(L, hi=float(plan["objective"][3])+1e-5)
    model.add(E, hi=float(plan["objective"][1])-transport_energy+1e-7)
    stages = []; best = None
    for name, objective in [("C", {C: 1}), ("L", L), ("E", E)]:
        remaining = deadline-time.perf_counter()
        if remaining <= .1:
            break
        result, violation = model.run(objective, min(20., remaining), False)
        stage = dict(stage=name, status=int(result.status), message=str(result.message),
                     value=float(result.fun) if result.fun is not None else None,
                     bound=getattr(result,"mip_dual_bound",None),gap=getattr(result,"mip_gap",None),
                     violation=violation)
        stages.append(stage)
        if result.x is None or violation is None or violation > 2e-4:
            break
        best = result.x
        model.add(objective, hi=float(result.fun)+1e-7)
    if best is None:
        return None, stages
    polished = copy.deepcopy(plan)
    for route in polished["routes"]:
        s = float(best[start[route["route_id"]]])
        route.update(start=s,takeoff=s+route["prep_s"],finish=s+route["duration"],
                     recharge=s+route["duration"]+route["charge_s"])
    for relay in polished["relays"]:
        j=int(relay["slot"]); q=relay["position"]
        s=float(best[rs[j]]); d=float(best[dur[j]])
        a=s+180+q["out_s"]+30; b=a+d; f=b+q["back_s"]
        e=q["e0"]+d*1.1/3600; soc=1-e/3.2
        charge=1800*(.65*(.9-soc)/.9+.35) if soc<.9 else 1800*.35*(1-soc)/.1
        relay.update(start=s,takeoff=s+180,arrival=s+180+q["out_s"],alpha=a,beta=b,finish=f,
                     duration=d,energy=e,soc=soc,charge_s=charge,recharge=f+charge,body_ready=f+300)
    route_by_id={r["route_id"]:r for r in polished["routes"]}
    for box in polished["boxes"]:
        row=expected.loc[box["box"]];route=route_by_id[box["route_id"]]
        box["delivery"]=route["start"]+route["offsets"][row.category]
    et=sum(r["energy"] for r in polished["routes"]);er=sum(r["energy"] for r in polished["relays"])
    c=max(r["finish"] for r in polished["routes"]+polished["relays"])
    late=sum(float(expected.loc[b["box"],"priority"])*max(0.,b["delivery"]-float(expected.loc[b["box"],"expected"]))
             for b in polished["boxes"] if not bool(expected.loc[b["box"],"hard"]))/denominator
    polished.update(ET=et,ER=er,NT=len(polished["routes"]),NR=len(polished["relays"]),
                    objective=[len(polished["routes"])+len(polished["relays"]),et+er,c,late],
                    source="fixed_discrete_structure_exact_continuous_retiming",
                    status="unverified_fixed_structure_candidate")
    # A retimed/relinked plan must not inherit previous archive regret scores,
    # search gaps, or optimality metadata as if they described this solve.
    for key in list(polished):
        if key.startswith('regret_') or key in ('completion_time_lower_bound','meta'):
            polished.pop(key)
    polished['meta']={'method':'fixed_routes_resources_positions_order_polish',
                      'atomic_providers_free':False,'stages':stages,
                      'exchange_policy_scope':'O01-only exchange after return; one mounted battery per flight and no spare carriage. A restricted feasible strategy when off-site exchange is permitted.',
                      'source_objective':plan['objective'],'original_global_optimality_claim':False}
    return polished, stages


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=300)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--count',type=int,default=8)
    parser.add_argument('--out',default=None)
    args=parser.parse_args()
    begun=time.perf_counter();deadline=begun+args.seconds
    output=OUT/'搜索精修'/(args.out or datetime.now().strftime('%Y%m%d_%H%M%S'));output.mkdir(parents=True,exist_ok=True)
    ctx=Context();ctx.qs=load(OUT/'缓存/中继候选位置.json');geom=load(OUT/'缓存/区间几何.json')
    if geom['candidate_count']!=len(ctx.qs):raise ValueError('Geometry/positions mismatch')
    ctx.arc_cache={tuple(map(int,k.split(','))):v for k,v in geom['arcs'].items()}
    ctx.node_cache={int(k):v for k,v in geom['nodes'].items()}
    official=load(OUT/'子问题二/最终方案_待独立核验.json')
    witness=load(OUT/'审查资料/本轮复核/直接模型基准映射方案.json')
    archives=load(OUT/'子问题一/非支配方案明细.json')
    sources=[('official',official),('mapped_witness',witness)]
    seen={tuple(np.round(official['objective'],5)),tuple(np.round(witness['objective'],5))}
    for i,plan in enumerate(sorted(archives,key=lambda p:(p['objective'][0],p['objective'][2],p['objective'][1]))):
        key=tuple(np.round(plan['objective'],5))
        if key in seen:continue
        seen.add(key);sources.append((f'archive_{i:02d}',plan))
        if len(sources)>=args.count:break
    records=[];verified=[]
    def work(item):
        name,source=item;folder=output/name;folder.mkdir(exist_ok=True)
        if time.perf_counter()>=deadline:
            return dict(source=name,status='not_started_budget_exhausted'),None
        try:
            atomic=atomic_plan(ctx,source)
            plan,stages=solve_fixed(ctx,atomic,deadline)
            record=dict(source=name,source_objective=source['objective'],stages=stages,
                        scope='fixed routes, box assignment, resources/order, relay positions/components; optimize times and charge branches',
                        atomic_providers_free=False)
            if plan is None:
                record['status']='no_feasible_solver_incumbent';save(folder/'记录.json',record);return record,None
            verifier=Verifier(plan);verifier.verify_routes();verifier.verify_boxes();verifier.verify_relays();physical=verifier.finish()
            raw=audit(plan)
            save(folder/'独立DEM核验.json',physical);save(folder/'原始数据结构审计.json',raw)
            passed=physical['passed'] and raw['status']=='PASS'
            record.update(status='PASS' if passed else 'FAIL',objective=plan['objective'],
                          change_from_source=(np.array(plan['objective'])-np.array(source['objective'])).tolist(),
                          change_from_official=(np.array(plan['objective'])-np.array(official['objective'])).tolist(),
                          physical_check_count=len(physical['checks']),raw_check_count=len(raw['checks']))
            if passed:
                plan['status']='independently_verified_fixed_structure_polish'
                save(folder/'已核验方案.json',plan)
            else:
                save(folder/'被拒绝方案.json',plan)
            save(folder/'记录.json',record)
            print(json.dumps(record,ensure_ascii=False),flush=True)
            return record,plan if passed else None
        except Exception as error:
            record=dict(source=name,status='ERROR',error=type(error).__name__+': '+str(error))
            save(folder/'记录.json',record);print(json.dumps(record,ensure_ascii=False),flush=True)
            return record,None
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(work,item) for item in sources]
        for future in as_completed(futures):
            record,plan=future.result();records.append(record)
            if plan is not None:verified.append(plan)
            save(output/'已完成记录.json',records)
    nondom=[]
    for i,plan in enumerate(verified):
        f=np.array(plan['objective'])
        if not any(np.all(np.array(other['objective'])<=f+1e-5) and np.any(np.array(other['objective'])<f-1e-5)
                   for j,other in enumerate(verified) if j!=i):nondom.append(plan)
    summary=dict(status='completed',elapsed_s=time.perf_counter()-begun,requested_budget_s=args.seconds,
                 verification_may_finish_after_budget=True,source_count=len(sources),verified_count=len(verified),
                 nondominated_count=len(nondom),records=records,official_objective=official['objective'],
                 original_global_optimality_claim=False,official_files_modified=False)
    save(output/'精修摘要.json',summary);save(output/'已核验非支配档案.json',nondom)
    print('POLISH_COMPLETED',len(verified),'VERIFIED',len(nondom),'NONDOM',output,flush=True)


if __name__=='__main__':main()
