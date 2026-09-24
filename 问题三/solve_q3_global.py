"""Finite-library direct joint MILP; ALNS stays a separate comparison.

Every round keeps ALL route instances selectable and jointly decides routes,
starts, UAVs, batteries, relay locations, intervals and components. Missing
resource disjunctions and selected communication blocks are added to the
all-column model. A time limit without a fully feasible incumbent is a limit,
never a successful solve. Official result tables are never overwritten.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import itertools
import json
import math
import time
from datetime import datetime
from pathlib import Path
from q3_common import Context, OUT, load, make_route, prepare_candidates, prepare_geometry, profile, save
from q3_direct_milp import TOL, complete_communication, solve_relaxation, transport_conflicts


def route_signature(route):
    return (route["vehicle"], tuple((d["zone"], tuple(sorted((c, int(n)) for c, n in d["counts"].items() if n)))
                                    for d in route["deliveries"]))


def expand_instances(ctx, source_patterns):
    """Recompute/deduplicate patterns, then add every safe executable copy.

    Exact category cover implies multiplicity <= min floor(d_c/a_pc). Adding
    this many copies permits any use of each pattern, unlike a binary registry
    that allows a useful repeated grouping only once.
    """
    demand = ctx.boxes.groupby("category").size().to_dict()
    for category, group in ctx.boxes.groupby("category"):
        for field in ("zone", "kind", "mass", "volume", "expected", "priority"):
            if group[field].nunique(dropna=False) != 1:
                raise ValueError(f"Nonexchangeable category {category}: {field}")
        if len(group[group["first"] == "是"]) > 1:
            raise ValueError(f"Multiple first boxes need a count encoding: {category}")
    unique = {}
    for source in source_patterns:
        signature = route_signature(source)
        if signature not in unique:
            unique[signature] = {"source": source, "source_ids": []}
        unique[signature]["source_ids"].append(source.get("route_id"))
    routes, records, discarded = [], [], []
    ordered = sorted(unique.items(), key=lambda item: repr(item[0]))
    for number, (_, entry) in enumerate(ordered, 1):
        source = entry["source"]
        if len({d["zone"] for d in source["deliveries"]}) != len(source["deliveries"]):
            raise ValueError("Repeated-zone visits are outside this route representation")
        pattern_id = f"DP{number:06d}"
        regenerated = make_route(ctx, source["vehicle"], copy.deepcopy(source["deliveries"]), pattern_id)
        if regenerated is None:
            discarded.append({"source_ids": entry["source_ids"], "reason": "not_feasible_under_current_coefficients"})
            continue
        atomic = profile(ctx, regenerated, merge=False)
        if atomic is None:
            discarded.append({"source_ids": entry["source_ids"], "reason": "no_certified_atomic_coverage"})
            continue
        regenerated["needs"] = atomic["needs"]
        counts = regenerated["counts"]
        if not counts or any(c not in demand or n <= 0 or int(n) != n for c, n in counts.items()):
            raise ValueError(f"Invalid category count in {pattern_id}")
        multiplicity = min(int(demand[c] // n) for c, n in counts.items())
        if not multiplicity:
            discarded.append({"source_ids": entry["source_ids"], "reason": "category_count_exceeds_demand"})
            continue
        for k in range(multiplicity):
            route = copy.deepcopy(regenerated)
            route.update(pattern_id=pattern_id, route_id=f"{pattern_id}#I{k + 1:02d}", instance_index=k + 1)
            routes.append(route)
        records.append({"pattern_id": pattern_id, "source_ids": entry["source_ids"], "copies": multiplicity,
                        "vehicle": source["vehicle"], "counts": counts, "atomic_needs": len(atomic["needs"]),
                        "energy_recomputed": regenerated["energy"],
                        "energy_delta_from_source": regenerated["energy"] - float(source["energy"]),
                        "duration_delta_from_source": regenerated["duration"] - float(source["duration"])})
    if len({r["route_id"] for r in routes}) != len(routes):
        raise AssertionError("Nonunique route instances")
    return routes, {"input_patterns": len(source_patterns), "unique_patterns_before_regeneration": len(unique),
                    "patterns": len(records), "instances": len(routes), "records": records, "discarded": discarded}


def seed_blocks_from_reference(routes, reference):
    """Use reference only to seed valid constraints; never fix its route set."""
    by_signature = {}
    for route in routes:
        by_signature.setdefault(route_signature(route), []).append(route)
    chosen, missing, usage = [], [], {}
    for old in reference.get("routes", []):
        signature = route_signature(old); used = usage.get(signature, 0)
        copies = by_signature.get(signature, [])
        if used >= len(copies):
            missing.append(old.get("route_id")); continue
        chosen.append(copies[used]); usage[signature] = used + 1
    pairs = {tuple(sorted((a["route_id"], b["route_id"]))) for a, b in itertools.combinations(chosen, 2)
             if a["vehicle"] == b["vehicle"]}
    return {r["route_id"] for r in chosen}, pairs, {
        "reference_objective": reference.get("objective"), "matched_routes": len(chosen),
        "missing_routes": missing, "use": "seed_valid_constraints_only_no_route_fixes_no_upper_bound_claim"}


def run_direct(ctx, routes, *, seconds=120, round_seconds=25, mode="C", caps=None,
               slots_per_uav=3, horizon=30000, output_dir=None, loaded_ids=None,
               pair_keys=None, display=False, max_rounds=100):
    """Delayed exact constraints; every column stays globally selectable."""
    started = time.perf_counter()
    loaded_ids, pair_keys = set(loaded_ids or []), set(pair_keys or [])
    iterations, candidate, lower_bound = [], None, None
    next_slice = round_seconds
    status = "time_limit_without_certified_incumbent"
    output_dir = Path(output_dir) if output_dir else None
    for iteration in range(max_rounds):
        remaining = seconds - (time.perf_counter() - started)
        if remaining < .1:
            break
        plan, meta = solve_relaxation(ctx, routes, loaded_ids=loaded_ids, pair_keys=pair_keys,
                                      mode=mode, caps=caps, seconds=min(next_slice, remaining),
                                      slots_per_uav=slots_per_uav, horizon=horizon, display=display)
        bound = meta.get("dual_bound")
        if bound is not None and math.isfinite(float(bound)):
            lower_bound = float(bound) if lower_bound is None else max(lower_bound, float(bound))
        record = {"iteration": iteration, "all_route_instances_still_selectable": len(routes), **meta}
        if plan is None:
            record["accepted_as_feasible"] = False; iterations.append(record)
            if meta.get("status") == 2:
                status = "finite_model_infeasible_certified_by_outer_relaxation"
            elif meta.get("status") == 4:
                status = "solver_error_no_feasibility_or_optimality_claim"
            else:
                status = "solver_limit_or_rejection_without_new_incumbent"
            print(json.dumps(record, ensure_ascii=False), flush=True)
            if output_dir:
                save(output_dir / "迭代日志.json", iterations)
            # A short subsolve with no incumbent is not an infeasibility
            # certificate. Retry once using all remaining total budget,
            # without changing columns, constraints, or the solver gap.
            unused = seconds - (time.perf_counter() - started)
            if meta.get("status") == 1 and unused > .1:
                next_slice = unused
                continue
            break
        conflicts = transport_conflicts(plan)
        communication_failures = complete_communication(plan, loaded_ids)
        selected_ids = {r["route_id"] for r in plan["routes"]}
        new_loaded = {r["route_id"] for r in plan["routes"] if r["needs"]} - loaded_ids
        new_pairs = {tuple(sorted((a["route_id"], b["route_id"])))
                     for a, b in itertools.combinations(plan["routes"], 2)
                     if a["vehicle"] == b["vehicle"]} - pair_keys
        feasible = not conflicts and not communication_failures
        record.update(selected_routes=len(selected_ids), objective_recomputed=plan["objective"],
                      newly_loaded_route_blocks=len(new_loaded), newly_loaded_resource_pairs=len(new_pairs),
                      transport_conflicts=len(conflicts), incomplete_communication=len(communication_failures),
                      accepted_as_feasible=feasible)
        iterations.append(record)
        if output_dir:
            save(output_dir / f"松弛轮次_{iteration:03d}.json", {"meta": record, "relaxation_incumbent": plan,
                 "resource_conflicts": conflicts, "communication_failures": communication_failures})
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if feasible:
            plan["status"] = "finite_model_feasible_pending_independent_physics_verification"
            candidate = plan
            selected_value = plan["objective"][["N", "E", "C", "L"].index(mode)]
            gap = max(0.0, selected_value - lower_bound) if lower_bound is not None else None
            if meta["status"] == 0 and gap is not None and gap <= max(TOL, abs(selected_value) * 1e-7):
                status = "finite_model_scalar_optimum_certified_pending_independent_physics_verification"
            else:
                status = "finite_model_feasible_incumbent_without_optimality_certificate"
            break
        if not new_loaded and not new_pairs:
            status = "internal_validation_failure_no_new_constraints"; break
        loaded_ids.update(new_loaded); pair_keys.update(new_pairs)
        next_slice = round_seconds
        if output_dir:
            save(output_dir / "迭代日志.json", iterations)
            save(output_dir / "已补约束状态.json", {"loaded_route_ids": sorted(loaded_ids),
                                                   "resource_pairs": sorted(pair_keys)})
    result = {"method": "all_column_direct_joint_MILP_with_delayed_exact_constraints",
              "status": status, "scalar_objective": mode, "epsilon_caps": caps or {},
              "candidate_plan": candidate, "finite_model_valid_lower_bound": lower_bound,
              "iteration_count": len(iterations), "iterations": iterations,
              "elapsed_s": time.perf_counter() - started,
              "loaded_route_ids": sorted(loaded_ids), "resource_pairs": sorted(pair_keys),
              "scope": {"route_instances": len(routes), "relay_positions": len(ctx.qs),
                        "relay_slots_per_uav": slots_per_uav, "horizon_s": horizon,
                        "communication_assignment": "one relay per original certified atomic interval; merge=False",
                        "original_continuous_problem_global_optimality": False,
                        "independent_physics_verification_required": True,
                        "multiobjective_or_minimax_regret_optimum": False},
              "comparison": "Existing solve_q3.py ALNS outputs unchanged; compare scalar objectives only with matching caps."}
    if candidate is not None:
        v = candidate["objective"][["N", "E", "C", "L"].index(mode)]
        result["finite_model_upper_bound"] = v
        result["absolute_gap"] = max(0.0, v - lower_bound) if lower_bound is not None else None
    if output_dir:
        save(output_dir / "直接联合MILP结果.json", result); save(output_dir / "迭代日志.json", iterations)
        if candidate is not None:
            save(output_dir / "候选方案_待独立物理核验.json", candidate)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--round-seconds", type=float, default=25)
    parser.add_argument("--mode", choices=["N", "E", "C", "L"], default="C")
    parser.add_argument("--caps-json", default="{}", help='epsilon caps, e.g. {"N":24,"E":66,"L":500}')
    parser.add_argument("--route-file", default="子问题一/累计候选路线.json")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--slots-per-uav", type=int, default=3)
    parser.add_argument("--horizon", type=float, default=30000)
    parser.add_argument("--seed-reference", default=None, help="Only seed constraints; do not fix routes")
    parser.add_argument("--resume-state", default=None)
    parser.add_argument("--display", action="store_true")
    args = parser.parse_args()
    if args.seconds <= 0 or args.round_seconds <= 0:
        parser.error("Time budgets must be positive")
    output_dir = Path(args.output_dir) if args.output_dir else OUT / "全局直接求解" / datetime.now().strftime("%Y%m%d_%H%M%S")
    if not output_dir.is_absolute():
        output_dir = OUT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(args.route_file)
    if not source_path.is_absolute():
        source_path = OUT / source_path
    source_bytes = source_path.read_bytes()
    ctx = Context(); prepare_candidates(ctx); prepare_geometry(ctx)
    routes, library = expand_instances(ctx, json.loads(source_bytes.decode("utf-8")))
    if not routes:
        raise RuntimeError("No regenerated candidate route instances")
    library.update(source_file=str(source_path), source_sha256=hashlib.sha256(source_bytes).hexdigest(),
                   relay_candidate_sha256=hashlib.sha256(json.dumps(ctx.qs, sort_keys=True).encode()).hexdigest())
    save(output_dir / "冻结候选库清单.json", library)
    loaded, pairs, seed_meta = set(), set(), None
    if args.seed_reference:
        path = Path(args.seed_reference)
        if not path.is_absolute():
            path = OUT / path
        loaded, pairs, seed_meta = seed_blocks_from_reference(routes, load(path))
    if args.resume_state:
        path = Path(args.resume_state)
        if not path.is_absolute():
            path = OUT / path
        # Route IDs alone cannot establish unchanged pattern semantics. A
        # prior state is accepted only with its frozen-library manifest.
        prior_manifest = load(path.parent / "冻结候选库清单.json")
        for field in ("source_sha256", "relay_candidate_sha256", "records"):
            if prior_manifest.get(field) != library.get(field):
                raise ValueError(f"Resume state belongs to a different frozen library: {field}")
        state = load(path); loaded.update(state["loaded_route_ids"])
        pairs.update(tuple(p) for p in state["resource_pairs"])
    existing_ids = {r["route_id"] for r in routes}
    if not loaded <= existing_ids or any(a not in existing_ids or b not in existing_ids for a, b in pairs):
        raise ValueError("Constraint state does not belong to the frozen library")
    save(output_dir / "运行配置.json", {**vars(args), "seed_reference_metadata": seed_meta,
                                      "patterns": library["patterns"], "instances": len(routes)})
    print("FINITE_DIRECT_LIBRARY", library["patterns"], "INSTANCES", len(routes), "OUT", output_dir, flush=True)
    result = run_direct(ctx, routes, seconds=args.seconds, round_seconds=args.round_seconds,
                        mode=args.mode, caps=json.loads(args.caps_json), slots_per_uav=args.slots_per_uav,
                        horizon=args.horizon, output_dir=output_dir, loaded_ids=loaded,
                        pair_keys=pairs, display=args.display)
    print("FINITE_DIRECT_RESULT", result["status"], "BOUND", result["finite_model_valid_lower_bound"],
          "CANDIDATE", result["candidate_plan"]["objective"] if result["candidate_plan"] else None, flush=True)
    return 0 if result["candidate_plan"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
