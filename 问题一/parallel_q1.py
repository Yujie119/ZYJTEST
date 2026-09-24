"""Independent CPU scenario solves; data are cached once per worker."""
from collections import Counter
from q1_core import Model, active_patterns, capacity_table, minimax, expand_plan

CTX = None


def init_worker(context):
    global CTX
    CTX = context


def solve_scenario(job):
    ctx = CTX
    kind = job["kind"]
    rho, eta = job.get("rho",.2), job.get("eta",.72)
    active, all_active=active_patterns(ctx["universe"],rho,eta)
    logs=[]
    model=Model(active,ctx["demands"],logs,scenario=job["id"])
    if kind=="rho":
        row=dict(rho=rho,candidate_patterns=len(all_active),
                 labelled_candidates=sum(p["combinations"] for p in all_active),
                 retained_patterns=len(active),
                 baseline_still_feasible=rho<=ctx["baseline_critical"]+1e-9)
        capacities=capacity_table(ctx["vehicles"],ctx["geometry"],rho).to_dict("records")
        if rho>ctx["rho_feasible"]+1e-9:
            assert model.solve(model.C[0],tag="infeasibility-certificate") is None
            row.update(feasible=False)
            return dict(job=job,row=row,plan=None,capacities=capacities,logs=logs)
    center=job.get("center",(1/3,1/3,1/3))
    delta=job.get("delta",1/3)
    result=minimax(model,ctx["ideal"],ctx["scale"],delta,center)
    if result is None:
        raise RuntimeError(f"Unexpected infeasibility: {job}")
    plan=expand_plan(model,result["x"],ctx["identities"],rho)
    common=dict(N=int(result["f"][0]),E_kWh=result["f"][1],T_s=result["f"][2],
                max_regret=result["regret"],min_return_soc=min(p["return_soc"] for p in plan))
    if kind=="rho":
        ct=Counter(p["vehicle"] for p in plan)
        row.update(feasible=True,n_A=ct["A"],n_B=ct["B"],n_C=ct["C"],**common)
    elif kind=="eta":
        row=dict(eta=eta,**common)
        capacities=[]
    else:
        row=dict(center=job["center_label"],w_N=center[0],w_E=center[1],w_T=center[2],
                 delta=delta,vertices=len(result["weights"]),
                 lower_bound=result["solver_lower_bound"],**common)
        capacities=[]
    return dict(job=job,row=row,plan=plan,capacities=capacities,logs=logs)
