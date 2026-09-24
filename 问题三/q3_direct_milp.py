"""Direct joint MILP on a frozen, explicitly bounded Q3 candidate library.

This is independent of q3_milp.solve_joint.  Transport columns are never fixed
to a preliminary set-cover solution.  Missing transport disjunctions and route
communication blocks are *outer relaxations*: after every incumbent they are
added to the same all-column problem.  Only a fully checked incumbent can be
exported as a candidate plan.  This proves nothing about positions/routes not
in the frozen library, the 30,000 s horizon, or relay slots outside the model.
"""
from __future__ import annotations

import copy
import itertools
import math
import time
import warnings

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

UAV = {"A": ["U01", "U02", "U03", "U04"], "B": ["U05", "U06"], "C": ["U07", "U08"]}
BAT = {g: [f"{g}-BAT-{i:02d}" for i in range(1, n + 1)] for g, n in [("A", 6), ("B", 4), ("C", 4)]}
TOL = 2e-4


class DirectModel:
    def __init__(self):
        self.names, self.lo, self.hi, self.integer = [], [], [], []
        self.rows, self.lower, self.upper = [], [], []

    def var(self, name, lo=0.0, hi=math.inf, integer=False):
        k = len(self.names)
        self.names.append(name)
        self.lo.append(float(lo)); self.hi.append(float(hi))
        self.integer.append(int(integer))
        return k

    def add(self, coefficients, lo=-math.inf, hi=math.inf):
        self.rows.append({k: float(v) for k, v in coefficients.items() if abs(v) > 1e-14})
        self.lower.append(float(lo)); self.upper.append(float(hi))

    def eq(self, coefficients, value=0.0):
        self.add(coefficients, value, value)

    def matrix(self):
        rr, cc, vv = [], [], []
        for i, row in enumerate(self.rows):
            for j, value in row.items():
                rr.append(i); cc.append(j); vv.append(value)
        return coo_matrix((vv, (rr, cc)), shape=(len(self.rows), len(self.names))).tocsc()

    def run(self, objective, seconds, display=False):
        cost = np.zeros(len(self.names))
        for k, value in objective.items():
            cost[k] = value
        matrix = self.matrix()
        # Every HiGHS invocation in this entry point uses one thread.  Mixing
        # default global thread initialization and explicit threads is unsafe.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Unrecognized options detected")
            result = milp(cost, integrality=np.asarray(self.integer),
                          bounds=Bounds(self.lo, self.hi),
                          constraints=LinearConstraint(matrix, self.lower, self.upper),
                          options={"time_limit": float(seconds), "mip_rel_gap": 0.0,
                                   "threads": 1, "disp": bool(display),
                                   "mip_feasibility_tolerance": 1e-8,
                                   "primal_feasibility_tolerance": 1e-8})
        violation = None
        if result.x is not None:
            value = matrix @ result.x
            violation = max(float(np.max(np.maximum(np.asarray(self.lower) - value, 0))),
                            float(np.max(np.maximum(value - np.asarray(self.upper), 0))),
                            float(np.max(np.maximum(np.asarray(self.lo) - result.x, 0))),
                            float(np.max(np.maximum(result.x - np.asarray(self.hi), 0))))
            integer_values = result.x[np.asarray(self.integer, dtype=bool)]
            if len(integer_values):
                violation = max(violation, float(np.max(abs(integer_values - np.rint(integer_values)))))
        return result, violation


def transport_conflicts(plan):
    """Exact pairwise check of body and battery half-open occupancy intervals."""
    result = []
    for a, b in itertools.combinations(plan["routes"], 2):
        if a["vehicle"] != b["vehicle"]:
            continue
        for key, finish_key in [("uav", "finish"), ("battery_id", "recharge")]:
            if a[key] != b[key]:
                continue
            overlap = min(a[finish_key], b[finish_key]) - max(a["start"], b["start"])
            if overlap > TOL:
                result.append({"pair": sorted([a["route_id"], b["route_id"]]),
                               "resource": key, "id": a[key], "overlap_s": overlap})
    return result


def complete_communication(plan, loaded_ids):
    """Check exact selected atomic-block assignments after the MILP solve.

    The geometric certificates themselves are produced by q3_common.profile
    and still require the independent DEM verifier before publication.
    """
    relays = {r["slot"]: r for r in plan["relays"]}
    failures = []
    for route in plan["routes"]:
        if route["needs"] and route["route_id"] not in loaded_ids:
            failures.append({"route": route["route_id"], "reason": "block_not_loaded"})
            continue
        if len(route["links"]) != len(route["needs"]):
            failures.append({"route": route["route_id"], "reason": "link_count"})
            continue
        for need, link in zip(route["needs"], route["links"]):
            relay = relays.get(link["relay_slot"])
            if relay is None or not (int(need["mask"]) & (1 << relay["qid"])):
                failures.append({"route": route["route_id"], "reason": "inactive_or_wrong_relay"})
            elif relay["alpha"] > route["start"] + need["t0"] + TOL or relay["beta"] < route["start"] + need["t1"] - TOL:
                failures.append({"route": route["route_id"], "reason": "time_not_covered"})
    return failures


def solve_relaxation(ctx, routes, *, loaded_ids, pair_keys, mode="C", caps=None,
                     seconds=30.0, slots_per_uav=3, horizon=30000.0, display=False):
    """Solve all transport choices jointly; return a labelled relaxation only.

    pair_keys is a set of sorted route-ID pairs whose full body/battery
    disjunctions have been materialized.  loaded_ids identifies complete
    atomic communication blocks.  Neither is a route-selection restriction.
    """
    started = time.perf_counter()
    if mode not in {"N", "E", "C", "L"}:
        raise ValueError("mode must be N, E, C, or L")
    ids = [r["route_id"] for r in routes]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate route instance IDs")
    loaded_ids = set(loaded_ids)
    pair_keys = {tuple(sorted(k)) for k in pair_keys}
    H = float(horizon)
    M = 2 * H + max(r["duration"] + r["charge_s"] for r in routes) + 1000
    J, positions, component_count = 2 * slots_per_uav, list(range(len(ctx.qs))), 6
    if not positions or slots_per_uav < 1:
        raise ValueError("Empty relay domain")
    m = DirectModel()
    x, start, body, battery, lateness = [], [], {}, {}, {}
    for i, route in enumerate(routes):
        latest = min(H - route["duration"], route["latest_start"])
        x.append(m.var(("x", i), 0, int(latest >= 0), True))
        start.append(m.var(("start", i), 0, max(0.0, latest)))
        m.add({start[i]: 1, x[i]: -max(0.0, latest)}, hi=0)
        for resource in UAV[route["vehicle"]]:
            body[i, resource] = m.var(("uav", i, resource), 0, 1, True)
        for resource in BAT[route["vehicle"]]:
            battery[i, resource] = m.var(("battery", i, resource), 0, 1, True)
        m.eq({**{body[i, d]: 1 for d in UAV[route["vehicle"]]}, x[i]: -1})
        m.eq({**{battery[i, d]: 1 for d in BAT[route["vehicle"]]}, x[i]: -1})
    # Identical copies are interchangeable.  Prefix selection and ascending
    # start order remove only their labels, never a physical schedule.
    copies = {}
    for i, route in enumerate(routes):
        copies.setdefault(route["pattern_id"], []).append(i)
    for indices in copies.values():
        for a, b in zip(indices, indices[1:]):
            m.add({x[b]: 1, x[a]: -1}, hi=0)
            m.add({start[a]: 1, start[b]: -1, x[b]: H}, hi=H)

    # Exchangeability is checked when the library is built.  Every first-batch
    # category in the supplied data has one flagged box.  In particular use
    # group["first"], not pandas DataFrame.first (a method).
    for category, group in ctx.boxes.groupby("category"):
        indices = [i for i, r in enumerate(routes) if r["counts"].get(category, 0)]
        if not indices:
            return None, {"reason": "uncovered_category", "category": category}
        m.eq({x[i]: routes[i]["counts"][category] for i in indices}, len(group))
        first_boxes = group[group["first"] == "是"]
        if len(first_boxes) > 1:
            raise ValueError("Multiple first boxes in one category need a generalized count encoding")
        if len(first_boxes):
            selectors = []
            deadline = float(first_boxes.iloc[0]["deadline"])
            for i in indices:
                flag = m.var(("first", category, i), 0, 1, True)
                selectors.append(flag)
                m.add({flag: 1, x[i]: -1}, hi=0)
                m.add({start[i]: 1, flag: M}, hi=M + deadline - routes[i]["offsets"][category])
            m.eq({v: 1 for v in selectors}, 1)

    by_id = {rid: i for i, rid in enumerate(ids)}
    for ra, rb in sorted(pair_keys):
        i, j = by_id[ra], by_id[rb]
        if routes[i]["vehicle"] != routes[j]["vehicle"]:
            continue
        order = m.var(("order", i, j), 0, 1, True)
        for kind, resources, assignments in [("body", UAV[routes[i]["vehicle"]], body),
                                               ("battery", BAT[routes[i]["vehicle"]], battery)]:
            ti = routes[i]["duration"] + (routes[i]["charge_s"] if kind == "battery" else 0)
            tj = routes[j]["duration"] + (routes[j]["charge_s"] if kind == "battery" else 0)
            for resource in resources:
                m.add({start[i]: 1, start[j]: -1, assignments[i, resource]: M,
                       assignments[j, resource]: M, order: M}, hi=3 * M - ti)
                m.add({start[j]: 1, start[i]: -1, assignments[i, resource]: M,
                       assignments[j, resource]: M, order: -M}, hi=2 * M - tj)

    C = m.var("completion", 0, H)
    N, E, L = {v: 1 for v in x}, {x[i]: r["energy"] for i, r in enumerate(routes)}, {}
    denominator = float(ctx.boxes.loc[~ctx.boxes.hard, "priority"].sum())
    for g, fleet in UAV.items():
        m.add({**{x[i]: r["duration"] for i, r in enumerate(routes) if r["vehicle"] == g}, C: -len(fleet)}, hi=0)
    for i, route in enumerate(routes):
        m.add({start[i]: 1, x[i]: route["duration"], C: -1}, hi=0)
        for category, number in route["counts"].items():
            group = ctx.boxes[ctx.boxes.category == category]
            row = group.iloc[0]
            if row.kind == "医疗物资":
                # Explicit medical deadlines do not rely solely on a cached
                # latest_start coefficient.
                m.add({start[i]: 1, x[i]: M}, hi=M + float(row.expected) - route["offsets"][category])
                continue
            # A flagged nonmedical box has deadline <= expected, hence zero
            # lateness in its selected first-batch delivery.  Aggregating all
            # category counts gives exactly the non-hard box numerator.
            if len(group[group.hard]) and (group.loc[group.hard, "deadline"] > group.loc[group.hard, "expected"]).any():
                raise ValueError("Hard box may be late relative to expected; require explicit per-box lateness")
            variable = m.var(("late", i, category), 0, H)
            lateness[i, category] = variable
            m.add({start[i]: 1, x[i]: route["offsets"][category], variable: -1}, hi=float(row.expected))
            m.add({variable: 1, x[i]: -H}, hi=0)
            if denominator:
                L[variable] = number * float(row.priority) / denominator

    on, rs, alpha, beta, finish, duration, energy, charge = [], [], [], [], [], [], [], []
    position, component = {}, {}
    for j in range(J):
        on.append(m.var(("relay_on", j), 0, 1, True)); N[on[j]] = 1
        rs.append(m.var(("relay_start", j), 0, H))
        alpha.append(m.var(("service_start", j), 0, H))
        beta.append(m.var(("service_end", j), 0, H))
        finish.append(m.var(("relay_finish", j), 0, H))
        duration.append(m.var(("relay_duration", j), 0, 9000))
        energy.append(m.var(("relay_energy", j), 0, 2.56)); E[energy[j]] = 1
        charge.append(m.var(("relay_charge", j), 0, 1540))
        for variable, upper in [(rs[j], H), (finish[j], H), (energy[j], 2.56), (charge[j], 1540)]:
            m.add({variable: 1, on[j]: -upper}, hi=0)
        for q in positions:
            position[j, q] = m.var(("position", j, q), 0, 1, True)
        m.eq({**{position[j, q]: 1 for q in positions}, on[j]: -1})
        m.eq({alpha[j]: 1, rs[j]: -1,
              **{position[j, q]: -(180 + ctx.qs[q]["out_s"] + 30) for q in positions}})
        m.eq({beta[j]: 1, alpha[j]: -1, duration[j]: -1})
        m.eq({finish[j]: 1, beta[j]: -1, **{position[j, q]: -ctx.qs[q]["back_s"] for q in positions}})
        m.eq({energy[j]: 1, duration[j]: -1.1 / 3600,
              **{position[j, q]: -ctx.qs[q]["e0"] for q in positions}})
        m.add({duration[j]: 1, **{position[j, q]: -ctx.qs[q]["dmax"] for q in positions}}, hi=0)
        m.add({finish[j]: 1, C: -1}, hi=0)
        branch = m.var(("charge_branch", j), 0, 1, True)
        m.add({branch: 1, on[j]: -1}, hi=0)
        m.add({energy[j]: 1, on[j]: -.32, branch: -2.24}, hi=0)
        m.add({energy[j]: 1, branch: -.32}, lo=0)
        for sign in (1, -1):
            m.add({charge[j]: sign, energy[j]: -1968.75 * sign, branch: -6000}, hi=0)
            m.add({charge[j]: sign, energy[j]: -406.25 * sign,
                   on[j]: -500 * sign - 6000, branch: 6000}, hi=0)
        for p in range(component_count):
            component[j, p] = m.var(("component", j, p), 0, 1, True)
        m.eq({**{component[j, p]: 1 for p in range(component_count)}, on[j]: -1})
        if j % slots_per_uav:
            m.add({on[j]: 1, on[j - 1]: -1}, hi=0)
            m.add({finish[j - 1]: 1, rs[j]: -1, on[j]: M}, hi=M - 300)
    # Relay bodies/components are interchangeable; these remove label symmetry.
    m.add({on[slots_per_uav]: 1, on[0]: -1}, hi=0)
    m.eq({component[0, 0]: 1, on[0]: -1})
    for j, k in itertools.combinations(range(J), 2):
        order = m.var(("component_order", j, k), 0, 1, True)
        if j // slots_per_uav == k // slots_per_uav:
            m.lo[order] = m.hi[order] = 1
        for p in range(component_count):
            m.add({finish[j]: 1, charge[j]: 1, rs[k]: -1, component[j, p]: M,
                   component[k, p]: M, order: M}, hi=3 * M)
            m.add({finish[k]: 1, charge[k]: 1, rs[j]: -1, component[j, p]: M,
                   component[k, p]: M, order: -M}, hi=2 * M)

    cover, support = {}, {j: [] for j in range(J)}
    unloaded = [x[i] for i, route in enumerate(routes) if route["route_id"] not in loaded_ids and route["needs"]]
    for i, route in enumerate(routes):
        if route["route_id"] not in loaded_ids:
            continue
        for h, need in enumerate(route["needs"]):
            allowed = [q for q in positions if int(need["mask"]) & (1 << q)]
            if not allowed:
                m.hi[x[i]] = 0
                continue
            selectors = []
            for j in range(J):
                variable = m.var(("cover", i, h, j), 0, 1, True)
                cover[i, h, j] = variable; selectors.append(variable); support[j].append(variable)
                m.add({variable: 1, **{position[j, q]: -1 for q in allowed}}, hi=0)
                m.add({alpha[j]: 1, start[i]: -1, variable: M}, hi=M + need["t0"])
                m.add({start[i]: 1, beta[j]: -1, variable: M}, hi=M - need["t1"])
            m.eq({**{v: 1 for v in selectors}, x[i]: -1})
    for j in range(J):
        # An unloaded selected route may support a relay in the relaxation.
        # Its exact support is supplied once its block is materialized.
        m.add({on[j]: 1, **{v: -1 for v in support[j] + unloaded}}, hi=0)
    objectives = {"N": N, "E": E, "C": {C: 1}, "L": L}
    for key, value in (caps or {}).items():
        if key not in objectives:
            raise ValueError(f"Unknown epsilon cap {key}")
        if value is not None:
            m.add(objectives[key], hi=float(value))
    building_s = time.perf_counter() - started
    result, violation = m.run(objectives[mode], max(.01, seconds - building_s), display)
    meta = {"status": int(result.status), "message": str(result.message),
            "incumbent_available": result.x is not None, "objective_mode": mode,
            "solver_objective": float(result.fun) if result.fun is not None else None,
            "dual_bound": getattr(result, "mip_dual_bound", None),
            "mip_gap": getattr(result, "mip_gap", None), "nodes": getattr(result, "mip_node_count", None),
            "max_constraint_violation": violation, "variables": len(m.names), "constraints": len(m.rows),
            "route_instances": len(routes), "loaded_route_blocks": len(loaded_ids),
            "loaded_transport_pairs": len(pair_keys), "building_s": building_s,
            "elapsed_s": time.perf_counter() - started, "mip_rel_gap_requested": 0.0, "threads": 1}
    if result.x is None or violation is None or violation > TOL:
        if result.x is not None:
            meta["rejected"] = "numerical_constraint_or_integrality_violation"
        return None, meta
    value = result.x
    transport, relays = [], []
    for i, route in enumerate(routes):
        if value[x[i]] < .5:
            continue
        s = max(0.0, float(value[start[i]])); f = s + route["duration"]
        links = []
        if route["route_id"] in loaded_ids:
            for h, need in enumerate(route["needs"]):
                possible = [j for j in range(J) if (i, h, j) in cover and value[cover[i, h, j]] > .5]
                if len(possible) != 1:
                    return None, dict(meta, rejected="missing_or_multiple_communication_assignment")
                links.append(dict(need, relay_slot=possible[0]))
        transport.append(dict(copy.deepcopy(route), start=s, takeoff=s + route["prep_s"], finish=f,
                              recharge=f + route["charge_s"],
                              uav=max(UAV[route["vehicle"]], key=lambda k: value[body[i, k]]),
                              battery_id=max(BAT[route["vehicle"]], key=lambda k: value[battery[i, k]]), links=links))
    for j in range(J):
        if value[on[j]] < .5:
            continue
        q = max(positions, key=lambda k: value[position[j, k]])
        p = max(range(component_count), key=lambda k: value[component[j, k]])
        qq = ctx.qs[q]; s = max(0.0, float(value[rs[j]])); d = max(0.0, float(value[duration[j]]))
        a = s + 180 + qq["out_s"] + 30; b = a + d; f = b + qq["back_s"]
        e = qq["e0"] + 1.1 * d / 3600; soc = 1 - e / 3.2
        ch = 1800 * (.65 * (.9 - soc) / .9 + .35) if soc < .9 else 1800 * .35 * (1 - soc) / .1
        relays.append(dict(slot=j, relay_id=f"Q3-DIRECT-R{j + 1:03d}", uav=f"R{j // slots_per_uav + 1:02d}",
                           component=f"R-EC-{p + 1:02d}", qid=q, position=copy.deepcopy(qq), start=s,
                           takeoff=s + 180, arrival=s + 180 + qq["out_s"], alpha=a, beta=b, finish=f,
                           duration=d, energy=e, soc=soc, charge_s=ch, recharge=f + ch, body_ready=f + 300))
    delivery_slots = {}
    for route in transport:
        for category, number in route["counts"].items():
            delivery_slots.setdefault(category, []).extend([(route, route["start"] + route["offsets"][category])] * number)
    boxes = []
    for category, group in ctx.boxes.groupby("category"):
        named = group.sort_values(["hard", "deadline", "box"], ascending=[False, True, True]).to_dict("records")
        slots = sorted(delivery_slots.get(category, []), key=lambda item: item[1])
        if len(named) != len(slots):
            return None, dict(meta, rejected="box_coverage")
        for box, (route, delivery) in zip(named, slots):
            boxes.append(dict(box, route_id=route["route_id"], delivery=delivery,
                              uav=route["uav"], battery_id=route["battery_id"]))
    if any(b["hard"] and b["delivery"] > b["deadline"] + TOL for b in boxes):
        return None, dict(meta, rejected="hard_deadline")
    ET, ER = sum(r["energy"] for r in transport), sum(r["energy"] for r in relays)
    actualC = max([r["finish"] for r in transport] + [r["finish"] for r in relays])
    actualL = sum(b["priority"] * max(0.0, b["delivery"] - b["expected"]) for b in boxes if not b["hard"]) / denominator
    plan = {"routes": sorted(transport, key=lambda r: r["start"]), "relays": relays, "boxes": boxes,
            "NT": len(transport), "NR": len(relays), "ET": ET, "ER": ER,
            "objective": [len(transport) + len(relays), ET + ER, actualC, actualL],
            "status": "outer_relaxation_incumbent_not_a_feasible_Q3_plan", "meta": meta}
    return plan, meta
