"""Exact-box candidates; search restrictions are exported, never physical rules."""
from collections import Counter,defaultdict
import itertools,random,math
from q2_data import make_route,decode

def single_point_catalog(data):
    """Enumerate every labelled subset at every zone and all types, no dominance."""
    byzone=defaultdict(list);stats=Counter();routes=[]
    for b,v in data['boxes'].items():byzone[v['zone']].append(b)
    for z,ids in byzone.items():
        for n in range(1,len(ids)+1):
            for subset in itertools.combinations(ids,n):
                for g in data['vehicles']:
                    r=make_route(data,g,[dict(zone=z,boxes=list(subset))],stats)
                    if r:routes.append(r)
    return routes,stats

def global_pool(data,catalog,base,seed=202600,per_zone_type=6,multipoint_budget=140):
    """Disclosed working pool K0: base + singletons + per-type diverse subsets.

    All decisions are free in the direct global joint MILP on K0. K0 is not
    confused with the exhaustive single-point catalog or all multi-point routes.
    """
    rng=random.Random(seed);pool={r['candidate_id']:r for r in base['routes']};group=defaultdict(list)
    for r in catalog:
        group[r['zones'][0],r['vehicle']].append(r)
        if r['nbox']==1:pool[r['candidate_id']]=r
    for (z,g),rs in group.items():
        orders=[sorted(rs,key=lambda r:(r['energy']/r['nbox'],-r['nbox'],r['candidate_id'])),
                sorted(rs,key=lambda r:(-sum(data['boxes'][b]['hard'] for b in r['box_ids']),r['energy'],r['candidate_id']))]
        chosen={}
        for rank in range(per_zone_type):
            for order in orders:chosen[order[min(rank,len(order)-1)]['candidate_id']]=order[min(rank,len(order)-1)]
        for r in chosen.values():pool[r['candidate_id']]=r
    # Legacy boxes and every type substitution, without applying Q1 dominance.
    for old in base['routes']:
        for g in data['vehicles']:
            r=make_route(data,g,old['events'])
            if r:pool[r['candidate_id']]=r
    # Explicit all disjoint pairings: 8 WAT boxes can execute 2-box patterns 4x.
    water=sorted(b for b,v in data['boxes'].items() if v['zone']=='S001' and v['kind']=='饮用水')
    for a,b in zip(water[::2],water[1::2]):
        for g in data['vehicles']:
            r=make_route(data,g,[dict(zone='S001',boxes=[a,b])])
            if r:pool[r['candidate_id']]=r
    stats=Counter();multi={};zones=sorted({v['zone'] for v in data['boxes'].values()})
    medical={z:[b for b,v in data['boxes'].items() if v['zone']==z and v['kind']=='医疗物资'] for z in zones}
    # Grow complete visit lists and test only complete physical routes. There is
    # no three-station data-structure limit, and repeated nonadjacent visits work.
    for attempt in range(multipoint_budget*12):
        n=rng.choice([2,3,4,5]);order=rng.sample(zones,n);g=rng.choice(list(data['vehicles']))
        ev=[dict(zone=z,boxes=[rng.choice(medical[z])]) for z in order]
        r=make_route(data,g,ev,stats)
        if r:multi[r['candidate_id']]=r
        if len(multi)>=multipoint_budget:break
    ev=[dict(zone=z,boxes=[medical[z][0]]) for z in ['S006','S011','S001','S013']]
    r=make_route(data,'B',ev,stats)
    if r:multi[r['candidate_id']]=r
    # Ordinary two-zone mixes complement the medical-only long routes.
    for attempt in range(100):
        za,zb=rng.sample(zones,2);g=rng.choice(list(data['vehicles']))
        a=group.get((za,g),[]);b=group.get((zb,g),[])
        if not a or not b:continue
        ra=rng.choice(a);rb=rng.choice(b)
        r=make_route(data,g,ra['events']+rb['events'],stats)
        if r:multi[r['candidate_id']]=r
    pool.update(multi)
    # Strip all previous execution times; only candidate attributes are inherited.
    for r in list(pool.values()):
        rebuilt=make_route(data,r['vehicle'],r['events'])
        if rebuilt:pool[r['candidate_id']]=rebuilt
    return list(pool.values()),dict(multiroute_generation=stats,count=len(pool),type_count=Counter(r['vehicle'] for r in pool.values()),
        visit_count=Counter(len(r['events']) for r in pool.values()),seed=seed,per_zone_type=per_zone_type,
        note='K0 is a finite working library, not the full original feasible route set.')

def construct_initial(data,pool,seed=202600,mode=0):
    """Feasible initializer only; its scores never replace a solver objective."""
    rng=random.Random(seed);remaining=set(data['boxes']);ua={u:0. for u in data['uavs']};ba={p:0. for p in data['batteries']};out=[]
    sets={r['candidate_id']:set(r['box_ids']) for r in pool}
    while remaining:
        # Assign RNG draws in a canonical order, independent of PYTHONHASHSEED.
        hard=[b for b in sorted(remaining) if data['boxes'][b]['hard']]
        if hard:
            target=min(hard,key=lambda b:(data['boxes'][b]['deadline'],rng.random()))
        else:target=min(sorted(remaining),key=lambda b:(data['boxes'][b]['expected']/data['boxes'][b]['priority'],rng.random()))
        choices=[]
        for r in pool:
            if target not in sets[r['candidate_id']] or not sets[r['candidate_id']]<=remaining:continue
            g=r['vehicle'];u=min((u for u,t in data['uavs'].items() if t==g),key=ua.get);p=min((p for p,t in data['batteries'].items() if t==g),key=ba.get)
            s=max(ua[u],ba[p])
            if s>(r['latest_start'] if r['latest_start'] is not None else math.inf)+1e-7:continue
            n=r['nbox'];nh=sum(data['boxes'][b]['hard'] for b in r['box_ids'])
            # Explore different load preferences to provide diverse feasible MIP starts.
            value=(s+r['duration'])/(n**[.0,.35,.65,1.][mode%4])
            value*=1+rng.uniform(-.1,.1)
            choices.append((value,r,s,u,p))
        if not choices:return None
        _,r,s,u,p=min(choices,key=lambda x:x[0]);out.append(dict(r,start=s,uav=u,battery_id=p));remaining-=sets[r['candidate_id']]
        ua[u]=s+r['duration'];ba[p]=ua[u]+r['charge_s']
    plan=decode(data,out)
    plan.update(source=f'initializer_seed_{seed}_mode_{mode}',initialization_seed=seed,initialization_mode=mode)
    return plan
