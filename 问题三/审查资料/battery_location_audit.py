"""Audit the battery location trace of existing O01-only Q3 plans.

This validates a restricted strategy allowed by the expert clarification. It
does not certify plans with en-route swaps, airborne swaps, remote charging,
or battery transport as cargo. Those need explicit events and source rules.
Original whole-sortie energy limits are retained. No official result is changed.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import pandas as pd
from audit_source_and_result import DATA, table

HERE = Path(__file__).resolve().parent
Q3 = HERE.parent
TOL = 2e-4


def audit_locations(plan):
    checks, ledger = [], []

    def check(name, condition, detail=None):
        checks.append(dict(check=name, passed=bool(condition), detail=detail))

    vehicles = {r['机型编号']: r for r in table('运输无人机数据.xlsx', 1, 2, 5)}
    stock = {r['机型编号']: r for r in table('运输无人机数据.xlsx', 18, 19, 22)}
    bodies = {r['无人机编号']: r['机型编号'] for r in table('运输无人机数据.xlsx', 7, 8, 16)}
    batteries = {f'{g}-BAT-{i:02d}': g for g in stock
                 for i in range(1, int(stock[g]['共享电池组总数（组）'])+1)}
    raw = pd.read_excel(DATA/'物资需求与配送时限.xlsx', sheet_name='逐箱货箱清单')
    mass_by_box = raw.set_index('货箱编号')['单箱质量（kg）'].to_dict()
    assigned = defaultdict(list)
    for box in plan['boxes']:
        assigned[box['route_id']].append(box['box'])

    # An unsupported extension must not silently fall through a baseline PASS.
    extension = bool(plan.get('battery_events') or plan.get('battery_swaps'))
    extension |= any(r.get('battery_swaps') or r.get('battery_sequence')
                     or r.get('charging_events') for r in plan['routes'])
    if extension:
        return dict(status='UNSUPPORTED_EXTENDED_EVENT_SCHEMA', checks=[], ledger=[],
                    reason='Needs explicit en-route battery and aircraft location/SOC events; no baseline certificate.')

    # The source rule fixes all initial shared batteries at O01 and ready.
    # Explicit contradictory declarations must not be ignored merely because
    # the baseline schema normally omits them.
    for key in ('initial_battery_locations', 'battery_initial_locations'):
        locations = plan.get(key)
        if locations is None:
            continue
        check(key+'/mapping schema', isinstance(locations, dict))
        if isinstance(locations, dict):
            for battery, location in locations.items():
                check(key+'/'+str(battery)+'/exists initially at O01',
                      battery in batteries and location == 'O01')
    states = plan.get('initial_batteries')
    if states is not None:
        check('initial_batteries/list schema', isinstance(states, list))
        if isinstance(states, list):
            check('initial_batteries/unique declarations',
                  all(isinstance(x, dict) for x in states) and
                  len({str(x.get('battery_id')) for x in states if isinstance(x, dict)}) == len(states))
            for index, state in enumerate(states):
                valid = isinstance(state, dict)
                check(f'initial_batteries/{index}/known compatible full battery at O01', valid and
                      state.get('battery_id') in batteries and state.get('location') == 'O01' and
                      state.get('vehicle', batteries.get(state.get('battery_id'))) == batteries.get(state.get('battery_id')) and
                      isinstance(state.get('soc', 1.), (int, float)) and abs(float(state.get('soc', 1.))-1.) < 1e-8)
    check('no plan-level spare battery cargo', not plan.get('spare_batteries') and not plan.get('battery_cargo'))

    for battery, g in batteries.items():
        ledger.append(dict(battery=battery, vehicle_type=g, route_id='', uav='',
                           event='initial_ready', t0=0., t1=0., origin='O01', destination='O01',
                           soc_before=1., soc_after=1.))
    check('route IDs unique', len({r['route_id'] for r in plan['routes']}) == len(plan['routes']))
    uses = defaultdict(list)
    aircraft_uses = defaultdict(list)
    for r in plan['routes']:
        rid, battery, g = r['route_id'], r.get('battery_id'), r['vehicle']
        known_type = g in vehicles and g in stock
        check(rid+'/known vehicle type', known_type)
        valid_id = isinstance(battery, str) and battery in batteries and batteries[battery] == g
        check(rid+'/one compatible installed battery', valid_id)
        check(rid+'/aircraft type', bodies.get(r['uav']) == g)
        extra = r.get('spare_batteries', [])
        check(rid+'/no declared spare batteries', not extra and not r.get('battery_cargo', []))
        named = assigned[rid]
        check(rid+'/payload contains original boxes only', bool(named) and all(b in mass_by_box for b in named))
        check(rid+'/payload mass contains no extra battery cargo',
              all(b in mass_by_box for b in named) and
              abs(sum(mass_by_box.get(b, 0.) for b in named)-r['mass']) < 1e-7)
        segments = r.get('segments', [])
        expected_path = ['O01'] + r['zones'] + ['O01']
        check(rid+'/one continuous O01 round trip',
              len(segments) == len(expected_path)-1 and
              all(s['from'] == a and s['to'] == b
                  for s, a, b in zip(segments, expected_path, expected_path[1:])))
        check(rid+'/no declared remote departure or return',
              r.get('origin', 'O01') == 'O01' and r.get('destination', 'O01') == 'O01')
        if not known_type:
            continue
        capacity = float(vehicles[g]['电池可用能量（kWh）'])
        reserve = float(vehicles[g]['返航电量下限（%）'])/100
        tfull = float(stock[g]['等效完全充电时间（s）'])
        energy = sum(s['energy'] for s in segments)
        soc = 1-energy/capacity
        charge = tfull*(max(.9-soc, 0.)*.65/.9 + (1-max(.9, soc))*.35/.1)
        check(rid+'/finite times and energy', all(math.isfinite(float(r[k])) for k in
              ('start', 'takeoff', 'finish', 'recharge', 'energy')) and r['start'] >= -TOL)
        check(rid+'/whole-sortie reserve retained', 0 <= energy <= (1-reserve)*capacity+1e-7)
        check(rid+'/energy and SOC', abs(energy-r['energy']) < 2e-6 and abs(soc-r['soc']) < 2e-6)
        check(rid+'/declared departure SOC is full',
              all(isinstance(r.get(key, 1.), (int, float)) and
                  abs(float(r.get(key, 1.))-1.) < 1e-8 for key in ('start_soc', 'departure_soc')))
        check(rid+'/full charge ready time', abs(r['recharge']-(r['finish']+charge)) < TOL)
        check(rid+'/preparation before takeoff and return',
              r['start'] <= r['takeoff']+TOL and r['takeoff'] < r['finish']+TOL)
        if not valid_id:
            continue
        uses[battery].append((r['start'], r['finish']+charge, rid))
        aircraft_uses[r['uav']].append((r['start'], r['finish'], rid))
        ledger.extend([
            dict(battery=battery, vehicle_type=g, route_id=rid, uav=r['uav'],
                 event='installed_during_preparation', t0=r['start'], t1=r['takeoff'],
                 origin='O01', destination='O01', soc_before=1., soc_after=1.),
            dict(battery=battery, vehicle_type=g, route_id=rid, uav=r['uav'],
                 event='installed_entire_round_trip', t0=r['takeoff'], t1=r['finish'],
                 origin='O01', destination='O01', soc_before=1., soc_after=soc,
                 visited_nodes='→'.join(expected_path)),
            dict(battery=battery, vehicle_type=g, route_id=rid, uav='',
                 event='detached_charging', t0=r['finish'], t1=r['finish']+charge,
                 origin='O01', destination='O01', soc_before=soc, soc_after=1.),
        ])
    for battery, intervals in uses.items():
        previous_ready = 0.
        for start, ready, rid in sorted(intervals):
            check(battery+'/'+rid+'/available at O01 and fully charged', start >= previous_ready-TOL)
            previous_ready = max(previous_ready, ready)
    for uav, intervals in aircraft_uses.items():
        intervals.sort()
        check(uav+'/single installed battery through nonoverlapping tasks',
              all(a[1] <= b[0]+TOL for a, b in zip(intervals, intervals[1:])))
    return dict(status='PASS' if all(c['passed'] for c in checks) else 'FAIL', checks=checks,
                check_count=len(checks), inventory_count=len(batteries), ledger=ledger,
                scope='existing transport plans with no en-route battery change; one working battery travels with each UAV',
                expert_rule='no carried spare; swaps may occur where batteries physically exist; all initial shared batteries at O01',
                remote_swaps_searched=False, original_global_optimality_claim=False,
                dependency='Segment geometry/energy and named boxes also require raw arithmetic audit and full DEM verification.')


def self_test(plan):
    tests = []
    def run(name, changed, expected):
        got = audit_locations(changed)['status']
        tests.append(dict(test=name, expected=expected, actual=got, passed=got == expected))
    run('baseline', plan, 'PASS')
    p = copy.deepcopy(plan); p['routes'][0]['spare_batteries'] = ['C-BAT-01']
    run('extra onboard spare', p, 'FAIL')
    p = copy.deepcopy(plan); p['routes'][0]['battery_id'] = 'C-BAT-99'
    run('nonexistent battery', p, 'FAIL')
    p = copy.deepcopy(plan); p['routes'][0]['origin'] = 'S001'
    run('remote departure cannot receive baseline certificate', p, 'FAIL')
    p = copy.deepcopy(plan); p['routes'][0]['recharge'] -= 100.
    run('premature recharge', p, 'FAIL')
    p = copy.deepcopy(plan); p['routes'][0]['mass'] += 1.
    run('undeclared additional payload', p, 'FAIL')
    p = copy.deepcopy(plan); p['battery_events'] = [{'kind': 'remote_swap'}]
    run('remote event needs extended verifier', p, 'UNSUPPORTED_EXTENDED_EVENT_SCHEMA')
    p = copy.deepcopy(plan); g=p['routes'][0]['vehicle'];other=next(x for x in 'ABC' if x!=g)
    p['routes'][0]['battery_id']=other+'-BAT-01'
    run('existing incompatible battery', p, 'FAIL')
    p = copy.deepcopy(plan); p['routes'][0]['vehicle']='UNDEFINED'
    run('unknown aircraft type rejected without crashing', p, 'FAIL')
    p = copy.deepcopy(plan); p['initial_battery_locations']={p['routes'][0]['battery_id']:'S001'}
    run('remote initial inventory contradicts source', p, 'FAIL')
    p = copy.deepcopy(plan); p['initial_batteries']=[{'battery_id':p['routes'][0]['battery_id'],'location':'O01','soc':.5}]
    run('initial battery not full', p, 'FAIL')
    p = copy.deepcopy(plan); p['routes'][0]['start_soc']=.5
    run('declared partially charged departure', p, 'FAIL')
    p = copy.deepcopy(plan); p['battery_cargo']=['A-BAT-01']
    run('plan-level declared spare cargo', p, 'FAIL')
    groups=defaultdict(list)
    for i,r in enumerate(plan['routes']):groups[r['vehicle']].append(i)
    group=next(v for v in groups.values() if len(v)>=2)
    ia,ib=sorted(group,key=lambda i:plan['routes'][i]['start'])[:2]
    def shift(route, new_start):
        delta=new_start-route['start']
        for key in ('start','takeoff','finish','recharge'):route[key]+=delta
    p=copy.deepcopy(plan);a,b=p['routes'][ia],p['routes'][ib]
    b['battery_id']=a['battery_id'];shift(b,a['start'])
    run('same battery used on overlapping flights',p,'FAIL')
    p=copy.deepcopy(plan);a,b=p['routes'][ia],p['routes'][ib]
    b['battery_id']=a['battery_id'];shift(b,(a['finish']+a['recharge'])/2)
    run('battery reused after return but before fully charged',p,'FAIL')
    p=copy.deepcopy(plan);a,b=p['routes'][ia],p['routes'][ib]
    b['uav']=a['uav'];shift(b,a['start'])
    run('one body simultaneously on two routes',p,'FAIL')
    p=copy.deepcopy(plan);p['initial_battery_locations']={p['routes'][0]['battery_id']:'O01'}
    run('consistent explicit initial location remains valid',p,'PASS')
    return dict(passed=all(t['passed'] for t in tests), tests=tests)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', default='搜索精修/扩展固定结构精修_v1/official/已核验方案.json')
    parser.add_argument('--output', default='审查资料/专家换电补充核验')
    args = parser.parse_args()
    source = Path(args.plan); source = source if source.is_absolute() else Q3/source
    out = Path(args.output); out = out if out.is_absolute() else Q3/out
    out.mkdir(parents=True, exist_ok=True)
    plan = json.loads(source.read_text(encoding='utf-8'))
    result = audit_locations(plan); result['source_plan'] = str(source)
    tests = self_test(plan)
    (out/'电池位置核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (out/'错误注入检查.json').write_text(json.dumps(tests, ensure_ascii=False, indent=2), encoding='utf-8')
    columns = ['battery', 'vehicle_type', 'route_id', 'uav', 'event', 't0', 't1',
               'origin', 'destination', 'soc_before', 'soc_after', 'visited_nodes']
    with (out/'运输电池位置与SOC事件.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader(); writer.writerows(result['ledger'])
    print(json.dumps(dict(status=result['status'], checks=result.get('check_count'),
                          self_tests=tests['passed'], output=str(out)), ensure_ascii=False))
    if result['status'] != 'PASS' or not tests['passed']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
