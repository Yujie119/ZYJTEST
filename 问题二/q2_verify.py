"""Independent reconstruction: never imports make_route, seg, charge or solver."""
from __future__ import annotations
import math
import hashlib
from collections import Counter,defaultdict

TIME_TOL=2e-5
ENERGY_TOL=1e-7

def verify_plan(data,plan,tol=TIME_TOL):
    errors=[];checks={k:True for k in ['coverage','identifiers','destination','hard_deadlines','mass_volume','geometry_energy',
        'delivery_times','resource_times','uav_nonoverlap','battery_nonoverlap','full_charge_reuse','soc','objective','finite']}
    def fail(check,msg):checks[check]=False;errors.append(f'{check}: {msg}')
    def num(value):
        try:return math.isfinite(float(value))
        except (TypeError,ValueError):return False
    def equal(check,a,b,label,eps=tol):
        if not num(a) or not num(b):fail('finite',label);fail(check,label)
        elif abs(float(a)-float(b))>eps:fail(check,f'{label}: {a} != {b}')
    raw=data['boxes'];routes=plan.get('routes',[]);rows=plan.get('boxes',[])
    route_ids=[r.get('route_id') for r in routes]
    if not routes or None in route_ids or len(route_ids)!=len(set(route_ids)):fail('identifiers','empty/duplicate/missing route IDs')
    rowids=[b.get('box') for b in rows]
    if Counter(rowids)!=Counter(raw.keys()):fail('coverage','exported box rows are not exact cover')
    rowmap={b.get('box'):b for b in rows};visited=[];delivery={};rebuilt=[];u_inter=defaultdict(list);p_inter=defaultdict(list)
    for r in routes:
        rid=r.get('route_id');g=r.get('vehicle');u=r.get('uav');p=r.get('battery_id')
        if g not in data['vehicles']:fail('identifiers',f'{rid}: unknown type');continue
        if data['uavs'].get(u)!=g:fail('identifiers',f'{rid}: unknown/mismatched UAV {u}')
        if data['batteries'].get(p)!=g:fail('identifiers',f'{rid}: unknown/mismatched battery {p}')
        v=data['vehicles'][g];events=r.get('events',[]);ids=[b for e in events for b in e.get('boxes',[])]
        canonical=(g,tuple((e.get('zone'),tuple(sorted(e.get('boxes',[])))) for e in events))
        identity='K'+hashlib.sha256(repr(canonical).encode()).hexdigest()[:16]
        if r.get('candidate_id')!=identity:fail('identifiers',f'{rid}: inconsistent candidate identity')
        visited.extend(ids)
        if not events or any(not e.get('boxes') for e in events):fail('destination',f'{rid}: empty visit')
        if len(set(ids))!=len(ids):fail('coverage',f'{rid}: repeated box')
        if any(b not in raw for b in ids):fail('identifiers',f'{rid}: unknown box');continue
        if sorted(ids)!=sorted(r.get('box_ids',[])):fail('coverage',f'{rid}: cached box set')
        if [e.get('zone') for e in events]!=r.get('zones'):fail('destination',f'{rid}: zone sequence')
        if any(raw[b]['zone']!=e.get('zone') for e in events for b in e['boxes']):fail('destination',f'{rid}: wrong destination')
        mass=sum(raw[b]['mass'] for b in ids);vol=sum(raw[b]['volume'] for b in ids)
        if mass>v['capacity']+1e-9 or vol>v['volume']+1e-10:fail('mass_volume',rid)
        equal('mass_volume',r.get('mass'),mass,rid+' mass',1e-8);equal('mass_volume',r.get('volume'),vol,rid+' volume',1e-10)
        if r.get('nbox')!=len(ids):fail('coverage',rid+' nbox')
        start=r.get('start')
        if not num(start) or start< -tol:fail('finite',rid+' start');continue
        prep=v['prep']+len(ids)*v['load'];t=prep;q=mass;energy=0.;here='O01';expected_segments=[];offsets={}
        for h,event in enumerate(events+[{'zone':'O01','boxes':[]}],1):
            there=event.get('zone');geo=data['geos'].get((here,there))
            if geo is None:fail('destination',f'{rid}: invalid leg {here}->{there}');break
            flight=geo['up']/v['up']+geo['distance']/v['speed']+geo['down']/v['down']
            effective_range=v['r0']-(v['r0']-v['rf'])*(max(0.,q)/v['capacity'])**1.5
            horizontal=v['battery']*geo['distance']/effective_range
            climb=(v['empty']+q)*9.81*geo['up']/(v['eta']*3600000.)
            leg=dict(**geo,**{'from':here,'to':there},load=q,horizontal=horizontal,climb=climb,energy=horizontal+climb,
                     time=flight,departure=t,arrival=t+flight)
            expected_segments.append(leg);energy+=horizontal+climb;t+=flight
            if event['boxes']:
                equal('delivery_times',event.get('arrival_offset'),t,f'{rid} event {h} arrival')
                t+=v['handoff0']+len(event['boxes'])*v['handoff1']
                equal('delivery_times',event.get('delivery_offset'),t,f'{rid} event {h} handoff')
                for b in event['boxes']:
                    offsets[b]=t;delivery[b]=start+t
                    if raw[b]['hard'] and start+t>raw[b]['deadline']+tol:fail('hard_deadlines',b)
                    row=rowmap.get(b,{})
                    for key,want in [('route_id',rid),('candidate_id',identity),('event',h),('zone',event['zone']),('uav',u),('battery_id',p)]:
                        if row.get(key)!=want:fail('identifiers',f'{b} {key}')
                    equal('delivery_times',row.get('delivery'),start+t,b+' delivery')
                    for key in ['kind','mass','volume','hard','deadline','expected','priority','first','first_deadline']:
                        if row.get(key)!=raw[b][key]:fail('identifiers',f'{b}: cached raw field {key}')
                q-=sum(raw[b]['mass'] for b in event['boxes'])
            here=there
        if abs(q)>1e-8:fail('mass_volume',rid+' nonempty return')
        latest=min((raw[b]['deadline']-offsets[b] for b in offsets if raw[b]['hard']),default=math.inf)
        cached_latest=r.get('latest_start')
        if math.isinf(latest):
            if cached_latest is not None and cached_latest!=math.inf:fail('hard_deadlines',rid+' cached latest_start')
        else:equal('hard_deadlines',cached_latest,latest,rid+' latest_start')
        if set(r.get('offsets',{}))!=set(offsets):fail('delivery_times',rid+' offsets set')
        for b,tb in offsets.items():equal('delivery_times',r.get('offsets',{}).get(b),tb,rid+' offset '+b)
        segs=r.get('segments',[])
        if len(segs)!=len(expected_segments):fail('geometry_energy',rid+' segment count')
        for cached,leg in zip(segs,expected_segments):
            for key,want in leg.items():
                if isinstance(want,str):
                    if cached.get(key)!=want:fail('geometry_energy',rid+' '+key)
                else:equal('geometry_energy',cached.get(key),want,rid+' '+key,ENERGY_TOL if key in ('energy','climb','horizontal') else tol)
        soc=1-energy/v['battery']
        recharge_time=(v['tfull']*(.65*(.9-soc)/.9+.35) if soc<.9 else v['tfull']*.35*(1-soc)/.1)
        finish=start+t;ready=finish+recharge_time
        if soc<v['rho']-1e-9:fail('soc',rid)
        equal('soc',r.get('soc'),soc,rid+' soc',1e-9)
        for key,want in [('prep_s',prep),('duration',t),('takeoff',start+prep),('finish',finish),('recharge',ready),('charge_s',recharge_time)]:
            equal('resource_times',r.get(key),want,rid+' '+key)
        equal('geometry_energy',r.get('energy'),energy,rid+' total energy',ENERGY_TOL)
        u_inter[u].append((start,finish,rid));p_inter[p].append((start,ready,rid))
        rebuilt.append(dict(route_id=rid,energy=energy,duration=t,finish=finish,recharge=ready,soc=soc))
    if Counter(visited)!=Counter(raw.keys()):fail('coverage','event boxes are not exact cover')
    for label,intervals in [('uav_nonoverlap',u_inter),('battery_nonoverlap',p_inter)]:
        for rid,iv in intervals.items():
            iv=sorted(iv)
            for a,b in zip(iv,iv[1:]):
                if a[1]>b[0]+tol:fail(label,f'{rid}: {a[2]} overlaps {b[2]}')
    checks['full_charge_reuse']=checks['battery_nonoverlap'] and checks['resource_times'] and checks['identifiers']
    soft=[b for b in raw if not raw[b]['hard']];den=sum(raw[b]['priority'] for b in soft) or 1.
    obj=[len(rebuilt),sum(r['energy'] for r in rebuilt),max((r['finish'] for r in rebuilt),default=0.),
         sum(raw[b]['priority']*max(0.,delivery.get(b,0)-raw[b]['expected']) for b in soft)/den]
    if len(plan.get('objective',[]))!=4:fail('objective','missing vector')
    else:
        for j in range(4):equal('objective',plan['objective'][j],obj[j],f'F{j}',[0,ENERGY_TOL,tol,tol][j])
    checks['all']=all(checks.values()) and not errors
    return checks,errors,dict(objective=obj,routes=rebuilt,delivery=delivery)
