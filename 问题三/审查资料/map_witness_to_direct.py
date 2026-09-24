"""Map the external audit witness into the frozen direct MILP; no optimization.

Only this audit's JSON outputs are written. Production code, solver results,
candidate caches and official submissions are unchanged.
"""
from __future__ import annotations
import os
os.environ["MKL_THREADING_LAYER"] = "SEQUENTIAL"
for _key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_key] = "1"
import copy
import hashlib
import itertools
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
import numpy as np

HERE = Path(__file__).resolve().parent
Q3 = HERE.parent
OUT = HERE / "本轮复核"
sys.path.insert(0, str(Q3))
from q3_common import Context, load
from solve_q3_global import expand_instances, route_signature
import q3_direct_milp as direct
from verify_q3 import Verifier
from audit_source_and_result import audit

WITNESS = OUT / "支配见证方案.json"
SOURCE = Q3 / "子问题一/累计候选路线.json"
RUN = Q3 / "全局直接求解/20260924_直接联合120秒"
HORIZON = 30000.0
SLOTS_PER_UAV = 3
TOL = 2e-4


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(suffix, value):
    def conv(v):
        if isinstance(v, (np.integer, np.floating)):
            return v.item()
        if isinstance(v, np.bool_):
            return bool(v)
        raise TypeError(type(v).__name__)
    (OUT / ("直接模型基准映射" + suffix + ".json")).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=conv, allow_nan=False), encoding="utf-8")


def map_plan(ctx, routes, witness):
    copies = defaultdict(list)
    for route in routes:
        copies[route_signature(route)].append(route)
    groups = defaultdict(list)
    for route in witness["routes"]:
        groups[route_signature(route)].append(route)
    mapped = copy.deepcopy(witness)
    chosen, mapping, link_records = [], {}, []
    relays = {int(r["slot"]): r for r in mapped["relays"]}
    for signature, old_group in groups.items():
        old_group.sort(key=lambda r: (r["start"], r["route_id"]))
        available = sorted(copies.get(signature, []), key=lambda r: r["instance_index"])
        if len(old_group) > len(available):
            raise ValueError("Witness pattern not sufficiently represented: " + repr(signature))
        for old, fresh in zip(old_group, available):
            record = copy.deepcopy(fresh)
            # The direct model itself intersects latest_start with H-duration.
            # Serialize that effective finite bound, not an Infinity token.
            record["latest_start"] = min(HORIZON - record["duration"], record["latest_start"])
            for key in ("start", "takeoff", "finish", "recharge", "uav", "battery_id"):
                record[key] = old[key]
            for key in ("prep_s", "duration", "energy", "soc", "charge_s"):
                if abs(float(fresh[key]) - float(old[key])) > 2e-7:
                    raise ValueError(f"Physical coefficient changed: {old['route_id']} {key}")
            links = []
            for number, need in enumerate(fresh["needs"]):
                matches = []
                for old_number, link in enumerate(old["links"]):
                    relay = relays.get(int(link["relay_slot"]))
                    if (relay is not None and link["t0"] <= need["t0"] + 1e-7
                            and link["t1"] >= need["t1"] - 1e-7
                            and int(need["mask"]) & (1 << int(relay["qid"]))):
                        matches.append((old_number, relay["slot"]))
                if not matches:
                    raise ValueError(f"No old full-interval provider: {old['route_id']} atom {number}")
                old_number, slot = matches[0]
                links.append(dict(need, relay_slot=slot))
                link_records.append(dict(old_route_id=old["route_id"], route_id=fresh["route_id"],
                                         atomic_need=number, old_link=old_number, relay_slot=slot))
            record["links"] = links
            record["external_witness_route_id"] = old["route_id"]
            mapping[old["route_id"]] = fresh["route_id"]
            chosen.append(record)
    mapped["routes"] = sorted(chosen, key=lambda r: (r["start"], r["route_id"]))
    for box in mapped["boxes"]:
        box["route_id"] = mapping[box["route_id"]]
    mapped["source"] = "external_existing_audit_witness_mapped_without_optimization"
    mapped["status"] = "mapped_external_baseline_pending_verification"
    return mapped, mapping, link_records


def model_vector_check(ctx, all_routes, plan):
    """Build direct-model rows, substitute this witness, call no solver.

    Materialize every selected route's communication and every selected
    same-type resource pair. Omitted rows involve unselected routes; those
    have x=start=assignments=cover=0 and the documented M deactivates them.
    """
    by_id = {r["route_id"]: r for r in plan["routes"]}
    by_slot = {int(r["slot"]): r for r in plan["relays"]}
    loaded = set(by_id)
    pairs = {tuple(sorted((a["route_id"], b["route_id"])))
             for a, b in itertools.combinations(plan["routes"], 2)
             if a["vehicle"] == b["vehicle"]}
    first_route = {}
    for category, group in ctx.boxes.groupby("category"):
        first = group[group["first"] == "是"]
        if len(first):
            eligible = [r for r in plan["routes"] if r["counts"].get(category)
                        and r["start"] + r["offsets"][category] <= float(first.iloc[0]["deadline"]) + TOL]
            if not eligible:
                raise ValueError("First-batch category has no timely selected route: " + category)
            first_route[category] = min(eligible, key=lambda r: (r["start"] + r["offsets"][category], r["route_id"]))["route_id"]
    captured = {}
    original_run = direct.DirectModel.run

    def probe(model, objective, seconds, display=False):
        values = np.zeros(len(model.names))
        for index, name in enumerate(model.names):
            if name == "completion":
                values[index] = plan["objective"][2]
                continue
            tag = name[0]
            if tag in ("x", "start", "uav", "battery", "late"):
                route = by_id.get(all_routes[name[1]]["route_id"])
                if route is None:
                    continue
                if tag == "x":
                    values[index] = 1
                elif tag == "start":
                    values[index] = route["start"]
                elif tag == "uav":
                    values[index] = route["uav"] == name[2]
                elif tag == "battery":
                    values[index] = route["battery_id"] == name[2]
                elif tag == "late":
                    category = name[2]
                    expected = float(ctx.catinfo[category]["expected"])
                    values[index] = max(0.0, route["start"] + route["offsets"][category] - expected)
            elif tag == "first":
                values[index] = all_routes[name[2]]["route_id"] == first_route.get(name[1])
            elif tag == "order":
                a, b = (by_id.get(all_routes[i]["route_id"]) for i in name[1:3])
                values[index] = bool(a and b and a["start"] <= b["start"])
            elif tag == "component_order":
                j, k = name[1:3]
                if j // SLOTS_PER_UAV == k // SLOTS_PER_UAV:
                    values[index] = 1
                elif j in by_slot and k in by_slot:
                    values[index] = by_slot[j]["start"] <= by_slot[k]["start"]
            elif tag == "cover":
                route = by_id.get(all_routes[name[1]]["route_id"])
                if route is not None:
                    values[index] = route["links"][name[2]]["relay_slot"] == name[3]
            else:
                relay = by_slot.get(name[1])
                if relay is None:
                    continue
                fields = {"relay_start": "start", "service_start": "alpha", "service_end": "beta",
                          "relay_finish": "finish", "relay_duration": "duration", "relay_energy": "energy",
                          "relay_charge": "charge_s"}
                if tag == "relay_on":
                    values[index] = 1
                elif tag in fields:
                    values[index] = relay[fields[tag]]
                elif tag == "position":
                    values[index] = relay["qid"] == name[2]
                elif tag == "component":
                    values[index] = relay["component"] == f"R-EC-{name[2] + 1:02d}"
                elif tag == "charge_branch":
                    values[index] = relay["energy"] > .32
                else:
                    raise ValueError("Unhandled direct variable: " + repr(name))
        matrix = model.matrix()
        residual = matrix @ values
        row_violation = np.maximum(np.maximum(np.array(model.lower) - residual, 0),
                                   np.maximum(residual - np.array(model.upper), 0))
        bounds = max(float(np.max(np.maximum(np.array(model.lo) - values, 0))),
                     float(np.max(np.maximum(values - np.array(model.hi), 0))))
        ints = values[np.asarray(model.integer, dtype=bool)]
        integrality = float(np.max(abs(ints - np.rint(ints))))
        worst = max(float(np.max(row_violation)), bounds, integrality)
        captured.update(status="PASS" if worst <= TOL else "FAIL", variables=len(model.names),
                        materialized_constraints=len(model.rows), max_violation=worst,
                        row_max_violation=float(np.max(row_violation)),
                        bound_max_violation=bounds, integrality_max_violation=integrality,
                        failing_row_indices=np.flatnonzero(row_violation > TOL).tolist(),
                        selected_communication_blocks=len(loaded), selected_resource_pairs=len(pairs),
                        solver_called=False,
                        omitted_rows="Only unselected-route communication and resource disjunctions; set all their assignments to zero. Complete selected blocks and same-type selected pairs were checked.")
        # Return no incumbent intentionally: the production decoder is not
        # needed and this check must not look like a successful MILP solve.
        return SimpleNamespace(x=None, status=1, message="audit substitution only; solver not called",
                               fun=None, mip_dual_bound=None, mip_gap=None, mip_node_count=None), worst

    direct.DirectModel.run = probe
    try:
        direct.solve_relaxation(ctx, all_routes, loaded_ids=loaded, pair_keys=pairs,
                                mode="C", caps={}, slots_per_uav=SLOTS_PER_UAV, horizon=HORIZON, seconds=60)
    finally:
        direct.DirectModel.run = original_run
    return captured


def main():
    ctx = Context()
    ctx.qs = load(Q3 / "缓存/中继候选位置.json")
    geometry = load(Q3 / "缓存/区间几何.json")
    if geometry["candidate_count"] != len(ctx.qs):
        raise ValueError("Candidate count does not match atomic geometry")
    ctx.arc_cache = {tuple(map(int, key.split(","))): value for key, value in geometry["arcs"].items()}
    ctx.node_cache = {int(key): value for key, value in geometry["nodes"].items()}
    all_routes, library = expand_instances(ctx, load(SOURCE))
    manifest = load(RUN / "冻结候选库清单.json")
    fingerprint_checks = {
        "source_sha256": sha(SOURCE) == manifest["source_sha256"],
        "relay_sha256": hashlib.sha256(json.dumps(ctx.qs, sort_keys=True).encode()).hexdigest() == manifest["relay_candidate_sha256"],
        "records_equal": library["records"] == manifest["records"],
        "1290_patterns": library["patterns"] == manifest["patterns"] == 1290,
        "1445_instances": library["instances"] == manifest["instances"] == 1445,
        "no_discarded": not library["discarded"] and not manifest["discarded"],
    }
    if not all(fingerprint_checks.values()):
        raise ValueError("Frozen library mismatch: " + repr(fingerprint_checks))
    run = load(RUN / "直接联合MILP结果.json")
    if run["scalar_objective"] != "C" or run["epsilon_caps"] or run["scope"]["horizon_s"] != HORIZON:
        raise ValueError("Lower bound objective, caps, or horizon mismatch")
    plan, mapping, links = map_plan(ctx, all_routes, load(WITNESS))
    conflicts = direct.transport_conflicts(plan)
    communication = direct.complete_communication(plan, {r["route_id"] for r in plan["routes"]})
    matrix_check = model_vector_check(ctx, all_routes, plan)
    raw = audit(plan)
    verifier = Verifier(plan)
    verifier.verify_routes()
    verifier.verify_boxes()
    verifier.verify_relays()
    physical = verifier.finish()
    physical["plan"] = str(OUT / "直接模型基准映射方案.json")
    named_boxes = {b["box"] for b in plan["boxes"]}
    all_named_boxes = set(ctx.boxes["box"])
    scope_checks = {
        "80_original_boxes": len(plan["boxes"]) == 80 and named_boxes == all_named_boxes,
        "all_horizon": all(0 <= r["start"] <= r["finish"] <= HORIZON for r in plan["routes"] + plan["relays"]),
        "body_slots_agree": all(r["uav"] == f"R{r['slot'] // SLOTS_PER_UAV + 1:02d}" for r in plan["relays"]),
        "relay_prefix": all(sorted(r["slot"] % SLOTS_PER_UAV for r in plan["relays"] if r["slot"] // SLOTS_PER_UAV == u)
                            == list(range(sum(r["slot"] // SLOTS_PER_UAV == u for r in plan["relays"]))) for u in (0, 1)),
        "slot_zero_component_symmetry": next(r for r in plan["relays"] if r["slot"] == 0)["component"] == "R-EC-01",
        "every_relay_supports_atom": all(any(link["relay_slot"] == r["slot"] for route in plan["routes"] for link in route["links"]) for r in plan["relays"]),
    }
    passed = (all(scope_checks.values()) and not conflicts and not communication
              and matrix_check["status"] == "PASS" and raw["status"] == "PASS" and physical["passed"])
    ub = physical["objective_recomputed"][2] if passed else None
    lb = run["finite_model_valid_lower_bound"]
    result = {
        "status": "PASS" if passed else "FAIL",
        "purpose": "External existing witness mapped into exactly the bounded direct candidate model; this is NOT a solution discovered by the new solver.",
        "solver_called": False,
        "source_witness": str(WITNESS), "source_witness_sha256": sha(WITNESS),
        "direct_run_result": str(RUN / "直接联合MILP结果.json"),
        "fingerprint_checks": fingerprint_checks,
        "scope": {"patterns": 1290, "instances": 1445, "positions": len(ctx.qs),
                  "slots_per_uav": SLOTS_PER_UAV, "components": 6, "horizon_s": HORIZON,
                  "mode": "C", "epsilon_caps": {}, "atomic_interval_assignment": True,
                  "original_full_space_global_optimality": False},
        "scope_checks": scope_checks,
        "mapped_routes": len(plan["routes"]), "mapped_atomic_needs": len(links),
        "route_id_mapping": mapping,
        "transport_conflicts": conflicts, "communication_failures": communication,
        "matrix_substitution": matrix_check,
        "raw_workbook_audit": raw["status"], "DEM_verification": physical["status"],
        "four_objectives": physical["objective_recomputed"],
        "finite_model_C_lower_bound_s": lb,
        "external_known_feasible_C_upper_bound_s": ub,
        "relative_gap_UB_denominator": (ub - lb) / ub if passed else None,
        "gap_interpretation": "Bound interval for the same C-only finite model, not the actual suboptimality or a multiobjective/regret guarantee.",
        "formal_results_overwritten": False,
    }
    if passed:
        plan["status"] = "verified_external_baseline_for_frozen_direct_C_model"
        write("方案", plan)
    write("_原始算术", raw)
    write("_完整DEM", physical)
    write("_原子指派", links)
    write("", result)
    print(json.dumps({k: result[k] for k in ("status", "mapped_routes", "mapped_atomic_needs",
                      "finite_model_C_lower_bound_s", "external_known_feasible_C_upper_bound_s",
                      "relative_gap_UB_denominator")}, ensure_ascii=False))
    if not passed:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        write("", {"status": "FAIL", "reason": type(error).__name__ + ": " + str(error),
                   "external_known_feasible_C_upper_bound_s": None,
                   "solver_called": False, "formal_results_overwritten": False})
        raise
