"""Bounded checks of the direct Q3 solver; no official geometry caches loaded."""
from pathlib import Path
import contextlib
import copy
import io
import json
import math
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '问题三'))
sys.dont_write_bytecode = True
import numpy as np
from q3_common import Context, certificate, make_route
from solve_q3_global import expand_instances, run_direct
from q3_direct_milp import solve_relaxation, transport_conflicts, complete_communication


def local_certificates(ctx, zone):
    """Rebuild only two needed arcs from raw DEM; no prepare_* cache paths."""
    for i, j in [(0, zone), (zone, 0)]:
        g = ctx.geos[i, j]
        p0 = ctx.xyz[i].copy(); p1 = p0.copy(); p1[2] = g['cruise']
        p3 = ctx.xyz[j].copy(); p2 = p3.copy(); p2[2] = g['cruise']
        arcs = []
        for name, a, b, length in [('爬升',p0,p1,g['up']),('巡航',p1,p2,g['distance']),('下降',p2,p3,g['down'])]:
            n = max(1, math.ceil(length / 100))
            for k in range(n):
                aa = a + (b-a)*k/n; bb = a + (b-a)*(k+1)/n
                arcs.append(dict(phase=name, a=aa.tolist(), b=bb.tolist(), length=length/n,
                                 **certificate(ctx, aa, bb)))
        ctx.arc_cache[i,j] = arcs
    for k in [0, zone]:
        ctx.node_cache[k] = certificate(ctx, ctx.xyz[k], ctx.xyz[k])


def narrow(ctx, box_filter, zone):
    small = copy.copy(ctx)
    small.boxes = ctx.boxes.loc[box_filter].copy()
    small.catinfo = {c:g.iloc[0].to_dict() for c,g in small.boxes.groupby('category')}
    small.arc_cache = {}; small.node_cache = {}
    local_certificates(small, zone)
    return small


def call_direct(ctx, routes, **kwargs):
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        result = run_direct(ctx, routes, seconds=25, round_seconds=10, slots_per_uav=1, **kwargs)
    result['captured_stdout'] = captured.getvalue()
    return result


def independent_checks(ctx, plan):
    if plan is None:
        return {'plan_exists':False}
    overlaps = []
    for i,a in enumerate(plan['routes']):
        for b in plan['routes'][i+1:]:
            for resource,end in [('uav','finish'),('battery_id','recharge')]:
                if a[resource] == b[resource] and min(a[end],b[end])-max(a['start'],b['start']) > 2e-4:
                    overlaps.append([a['route_id'],b['route_id'],resource])
    actual_c = max(r['finish'] for r in plan['routes'] + plan['relays'])
    return {'plan_exists':True, 'unique_instance_ids':len({r['route_id'] for r in plan['routes']})==len(plan['routes']),
            'all_expected_box_ids_once':sorted(b['box'] for b in plan['boxes'])==sorted(ctx.boxes.box.tolist()),
            'hard_deadlines':all(b['delivery'] <= b['deadline']+2e-4 for b in plan['boxes'] if b['hard']),
            'body_and_battery_nonoverlap':not overlaps,'overlaps':overlaps,
            'objective_C_includes_both_types':abs(plan['objective'][2]-actual_c)<2e-4,
            'NT_matches':plan['NT']==len(plan['routes']),'NR_matches':plan['NR']==len(plan['relays']),
            'energy_sum_matches':abs(plan['objective'][1]-sum(r['energy'] for r in plan['routes']+plan['relays']))<1e-7}


def main():
    started = time.perf_counter()
    ctx = Context()
    q = ctx.relay_geometry(0.0,0.0,100.0)
    assert q is not None
    q['qid'] = 'TEST-O01-100'; ctx.qs=[q]
    results = {'scope':'Read-only raw Context, new local arc certificates for O01-S011 and O01-S001; no official cache read, no full80 optimization or full independent verifier.',
               'review_independence':'same-family','acceptance_status':'provisional','cases':{}}

    s11 = narrow(ctx, ctx.boxes.zone=='S011', 11)
    counts = s11.boxes.groupby('category').size().to_dict()
    src = make_route(s11,'B',[{'zone':'S011','counts':counts}],'TEST-S011')
    assert src is not None and src['nbox']==3 and not src['needs']
    routes,library = expand_instances(s11,[src])
    single = call_direct(s11,routes)
    checks = independent_checks(s11,single['candidate_plan'])
    checks.update(all_direct=not routes[0]['needs'], exactly_one_instance=len(routes)==1,
                  one_transport_zero_relays=single['candidate_plan']['NT']==1 and single['candidate_plan']['NR']==0,
                  C_equals_raw_route_duration=abs(single['candidate_plan']['objective'][2]-src['duration'])<2e-4)
    results['cases']['S011_three_boxes_all_direct']={'library':library,'checks':checks,'result':single}

    water = narrow(ctx,(ctx.boxes.zone=='S001')&(ctx.boxes.kind=='饮用水'),1)
    cat = water.boxes.category.iloc[0]
    srcw = make_route(water,'B',[{'zone':'S001','counts':{cat:2}}],'TEST-WATER')
    assert srcw is not None and not srcw['needs']
    wroutes,wlib = expand_instances(water,[srcw])
    initial,initial_meta = solve_relaxation(water,wroutes,loaded_ids=set(),pair_keys=set(),seconds=10,slots_per_uav=1)
    assert initial is not None
    limited = call_direct(water,wroutes,max_rounds=1)
    repeated = call_direct(water,wroutes)
    checks = independent_checks(water,repeated['candidate_plan'])
    checks.update(four_independent_copies=len(wroutes)==4 and len({r['route_id'] for r in wroutes})==4,
                  same_pattern=len({r['pattern_id'] for r in wroutes})==1,
                  initial_status_is_relaxation=initial['status']=='outer_relaxation_incumbent_not_a_feasible_Q3_plan',
                  initial_has_real_resource_conflict=bool(transport_conflicts(initial)),
                  limited_round_does_not_export_relaxation=limited['candidate_plan'] is None and 'finite_model_upper_bound' not in limited,
                  delayed_resource_pairs_materialized=any(it.get('newly_loaded_resource_pairs',0)>0 for it in repeated['iterations']),
                  more_than_one_round=repeated['iteration_count']>=2,
                  inventory_not_expanded={r['uav'] for r in repeated['candidate_plan']['routes']}<= {'U05','U06'} and
                     {r['battery_id'] for r in repeated['candidate_plan']['routes']} <= {f'B-BAT-{i:02d}' for i in range(1,5)},
                  initial_bound_below_final_value=float(initial_meta['dual_bound'])<=repeated['candidate_plan']['objective'][2]+2e-4)
    results['cases']['S001_eight_water_four_B_instances']={'library':wlib,'checks':checks,'initial':initial,'initial_meta':initial_meta,'one_round_result':limited,'result':repeated}

    # Controlled block fixture: force relay cover of an otherwise direct raw
    # route. This tests synchronization and C, not an actual need for a relay.
    fixture = copy.deepcopy(routes)
    fixture[0]['needs']=[{'t0':fixture[0]['prep_s'],'t1':fixture[0]['duration'],'mask':1}]
    unloaded,umeta = solve_relaxation(s11,fixture,loaded_ids=set(),pair_keys=set(),seconds=10,slots_per_uav=1)
    one = call_direct(s11,fixture,max_rounds=1)
    blocked = call_direct(s11,fixture)
    checks = independent_checks(s11,blocked['candidate_plan'])
    plan = blocked['candidate_plan']
    checks.update(unloaded_missing_block_detected=bool(complete_communication(unloaded,set())),
                  unloaded_plan_labelled_relaxation=unloaded['status']=='outer_relaxation_incumbent_not_a_feasible_Q3_plan',
                  one_round_no_false_feasible=one['candidate_plan'] is None and 'finite_model_upper_bound' not in one,
                  communication_block_added=blocked['iteration_count']>=2 and bool(blocked['loaded_route_ids']),
                  delayed_block_complete=not complete_communication(plan,set(blocked['loaded_route_ids'])),
                  relay_returns_last=max(r['finish'] for r in plan['relays']) > max(r['finish'] for r in plan['routes'])+1,
                  C_equals_transport_return_plus_relay_back=abs(plan['objective'][2]-src['duration']-q['back_s'])<2e-4,
                  relaxation_bound_is_lower=float(umeta['dual_bound']) <= plan['objective'][2]+2e-4)
    results['cases']['controlled_communication_block_and_joint_C']={'physical_scope':'Synthetic mandatory relay assignment on an actually direct raw route. Geometry need is not asserted or certified. This isolates MILP block completion and joint-C logic.',
                 'checks':checks,'unloaded':unloaded,'unloaded_meta':umeta,'one_round_result':one,'result':blocked}
    booleans = [(name,k,v) for name,case in results['cases'].items() for k,v in case['checks'].items() if isinstance(v,bool)]
    results['summary']={'boolean_checks':len(booleans),'passed':sum(v for _,_,v in booleans),
                        'failed':[{'case':name,'check':k} for name,k,v in booleans if not v],
                        'elapsed_s':time.perf_counter()-started}
    (OUT/'test_direct_joint.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,default=lambda o:o.item() if hasattr(o,'item') else str(o)),encoding='utf-8')
    print(json.dumps(results['summary'],ensure_ascii=False,indent=2))
    for name,case in results['cases'].items():
        result=case['result'];print(name,result['status'],result['iteration_count'],result['candidate_plan']['objective'] if result['candidate_plan'] else None)
    return 1 if results['summary']['failed'] else 0

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception:
        error=traceback.format_exc()
        (OUT/'test_direct_joint.json').write_text(json.dumps({'status':'execution_failed','traceback':error},ensure_ascii=False,indent=2),encoding='utf-8')
        raise
