"""Deterministic event tests for the no-spare battery location invariant.

Synthetic conservation examples only; these do not claim physical flight,
communication, time, or energy feasibility of any Q3 solution.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path


class State:
    def __init__(self):
        self.uav = {'U1': 'O01', 'U2': 'O01'}
        self.bat = {'B1': 'O01', 'B2': 'O01', 'B3': 'O01'}
        self.mounted = {'U1': 'B1', 'U2': 'B2'}
        self.events = []

    def check(self):
        assert len(self.mounted.values()) == len(set(self.mounted.values())), 'Battery mounted twice'
        for u, b in self.mounted.items():
            assert self.uav[u] == self.bat[b], 'Mounted battery teleported away from body'
        for q in set(self.uav.values()) | set(self.bat.values()):
            if q == 'O01':
                continue
            bodies = sum(p == q for p in self.uav.values())
            batteries = sum(p == q for p in self.bat.values())
            assert bodies == batteries, 'Remote battery/body conservation violated'
            loose = sum(p == q and b not in self.mounted.values() for b, p in self.bat.items())
            unpowered = sum(p == q and u not in self.mounted for u, p in self.uav.items())
            assert loose == unpowered, 'Loose inventory has no unpowered donor body'

    def fly(self, u, target):
        assert u in self.mounted, 'Cannot fly without a mounted battery'
        b = self.mounted[u]
        self.uav[u] = target; self.bat[b] = target
        self.check(); self.events.append(['fly', u, b, target])

    def detach(self, u):
        assert u in self.mounted
        b = self.mounted.pop(u)
        self.check(); self.events.append(['detach', u, b, self.uav[u]])

    def attach(self, u, b):
        assert u not in self.mounted, 'No spare/second mounted battery allowed'
        assert b not in self.mounted.values(), 'Battery already mounted elsewhere'
        assert self.uav[u] == self.bat[b], 'Cannot pick up a battery at another location'
        self.mounted[u] = b
        self.check(); self.events.append(['attach', u, b, self.uav[u]])


def main():
    records = []
    s = State(); s.check()
    s.fly('U1', 'S001'); s.detach('U1')
    assert s.bat['B1'] == 'S001' and 'U1' not in s.mounted
    records.append({'case': 'first_remote_loose_battery_requires_grounded_unpowered_donor', 'passed': True})
    snapshot = copy.deepcopy(s)
    try:
        snapshot.fly('U1', 'O01')
    except AssertionError:
        records.append({'case': 'unpowered_donor_cannot_leave', 'passed': True})
    else:
        raise AssertionError('Illegal unpowered departure accepted')
    s.fly('U2', 'S001'); s.detach('U2')
    s.attach('U1', 'B2'); s.attach('U2', 'B1')
    s.fly('U1', 'O01'); s.fly('U2', 'O01')
    assert all(p == 'O01' for p in s.bat.values())
    records.append({'case': 'legal_remote_exchange_of_mounted_arrivals_and_complete_return', 'passed': True})
    snapshot = State(); snapshot.fly('U1', 'S001'); snapshot.detach('U1')
    try:
        snapshot.attach('U1', 'B3')
    except AssertionError:
        records.append({'case': 'O01_inventory_cannot_be_taken_remotely', 'passed': True})
    else:
        raise AssertionError('Battery teleport accepted')
    snapshot = State(); snapshot.bat['B3'] = 'S001'
    try:
        snapshot.check()
    except AssertionError:
        records.append({'case': 'isolated_remote_stock_without_donor_body_rejected', 'passed': True})
    else:
        raise AssertionError('Artificial remote surplus accepted')
    snapshot = State()
    try:
        snapshot.attach('U1', 'B3')
    except AssertionError:
        records.append({'case': 'second_mounted_battery_rejected', 'passed': True})
    else:
        raise AssertionError('Spare battery accepted')
    result = {'status': 'PASS', 'tests': records, 'legal_event_trace': s.events,
              'scope': 'Synthetic battery/body location conservation only; no Q3 feasibility claim.',
              'unchanged_energy_requirement': 'Retain original complete-sortie energy <= one compatible battery capacity * 80%; per-battery SOC adds constraints and does not replace that original rule.'}
    path = Path(__file__).with_name('电池位置不变式_事件测试.json')
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('BATTERY_LOCATION_INVARIANT_TEST_PASS', len(records))


if __name__ == '__main__':
    main()
