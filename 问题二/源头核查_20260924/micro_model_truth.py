"""Independent finite enumeration of tiny joint scheduling instances.

Truth uses exact covers, resource assignments and all topological orders;
no historical schedules, metrics or production decoding build the oracle.
The production JointModel is tested only after oracle enumeration.
"""
from __future__ import annotations
import os
for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[key] = '1'
os.environ['MKL_THREADING_LAYER'] = 'SEQUENTIAL'
import itertools as it
import json
import math
import sys
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from q2_joint import JointModel


def fixture():
    boxes = {
        'a': dict(box='a', hard=True, deadline=6., expected=6., priority=3.),
        'b': dict(box='b', hard=False, deadline=None, expected=3., priority=1.),
        'c': dict(box='c', hard=False, deadline=None, expected=7., priority=2.),
    }
    data = dict(boxes=boxes, vehicles={'G': {}, 'H': {}},
                uavs={'G1': 'G', 'G2': 'G', 'H1': 'H'},
                batteries={'GB1': 'G', 'GB2': 'G', 'HB1': 'H'})
    specs = [
        ('ga', 'G', ['a'], [2], 4, 3, 3),
        ('gb', 'G', ['b'], [2], 5, 3, 3),
        ('gc', 'G', ['c'], [3], 6, 4, 5),
        ('gab', 'G', ['a', 'b'], [2, 4], 7, 4, 4),
        ('gbc', 'G', ['b', 'c'], [3, 5], 8, 5, 5),
        ('gac', 'G', ['a', 'c'], [4, 6], 9, 4, 6),
        ('gabc', 'G', ['a', 'b', 'c'], [2, 5, 8], 10, 5, 8),
        ('ha', 'H', ['a'], [1], 3, 6, 4),
        ('hb', 'H', ['b'], [2], 4, 6, 4),
        ('hc', 'H', ['c'], [3], 5, 6, 6),
        ('habc', 'H', ['a', 'b', 'c'], [2, 4, 6], 8, 6, 9),
    ]
    routes = []
    for rid, g, ids, offs, duration, charge, energy in specs:
        offsets = dict(zip(ids, offs))
        routes.append(dict(candidate_id=rid, vehicle=g, box_ids=ids,
            offsets=offsets, duration=float(duration), charge_s=float(charge),
            energy=float(energy), prep_s=1.,
            latest_start=min((boxes[b]['deadline']-offsets[b] for b in ids
                              if boxes[b]['hard']), default=math.inf),
            events=[dict(zone=b, boxes=[b]) for b in ids]))
    return data, routes


def enumerate_truth(data, routes, fixed=None):
    fixed = fixed or {}
    feasible = []
    covers = 0
    schedules = 0
    for flags in it.product((0, 1), repeat=len(routes)):
        selected = [r for r, flag in zip(routes, flags) if flag]
        ids = [b for r in selected for b in r['box_ids']]
        if sorted(ids) != sorted(data['boxes']):
            continue
        if not set(fixed) <= {r['candidate_id'] for r in selected}:
            continue
        covers += 1
        choices = []
        for r in selected:
            rid = r['candidate_id']
            if rid in fixed:
                choices.append([(fixed[rid]['uav'], fixed[rid]['battery_id'])])
            else:
                choices.append(list(it.product(
                    [u for u, g in data['uavs'].items() if g == r['vehicle']],
                    [p for p, g in data['batteries'].items() if g == r['vehicle']])))
        for resources in it.product(*choices):
            for order in it.permutations(range(len(selected))):
                uready = dict.fromkeys(data['uavs'], 0.)
                bready = dict.fromkeys(data['batteries'], 0.)
                deliveries = {}
                finish = []
                starts = {}
                valid = True
                for k in order:
                    r = selected[k]
                    u, p = resources[k]
                    start = max(uready[u], bready[p])
                    if r['candidate_id'] in fixed:
                        prescribed = fixed[r['candidate_id']]['start']
                        if start > prescribed+1e-9:
                            valid = False
                            break
                        start = prescribed
                    starts[r['candidate_id']] = start
                    end = start+r['duration']
                    uready[u], bready[p] = end, end+r['charge_s']
                    finish.append(end)
                    for b, offset in r['offsets'].items():
                        deliveries[b] = start+offset
                if not valid:
                    continue
                if any(deliveries[b] > x['deadline']+1e-9
                       for b, x in data['boxes'].items() if x['hard']):
                    continue
                schedules += 1
                den = sum(b['priority'] for b in data['boxes'].values() if not b['hard'])
                late = sum(b['priority']*max(0., deliveries[k]-b['expected'])
                           for k, b in data['boxes'].items() if not b['hard'])/den
                f = [len(selected), sum(r['energy'] for r in selected), max(finish), late]
                feasible.append(dict(objective=f, starts=starts,
                    selected=[r['candidate_id'] for r in selected], resources=resources))
    return feasible, dict(exact_covers=covers, enumerated_feasible_schedules=schedules)


def run():
    data, routes = fixture()
    truth, counts = enumerate_truth(data, routes)
    cases = []
    def check(name, weights=None, cap=None, order=None, fixed=None, oracle=truth):
        cap = cap or {}
        admissible = [t for t in oracle if all(t['objective']['NECL'.index(k)] <= v+1e-9
                                                for k, v in cap.items())]
        model = JointModel(data, deepcopy(routes), cap=cap, fixed=deepcopy(fixed), scope=name)
        if order is not None:
            plan, logs = model.lexsolve(order=order, seconds=10, seed=20260924)
            statuses = [m['status'] for m in logs]
            best = min((tuple(t['objective'][j] for j in order) for t in admissible), default=None)
            observed = None if plan is None else tuple(plan['objective'][j] for j in order)
        else:
            plan, meta = model.solve(weights, seconds=10, seed=20260924)
            statuses = [meta['status']]
            best = min((sum(w*f for w, f in zip(weights, t['objective'])) for t in admissible), default=None)
            observed = None if plan is None else sum(w*f for w, f in zip(weights, plan['objective']))
        ok = (plan is None) == (not admissible)
        if best is not None:
            av = observed if isinstance(observed, tuple) else [observed]
            bv = best if isinstance(best, tuple) else [best]
            ok = ok and all(abs(a-b) <= 2e-5 for a, b in zip(av, bv))
            ok = ok and all(s == 'Optimal' for s in statuses)
            # Match decoded event times to an independently enumerated feasible schedule.
            ok = ok and any(all(abs(x-y)<2e-5 for x, y in zip(t['objective'], plan['objective']))
                            for t in admissible)
        else:
            ok = ok and statuses == ['Infeasible']
        cases.append(dict(name=name, passed=bool(ok), oracle_optimum=best,
            production_value=observed, status=statuses, caps=cap,
            objective=None if plan is None else plan['objective']))
        if not ok:
            raise AssertionError(cases[-1])
    for j, label in enumerate('NECL'):
        check('single_'+label, weights=[int(j==k) for k in range(4)])
    check('positive_weighted', weights=[1., .7, .9, 2.])
    check('epsilon_NE', weights=[0.,0.,1.,0.], cap={'N':2,'E':9})
    check('epsilon_C', weights=[0.,1.,0.,0.], cap={'C':8})
    check('epsilon_L', weights=[0.,0.,1.,0.], cap={'L':0.})
    check('epsilon_all', weights=[0.,0.,1.,0.], cap={'N':3, 'E':10, 'C':12, 'L':1.})
    check('infeasible_combination', weights=[0.,0.,1.,0.], cap={'N':1,'E':7.})
    check('lex_C_LEN', order=(2,3,1,0))
    check('lex_N_ECL', order=(0,1,2,3))
    fixed = {'gb': dict(candidate_id='gb', start=2., uav='G1', battery_id='GB1')}
    fixed_truth, fixed_counts = enumerate_truth(data, routes, fixed=fixed)
    check('frozen_external_interval', order=(2,3,1,0), fixed=fixed, oracle=fixed_truth)
    resource_scenarios = []
    for tag, nu, nb in [('one_uav_two_batteries', 1, 2),
                        ('two_uavs_one_battery', 2, 1),
                        ('one_uav_one_battery', 1, 1)]:
        data = dict(boxes={
            'a': dict(box='a', hard=False, deadline=None, expected=2., priority=1.),
            'b': dict(box='b', hard=False, deadline=None, expected=5., priority=2.)},
            vehicles={'G': {}},
            uavs={f'G{k}':'G' for k in range(nu)},
            batteries={f'P{k}':'G' for k in range(nb)})
        routes = [dict(candidate_id='r'+b, vehicle='G', box_ids=[b],
            offsets={b: float(offset)}, duration=float(duration), charge_s=float(charge),
            energy=1., prep_s=1., latest_start=math.inf,
            events=[dict(zone=b, boxes=[b])])
            for b,offset,duration,charge in [('a',2,4,8),('b',3,5,2)]]
        specific, n = enumerate_truth(data, routes)
        resource_scenarios.append(dict(name=tag, **n))
        check(tag+'_C', weights=[0.,0.,1.,0.], oracle=specific)
        check(tag+'_L', weights=[0.,0.,0.,1.], oracle=specific)
        check(tag+'_lex', order=(2,3,1,0), oracle=specific)
    result = dict(passed=all(x['passed'] for x in cases), test_count=len(cases),
        truth_method='enumerate exact covers, compatible resource assignments, all task orders; earliest starts on each order',
        scope='tiny abstract coefficient fixtures; does not prove complete route enumeration or physical assumptions',
        counts=counts, fixed_counts=fixed_counts, resource_scenarios=resource_scenarios, cases=cases)
    (HERE/'micro_model_truth.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run()
