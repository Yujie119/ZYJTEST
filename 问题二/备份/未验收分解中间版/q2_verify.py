"""Independent, raw-input verifier for Question 2 result plans."""
from __future__ import annotations
import math
from collections import defaultdict
from copy import deepcopy
from q2_data import make_route, decode

TOL=1e-6

def _close(a,b,tol=TOL): return abs(float(a)-float(b))<=tol*max(1.,abs(float(a)),abs(float(b)))

def verify_plan(data,plan,tol=TOL):
    checks={}; errors=[]; routes=plan.get('routes',[]); boxes=plan.get('boxes',[])
    known_uav=data['uavs'];known_bat=data['batteries']
    if not routes: errors.append('empty_plan')
    rebuilt=[];ids=[]
    for r in routes:
        rid=r.get('route_id');
        if not rid: errors.append('missing_route_id');continue
        u=r.get('uav');p=r.get('battery_id');g=r.get('vehicle')
        if u not in known_uav: errors.append(f'unknown_uav:{u}')
        elif known_uav[u]!=g: errors.append(f'uav_type:{rid}')
        if p not in known_bat: errors.append(f'unknown_battery:{p}')
        elif known_bat[p]!=g: errors.append(f'battery_type:{rid}')
        events=r.get('events',[])
        for e in events:
            for b in e.get('boxes',[]): ids.append(b)
        try:
            rr=make_route(data,g,events)
            if rr is None: errors.append(f'route_physics:{rid}');continue
            for key in ('mass','volume','energy','duration','soc','charge_s'):
                if key in r and not _close(r[key],rr[key],tol): errors.append(f'cache_{key}:{rid}')
            if not _close(float(r.get('start',math.nan))+rr['duration'],float(r.get('finish',math.nan)),tol): errors.append(f'finish:{rid}')
            if not _close(float(r.get('finish',math.nan))+rr['charge_s'],float(r.get('recharge',math.nan)),tol): errors.append(f'recharge:{rid}')
            if float(r.get('start',-1)) < -tol or float(r.get('start',0)) > rr['latest_start']+tol: errors.append(f'start_window:{rid}')
            rebuilt.append(dict(rr,route_id=rid,start=float(r['start']),uav=u,battery_id=p,finish=float(r['finish']),recharge=float(r['recharge'])))
        except Exception as exc: errors.append(f'route_decode:{rid}:{exc}')
    checks['route_physics']=not any(x.startswith(('route_physics','route_decode','cache_','finish:','recharge:','start_window:')) for x in errors)
    checks['unique_coverage']=len(ids)==len(set(ids))==len(data['boxes']) and set(ids)==set(data['boxes'])
    if not checks['unique_coverage']: errors.append('coverage')
    checks['destination']=True
    for r in routes:
        for e in r.get('events',[]):
            for b in e.get('boxes',[]):
                if b not in data['boxes'] or data['boxes'][b]['zone']!=e.get('zone'):
                    checks['destination']=False;errors.append(f'destination:{b}')
    if not checks['destination']: pass
    checks['hard_deadlines']=True
    delivered={b['box']:float(b['delivery']) for b in boxes if 'box' in b}
    for b,v in data['boxes'].items():
        if v['hard'] and (b not in delivered or delivered[b] > v['deadline']+tol): checks['hard_deadlines']=False;errors.append(f'hard_deadline:{b}')
    # Reconstruct delivery times from route events, never from the output box cache.
    expected_del={}
    for r in rebuilt:
        for b,t in r['offsets'].items(): expected_del[b]=r['start']+t
    if set(expected_del)!=set(data['boxes']): checks['delivery_rebuild']=False;errors.append('delivery_set')
    else: checks['delivery_rebuild']=all(_close(expected_del[b],delivered.get(b,float('nan')),tol) for b in data['boxes'])
    if not checks['delivery_rebuild']: errors.append('delivery_cache')
    u_occ=defaultdict(list);b_occ=defaultdict(list)
    for r in rebuilt:
        u_occ[r['uav']].append((r['start'],r['finish'],r['route_id']))
        b_occ[r['battery_id']].append((r['start'],r['recharge'],r['route_id']))
    checks['uav_nonoverlap']=True;checks['battery_nonoverlap']=True
    for d,iv in u_occ.items():
        iv=sorted(iv)
        if any(a[1]>b[0]+tol for a,b in zip(iv,iv[1:])):checks['uav_nonoverlap']=False;errors.append(f'uav_overlap:{d}')
    for p,iv in b_occ.items():
        iv=sorted(iv)
        if any(a[1]>b[0]+tol for a,b in zip(iv,iv[1:])):checks['battery_nonoverlap']=False;errors.append(f'battery_overlap:{p}')
    checks['soc']=all(r['soc']>=data['vehicles'][r['vehicle']]['rho']-tol for r in rebuilt)
    if not checks['soc']: errors.append('soc')
    soft=[data['boxes'][b] | {'delivery':expected_del[b]} for b in data['boxes'] if not data['boxes'][b]['hard']]
    den=sum(b['priority'] for b in soft) or 1.
    obj=[len(rebuilt),sum(r['energy'] for r in rebuilt),max((r['finish'] for r in rebuilt),default=0.),sum(b['priority']*max(0.,b['delivery']-b['expected']) for b in soft)/den]
    checks['objective']=all(_close(obj[i],plan.get('objective',[math.nan]*4)[i],tol) for i in range(4))
    if not checks['objective']:errors.append('objective_cache')
    checks['all']=not errors
    return checks,errors,dict(routes=rebuilt,objective=obj,boxes=boxes)
