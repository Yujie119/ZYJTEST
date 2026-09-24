"""Independent checks: explicit labelled subsets and Pareto dynamic programming.

The verifier never calls an LP/MILP solver. It rebuilds costs from the original
input data, enumerates labelled subsets to check candidate completeness, and
uses a different algorithm to certify the full baseline Pareto objective set.
"""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import json
import math
import time
import numpy as np
import pandas as pd

from q1_core import WORK, load_inputs, generate_patterns, save_json


TOL = np.array([0,1e-9,1e-6])


def pareto(points):
    # Sort by N then E then T. Any later point cannot dominate an earlier one.
    unique=sorted(set(tuple(round(float(v),9) for v in p) for p in points))
    keep=[]
    for p in unique:
        a=np.array(p)
        if not any(np.all(np.asarray(q)<=a+TOL) for q in keep):
            keep.append(p)
    return tuple(keep)


def direct_cost(v,geo,q,n,eta=.72):
    length=v.range_empty-(v.range_empty-v.range_full)*(q/v.capacity)**1.5
    d,h1,h2=geo["distance_m"],geo["outbound_up_m"],geo["outbound_down_m"]
    energy=v.battery*(d/length+d/v.range_empty)
    energy+=9.81*((v.empty+q)*h1+v.empty*h2)/(eta*3600000)
    flight=2*d/v.speed+(h1+h2)*(1/v.up_speed+1/v.down_speed)
    operation=flight+v.prep+v.handoff_base+n*(v.load+v.handoff_box)
    return energy,flight,operation


def check_plan(plan,boxes,vehicles,geometry,rho=.2):
    seen=[]
    objectives=np.zeros(3)
    max_error=0.
    lookup=boxes.set_index("box")
    geometries=geometry.set_index("zone")
    for p in plan:
        selected=lookup.loc[p["boxes"]]
        assert selected.zone.nunique()==1 and selected.zone.iloc[0]==p["zone"]
        v=vehicles[p["vehicle"]]
        q,volume=selected.mass.sum(),selected.volume.sum()
        assert q<=v.capacity+1e-9 and volume<=v.volume+1e-9
        energy,flight,operation=direct_cost(v,geometries.loc[p["zone"]],q,len(selected))
        assert energy<=(1-rho)*v.battery+1e-8
        for actual,stored in [(q,p["mass"]),(volume,p["volume"]),(energy,p["energy"]),
                              (flight,p["fly_s"]),(operation,p["operation_s"])]:
            max_error=max(max_error,abs(actual-stored))
            assert abs(actual-stored)<1e-6,(actual,stored)
        assert abs(1-energy/v.battery-p["return_soc"])<1e-10
        seen+=p["boxes"]
        objectives+=np.array([1,energy,operation])
    assert Counter(seen)==Counter(boxes.box.tolist())
    return objectives,max_error


def check_geometry(nodes,geometry):
    """Independent vectorised segment/rectangle clipping instead of supercover."""
    from q1_core import source
    from scipy.io import loadmat
    mat=loadmat(source("镇龙乡及周边30米DEM.mat"))
    dem=mat["dem"]
    dx,_,left,_,dy,top=mat["transform"].ravel()
    ns=nodes.set_index("zone")
    x0=(ns.loc["O01","lon"]-left)/dx
    y0=(ns.loc["O01","lat"]-top)/dy
    for geo in geometry.to_dict("records"):
        row=ns.loc[geo["zone"]]
        x1,y1=(row.lon-left)/dx,(row.lat-top)/dy
        cc,rr=np.meshgrid(np.arange(math.floor(min(x0,x1))-1,math.floor(max(x0,x1))+2),
                         np.arange(math.floor(min(y0,y1))-1,math.floor(max(y0,y1))+2))
        cc,rr=cc.ravel(),rr.ravel()
        enter,leave=np.zeros(len(cc)),np.ones(len(cc))
        for a,b,low in [(x0,x1,cc),(y0,y1,rr)]:
            u=(low-a)/(b-a)
            v=(low+1-a)/(b-a)
            enter=np.maximum(enter,np.minimum(u,v))
            leave=np.minimum(leave,np.maximum(u,v))
        hit=(enter<=leave+1e-11)&(cc>=0)&(rr>=0)&(cc<dem.shape[1])&(rr<dem.shape[0])
        assert int(hit.sum())==geo["crossed_pixels"]
        assert abs(float(dem[rr[hit],cc[hit]].max())-geo["terrain_max_m"])<1e-9
    return len(geometry)


def verify():
    start=time.perf_counter()
    boxes,vehicles,geometry,nodes,manifest=load_inputs()
    current=json.loads((WORK/"输入文件校验.json").read_text(encoding="utf-8"))
    assert current==manifest,"Original inputs changed after solve"
    geometry_cases=check_geometry(nodes,geometry)
    summary=json.loads((WORK/"求解摘要.json").read_text(encoding="utf-8"))
    plan=json.loads((WORK/"子问题二/最终方案.json").read_text(encoding="utf-8"))
    objectives,error=check_plan(plan,boxes,vehicles,geometry)
    assert np.allclose(objectives,summary["final_objectives"],rtol=0,atol=1e-6)
    universe,demands,identities=generate_patterns(boxes,vehicles,geometry)
    active=[]
    for p in universe:
        geo=geometry[geometry.zone.eq(p["zone"])].iloc[0]
        v=vehicles[p["vehicle"]]
        energy,fly,operation=direct_cost(v,geo,p["mass"],p["nbox"])
        assert abs(energy-p["energy"])<1e-10 and abs(operation-p["operation_s"])<1e-7
        if energy<=.8*v.battery+1e-9:
            active.append(p)
    labelled=0
    for zone in boxes.zone.unique():
        part=boxes[boxes.zone.eq(zone)]
        n=len(part)
        mass=np.zeros(1<<n)
        volume=np.zeros(1<<n)
        for mask in range(1,1<<n):
            bit=mask&-mask
            index=bit.bit_length()-1
            mass[mask]=mass[mask^bit]+part.mass.iloc[index]
            volume[mask]=volume[mask^bit]+part.volume.iloc[index]
        geo=geometry[geometry.zone.eq(zone)].iloc[0]
        for v in vehicles.values():
            fits=(mass<=v.capacity+1e-9)&(volume<=v.volume+1e-9)
            fits[0]=False
            q=mass[fits]
            energy=direct_cost(v,geo,q,0)[0]
            count=int((energy<=.8*v.battery+1e-9).sum())
            expected=sum(p["combinations"] for p in active if p["zone"]==zone and p["vehicle"]==v.name)
            assert count==expected,(zone,v.name,count,expected)
            labelled+=count
    assert labelled==summary["labelled_candidates"]==19525
    # Independent exact multiobjective DP on each area; no dominance-pruned
    # MILP columns and no epsilon bounds are used here.
    combined=((0.,0.,0.),)
    states,local_counts=0,{}
    for zone in sorted(boxes.zone.unique()):
        keys=[k for k in demands if k.startswith(zone+":")]
        ps=[p for p in active if p["zone"]==zone]
        patterns=[(tuple(p["counts"].get(k,0) for k in keys),
                   (1.,p["energy"],p["operation_s"])) for p in ps]
        @lru_cache(None)
        def dp(state):
            if not any(state):
                return ((0.,0.,0.),)
            first=next(i for i,n in enumerate(state) if n)
            objectives=[]
            for count,cost in patterns:
                if count[first] and all(a<=b for a,b in zip(count,state)):
                    remain=tuple(b-a for a,b in zip(count,state))
                    for tail in dp(remain):
                        objectives.append(tuple(a+b for a,b in zip(cost,tail)))
            return pareto(objectives)
        local=dp(tuple(demands[k] for k in keys))
        assert local
        states+=dp.cache_info().currsize
        local_counts[zone]=len(local)
        combined=pareto(tuple(a+b for a,b in zip(left,right))
                        for left in combined for right in local)
    saved=pd.read_csv(WORK/"子问题二/非支配方案.csv")[["N","E_kWh","T_s"]].to_numpy()
    assert len(combined)==len(saved)==2,(combined,saved)
    for p in saved:
        assert any(np.allclose(p,q,rtol=0,atol=1e-6) for q in combined)
    weights=pd.read_csv(WORK/"子问题二/偏好极点核验.csv")
    ideal=np.array(summary["normalization_ideal"])
    scale=np.array(summary["normalization_scale"])
    regrets=[]
    for f in np.array(combined):
        regret=[]
        for row in weights.to_dict("records"):
            w=np.array([row["w_N"],row["w_E"],row["w_T"]])
            assert np.isclose(w.sum(),1) and np.min(w)>=0
            assert np.sum(np.abs(w-1/3))<=1/3+1e-9
            best=min(w@((np.array(g)-ideal)/scale) for g in combined)
            assert abs(best-row["best_value"])<1e-6
            regret.append(w@((f-ideal)/scale)-best)
        regrets.append(max(regret))
    assert abs(min(regrets)-summary["minimax_regret"])<1e-6
    scenarios=json.loads((WORK/"子问题三/安全余量各情景方案.json").read_text(encoding="utf-8"))
    for s in scenarios:
        check_plan(s["plan"],boxes,vehicles,geometry,s["rho"])
    # Monotonicity applies to capability/feasibility, not each component of a
    # reoptimised multiobjective representative.
    dense=np.load(WORK/"子问题三/双GPU载荷响应曲面.npz")
    q=dense["safe_load_kg"]
    filled=np.nan_to_num(q,nan=-1.)
    assert np.max(np.diff(filled,axis=1))<1e-8
    assert np.min(np.diff(filled,axis=2))>-1e-8
    workbook_path=WORK/"问题一_结果提交.xlsx"
    workbook_verified=False
    if workbook_path.exists():
        import openpyxl
        w=openpyxl.load_workbook(workbook_path,data_only=True)
        rows=list(w["Q1_单点组批"].values)[1:]
        rows=[r for r in rows if r[0] is not None]
        assert len(rows)==len(plan)==18
        assert abs(sum(r[7] for r in rows)-objectives[1])<1e-8
        assert abs(sum(r[6] for r in rows)-summary["cumulative_flight_s"])<1e-6
        for sheet in list(w)[1:]:
            assert not any(c.value is not None for row in sheet.iter_rows(min_row=2) for c in row)
        workbook_verified=True
    result=dict(status="PASS",input_hashes="match",independent_geometry_cases=geometry_cases,
                coverage="80 unique boxes exactly once; 15 zones; no cross-zone batching",
                physical_max_abs_recalculation_error=error,labelled_candidates_enumerated=labelled,
                independent_algorithm="Exact per-zone Pareto dynamic programming and additive frontier merge",
                DP_states=states,local_Pareto_counts=local_counts,global_Pareto_objectives=combined,
                minimax_regrets=regrets,SOC_scenario_plans_verified=len(scenarios),
                gpu_capacity_monotonicity="pass",submission_workbook_verified=workbook_verified,
                elapsed_s=time.perf_counter()-start)
    save_json(WORK/"独立核验结果.json",result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=="__main__":
    verify()
