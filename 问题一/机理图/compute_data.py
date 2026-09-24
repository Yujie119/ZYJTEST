"""Recompute exact projected sets and global relaxation certificates; no toy data."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from q1_core import *  # set numerical-runtime environment before NumPy/SciPy
from scipy.spatial import ConvexHull

OUT = Path(__file__).resolve().parent


def projected_lp_polygon(model, projection, label):
    """Support-oracle reconstruction, certified against every final hull edge.

    Coordinates are scaled for numerical stability. Each boundary edge is
    checked by an LP over the original polytope, not by angular sampling alone.
    """
    points = []
    scale = np.maximum(np.max(np.abs(projection), axis=1), 1.)
    P = projection / scale[:, None]

    def support(direction):
        result = model.solve(-direction @ P, lp=True, tag=label)
        assert result is not None
        x = result[0]
        assert np.max(np.abs(model.A @ x-model.b)) < 1e-7
        return P @ x

    for d in np.array([[1,0], [-1,0], [0,1], [0,-1]]):
        points.append(support(d))
    for iteration in range(200):
        pts = np.unique(np.round(points, 11), axis=0)
        hull = ConvexHull(pts)
        additions, worst = [], 0.
        for normal_offset in hull.equations:
            direction, offset = normal_offset[:2], normal_offset[2]
            p = support(direction)
            violation = float(direction @ p + offset)
            worst = max(worst, violation)
            if violation > 1e-8:
                additions.append(p)
        if not additions:
            return pts[hull.vertices]*scale, dict(iterations=iteration+1,
                max_scaled_support_violation=worst, vertices=len(hull.vertices))
        points.extend(additions)
    raise RuntimeError('Projection did not converge')


def enumerate_integer(model):
    A = model.A.toarray().astype(int)
    out = []
    def visit(remaining, start, x):
        if not remaining.any():
            out.append(x.copy())
            return
        for j in range(start, A.shape[1]):
            if x[j] < model.ub[j] and np.all(A[:,j] <= remaining):
                x[j] += 1
                visit(remaining-A[:,j], j, x)
                x[j] -= 1
    visit(model.b.astype(int), 0, np.zeros(A.shape[1], dtype=int))
    return np.array(out)


def main():
    boxes, vehicles, geometry, nodes, manifest = load_inputs()
    universe, demands, identities = generate_patterns(boxes, vehicles, geometry)
    patterns, raw = active_patterns(universe, rho=.2, eta=.72)
    logs = []
    model = Model(patterns, demands, logs, 'global_463')
    # Initialize HiGHS shared scheduler with the core's single-thread setting
    # before linprog, whose default can otherwise conflict with milp threads=1.
    model.solve(model.C[0], tag='initialize_highs_scheduler')
    front = pd.read_csv(WORK/'子问题二'/'非支配方案.csv')
    final = front.loc[front.selected].iloc[0]
    final_f = final[['N','E_kWh','T_s']].to_numpy(dtype=float)
    plan = json.loads((WORK/'子问题二'/'最终方案.json').read_text(encoding='utf-8'))
    fixed = np.sum([[1,p['energy'],p['operation_s']] for p in plan if p['zone'] != 'S008'], axis=0)
    local = Model([p for p in patterns if p['zone']=='S008'],
        {k:v for k,v in demands.items() if k.startswith('S008:')}, logs, 'S008_23')
    X = enumerate_integer(local)
    assert len(X) and np.all(X @ local.A.toarray().T == local.b)
    D = np.array([[p['vehicle']==g for p in local.patterns] for g in ('B','C')], dtype=float)
    decision_points = X @ D.T
    local_f = X @ local.C.T
    global_f = local_f + fixed
    assert np.min(np.linalg.norm(global_f-final_f,axis=1)) < 1e-6
    for _,row in front.iterrows():
        assert np.min(np.linalg.norm(global_f-row[['N','E_kWh','T_s']].to_numpy(float),axis=1)) < 1e-6
    decision_lp, decision_certificate = projected_lp_polygon(local, D, 'decision_projection')
    objective_lp, objective_certificate = projected_lp_polygon(local, local.C[[1,2]], 'objective_projection')
    decision_unique = np.unique(decision_points, axis=0)
    objective_unique = np.unique(np.round(local_f[:,[1,2]], 9), axis=0)
    # S003 has an actual lower-bound gap; S008 explains the tradeoff but its
    # individual objective minima coincide with its LP minima.
    relax_model = Model([p for p in patterns if p['zone']=='S003'],
        {k:v for k,v in demands.items() if k.startswith('S003:')}, logs, 'S003_53')
    RX = enumerate_integer(relax_model)
    RD = np.array([[p['vehicle']==g for p in relax_model.patterns] for g in ('B','C')],float)
    rdp = np.unique(RX@RD.T,axis=0)
    rop = RX@relax_model.C[[1,2]].T
    rdlp,rdcert=projected_lp_polygon(relax_model,RD,'S003_decision')
    rolp,rocert=projected_lp_polygon(relax_model,relax_model.C[[1,2]],'S003_objective')
    rminlp=relax_model.solve(relax_model.C[1],lp=True,tag='S003_min_E_LP')
    rminip=relax_model.solve(relax_model.C[1],tag='S003_min_E_IP')
    relaxation=dict(zone='S003',patterns=len(relax_model.patterns),solutions=len(RX),
        decision_points=rdp,decision_IP_hull=rdp[ConvexHull(rdp).vertices],
        decision_LP=rdlp,decision_certificate=rdcert,
        objective_points=rop,objective_IP_hull=rop[ConvexHull(rop).vertices],
        objective_LP=rolp,objective_certificate=rocert,
        LP_min_E_f=rminlp[1],IP_min_E_f=rminip[1],
        LP_min_E_decision=RD@rminlp[0],IP_min_E_decision=RD@rminip[0])
    zone_gaps=[]
    for zone in sorted(boxes.zone.unique()):
        zm=Model([p for p in patterns if p['zone']==zone],
            {k:v for k,v in demands.items() if k.startswith(zone+':')},logs,zone)
        low=zm.solve(zm.C[1],lp=True,tag='energy_LP')[2]
        opt=zm.solve(zm.C[1],tag='energy_IP')[2]
        zone_gaps.append(dict(zone=zone,E_LP=low,E_IP=opt,gap_kWh=opt-low))
    bounds, fractionals = [], []
    for j, name in enumerate(['N','E','T']):
        lp = model.solve(model.C[j]/[1,1,1000][j], lp=True, tag='bound_'+name)
        ip = model.solve(model.C[j]/[1,1,1000][j], tag='integer_'+name)
        low, opt = lp[1][j], ip[1][j]
        bounds.append(dict(objective=name, LP_lower=low, integer_optimum=opt,
            final_value=final_f[j], integrality_gap=opt-low,
            integrality_gap_pct=100*(opt-low)/opt,
            final_gap=final_f[j]-low, final_gap_pct=100*(final_f[j]-low)/final_f[j],
            final_reaches_LP=bool(abs(final_f[j]-low)<1e-6)))
        for p, value in zip(patterns,lp[0]):
            if value > 1e-8 and abs(value-round(value))>1e-7:
                fractionals.append(dict(objective=name,pattern=p['pattern'],zone=p['zone'],
                    vehicle=p['vehicle'], multiplicity=value, counts=str(p['counts'])))
    conditional_lp = model.solve(model.C[1], caps=[(model.C[0],final_f[0]),
        (model.C[2],final_f[2])], lp=True, tag='energy_at_final_caps')
    # Relax the SAME minimax epigraph, retaining integer preference baselines.
    ideal = front[['N','E_kWh','T_s']].min().to_numpy(float)
    scale = front[['N','E_kWh','T_s']].max().to_numpy(float)-ideal
    weights = preference_vertices()
    optima = np.array([model.weighted(w,scale,tag='regret_baseline')[2] for w in weights])
    coef = weights/scale @ model.C
    regret_lp = linprog(np.r_[np.zeros(len(patterns)),1.],
        A_ub=np.c_[coef,-np.ones(len(weights))],b_ub=optima,
        A_eq=hstack([model.A,csc_matrix((len(model.b),1))]),b_eq=model.b,
        bounds=list(zip(np.zeros(len(patterns)),model.ub))+[(0,None)], method='highs')
    assert regret_lp.success and abs(regret_lp.fun)<1e-7
    final_regret = float(np.max(weights @ (final_f/scale)-optima))
    assert abs(final_regret)<1e-6
    # Recheck every actual epsilon region, preserving infeasibility evidence.
    search = pd.read_csv(WORK/'子问题二'/'自适应epsilon搜索日志.csv')
    checks=[]
    for r in search.to_dict('records'):
        caps=[(model.C[0],r['N_cap'])]
        if pd.notna(r['T_cap_s']): caps.append((model.C[2],r['T_cap_s']))
        lp=model.solve(model.C[1],caps=caps,lp=True,tag=f"region{r['region']}_LP")
        ip=model.lex([1,0,2],caps=caps,tag=f"region{r['region']}_IP")
        assert lp is not None
        assert (ip is None)==(r['status']=='整数不可行')
        if ip is not None: assert np.allclose(ip[1],[r['N'],r['E_kWh'],r['T_s']],atol=1e-5)
        checks.append(dict(region=r['region'],LP_feasible=True,IP_feasible=ip is not None,
            LP_E=lp[1][1],f=None if ip is None else ip[1]))
    result=dict(domain='463 pruned count patterns; bounded multiplicity relaxation',
        rho=.2,eta=.72,global_patterns=len(patterns),raw_patterns=len(raw),
        local_zone='S008',local_patterns=len(local.patterns),fixed_objectives=fixed,
        local_integer_solutions=len(X), decision_points=decision_unique,
        decision_IP_hull=decision_unique[ConvexHull(decision_unique).vertices],
        decision_LP=decision_lp,decision_certificate=decision_certificate,
        objective_LP=objective_lp+fixed[[1,2]],
        objective_IP_hull=objective_unique[ConvexHull(objective_unique).vertices]+fixed[[1,2]],
        slice_objectives=global_f,objective_certificate=objective_certificate,
        pareto=front.to_dict('records'),bounds=bounds,
        conditional_energy_LP=conditional_lp[1][1],regret_LP=regret_lp.fun,
        final_regret=final_regret,epsilon_checks=checks,manifest=manifest,
        relaxation=relaxation,zone_energy_gaps=zone_gaps)
    save_json(OUT/'mechanism_data.json',result)
    csv(OUT/'全局下界核验.csv',bounds)
    csv(OUT/'各服务区能耗整数间隙.csv',zone_gaps)
    csv(OUT/'松弛分数解示例.csv',fractionals)
    csv(OUT/'投影与核验求解日志.csv',logs)
    csv(OUT/'S008条件整数可行方案.csv',[dict(index=k+1,N=f[0],E_kWh=f[1],T_s=f[2],
        B_sorties=decision_points[k,0],C_sorties=decision_points[k,1],
        patterns=';'.join(f"{p['pattern']}:{x}" for p,x in zip(local.patterns,X[k]) if x))
        for k,f in enumerate(global_f)])
    csv(OUT/'S003局部整数可行方案.csv',[dict(index=k+1,N=f[0],E_kWh=f[1],T_s=f[2],
        B_sorties=float(RD[0]@RX[k]),C_sorties=float(RD[1]@RX[k]),
        patterns=';'.join(f"{p['pattern']}:{x}" for p,x in zip(relax_model.patterns,RX[k]) if x))
        for k,f in enumerate(RX@relax_model.C.T)])
    print(json.dumps({k:result[k] for k in ['local_integer_solutions','bounds',
        'decision_certificate','objective_certificate','conditional_energy_LP','regret_LP']},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
