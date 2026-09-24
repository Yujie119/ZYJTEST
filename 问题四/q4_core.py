"""Exact rational partition evaluation for fixed Q3 task events."""
from pathlib import Path
from fractions import Fraction as F
from collections import defaultdict
import csv
import hashlib
import json
from functools import lru_cache

R = ('U_A','U_B','U_C','P_A','P_B','P_C','U_R','P_R')
ROOT = Path(__file__).resolve().parent

def frac(x): return F(str(x))
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def clean(x):
    if isinstance(x,F): return float(x)
    if isinstance(x,Path): return str(x)
    if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(tuple,list,set)): return [clean(v) for v in x]
    return x
def save(p,x):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    Path(p).write_text(json.dumps(clean(x),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def csvout(p,rows):
    if not rows:return
    with Path(p).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader()
        w.writerows({k:(json.dumps(clean(v),ensure_ascii=False) if isinstance(v,(dict,list,tuple)) else clean(v)) for k,v in row.items()} for row in rows)

class UF:
    def __init__(self,items):self.p={i:i for i in items}
    def find(self,x):
        if self.p[x]!=x:self.p[x]=self.find(self.p[x])
        return self.p[x]
    def join(self,items):
        items=sorted(items)
        for x in items[1:]:self.p[self.find(x)]=self.find(items[0])
    def groups(self):
        out=defaultdict(list)
        for x in self.p:out[self.find(x)].append(x)
        return sorted([sorted(g) for g in out.values()],key=lambda g:g[0])

@lru_cache(maxsize=1)
def raw_parameters():
    from openpyxl import load_workbook
    base=ROOT/'输入快照/原始附件'; inventory={r:0 for r in R}; capacity={}; full={}; turn=None
    for fn,relay in [('运输无人机数据.xlsx',False),('中继无人机数据.xlsx',True)]:
        wb=load_workbook(base/fn,read_only=True,data_only=True); rows=list(wb['数据'].values);wb.close()
        block=''
        for row in rows:
            if row[0] is None:continue
            if row[0] in ['三类机型参数','中继机型参数','逐架无人机清单','逐架中继无人机清单','共享电池库存','共享能源组件库存']:
                block=row[0];continue
            if block in ['三类机型参数','中继机型参数'] and row[0] in ['A','B','C','R']:
                capacity[row[0]]=frac(row[7 if relay else 8])
                if relay:turn=frac(row[11])
            if block in ['逐架无人机清单','逐架中继无人机清单'] and row[1] in ['A','B','C','R']:
                assert row[2]=='O01'; inventory['U_'+row[1]]+=1
            if block in ['共享电池库存','共享能源组件库存'] and row[0] in ['A','B','C','R']:
                inventory['P_'+row[0]]=int(row[1]);full[row[0]]=frac(row[2])
    assert all(x>0 for x in inventory.values())
    return inventory,capacity,full,turn

def build(directory):
    directory=Path(directory);p=load(directory/'方案.json')
    for fn in ['记录.json','独立DEM核验.json','原始数据结构审计.json','通信核验.json']:
        assert load(directory/fn)['status']=='PASS',(directory,fn)
    assert load(directory/'通信核验.json')['source_sha256']==digest(directory/'方案.json')
    routes={r['route_id']:r for r in p['routes']};relays={r['relay_id']:r for r in p['relays']}
    assert len(routes)==len(p['routes']) and len(relays)==len(p['relays'])
    zones=sorted({z for r in routes.values() for z in r['zones']})
    assert zones==[f'S{i:03}' for i in range(1,16)]
    slots={r['slot']:j for j,r in relays.items()};assert len(slots)==len(relays)
    u=UF(zones);merges=[]
    for k,r in routes.items():
        u.join(r['zones']);merges.append({'type':'transport','task':k,'zones':r['zones']})
    mt=len(u.groups());relations=defaultdict(set);edge_proof=[]
    rows=load(directory/'实际通信分段.json')
    with (directory/'通信事件端点核验.csv').open(encoding='utf-8-sig',newline='') as f:points=list(csv.DictReader(f))
    for row in rows:
        assert row['route_id'] in routes
        if row['mode']=='中继':
            k,j=row['route_id'],row['relay_id']; assert j in relays
            r=relays[j];assert r['alpha']-2e-4<=row['t0']<=row['t1']<=r['beta']+2e-4
            relations[j].add(k);edge_proof.append({'kind':'interval','route':k,'relay':j,'t0':row['t0'],'t1':row['t1']})
    for point in points:
        k,j=point['route_id'],point['provider'];assert k in routes
        if j!='G01':
            assert j in relays;relations[j].add(k)
            r=relays[j];assert r['alpha']-2e-4<=float(point['time_s'])<=r['beta']+2e-4
            edge_proof.append({'kind':'endpoint','route':k,'relay':j,'t0':float(point['time_s']),'t1':float(point['time_s'])})
    assert set(relations)==set(relays),'Unassigned executed relay task'
    for j,rr in sorted(relations.items()):
        zs=sorted({z for k in rr for z in routes[k]['zones']});u.join(zs)
        merges.append({'type':'actual_relay','task':j,'routes':sorted(rr),'zones':zs})
    comps=u.groups();ci={z:i for i,c in enumerate(comps) for z in c}
    tr_comp={k:ci[r['zones'][0]] for k,r in routes.items()}
    re_comp={j:tr_comp[next(iter(rr))] for j,rr in relations.items()}
    inventory,capacity,full,turn=raw_parameters()
    events=[];workT=[F(0) for c in comps];workR=[F(0) for c in comps]
    charge_errors=[]
    for typ,objects in [('T',routes),('R',relays)]:
        for k,r in objects.items():
            g=r['vehicle'] if typ=='T' else 'R';component=tr_comp[k] if typ=='T' else re_comp[k]
            soc=1-frac(r['energy'])/capacity[g]
            assert F(1,5)-F(1,1000000)<=soc<=1
            charge=full[g]*(F(65,100)*(F(9,10)-soc)/F(9,10)+F(35,100)) if soc<F(9,10) else full[g]*F(35,100)*(1-soc)/F(1,10)
            err=abs(float(frac(r['recharge'])-frac(r['finish'])-charge));assert err<2e-4
            charge_errors.append({'task':k,'charge_error_s':err})
            start=frac(r['start']); finish=frac(r['finish'])
            assert finish>start
            (workT if typ=='T' else workR)[component]+=finish-start
            body_end=finish if typ=='T' else frac(r['body_ready'])
            if typ=='R':assert abs(float(body_end-finish-turn))<2e-4
            for resource,end,old in [('U_'+g,body_end,r['uav']),('P_'+g,frac(r['recharge']),r['battery_id'] if typ=='T' else r['component'])]:
                events.append({'task':k,'task_type':typ,'component':component,'resource_type':resource,
                               'old_resource':old,'start':start,'task_end':finish,'ready':end})
    # Exact source decimals; no rounding, jitter or task-time modifications.
    pvec={r:peak([e for e in events if e['resource_type']==r])[0] for r in R}
    assert all(pvec[r]<=inventory[r] for r in R),('central peak exceeds inventory',directory,pvec)
    return {'directory':directory,'plan':p,'routes':routes,'relays':relays,'slots':slots,
            'components':comps,'M_T':mt,'M':len(comps),'relations':{j:sorted(v) for j,v in relations.items()},
            'merge_sources':merges,'edge_proof':edge_proof,'events':events,'workT':workT,'workR':workR,
            'inventory':inventory,'P':pvec,'charge_errors':charge_errors,'source_sha256':digest(directory/'方案.json')}

def peak(events):
    times=sorted({t for e in events for t in [e['start'],e['ready']]})
    best=0;witness=[]
    for a,b in zip(times,times[1:]):
        active=sorted(e['task'] for e in events if e['start']<=a<e['ready'])
        if len(active)>best:best=len(active);witness=[]
        if active and len(active)==best:witness.append({'start':a,'end':b,'tasks':active})
    return best,witness

def partitions(n,g):
    """Restricted growth strings; every unlabeled partition occurs once."""
    def rec(i,groups):
        if i==n:
            if len(groups)==g:yield tuple(tuple(x) for x in groups)
            return
        if len(groups)+(n-i)<g:return
        for h in range(len(groups)):
            groups[h].append(i);yield from rec(i+1,groups);groups[h].pop()
        if len(groups)<g:yield from rec(i+1,groups+[[i]])
    yield from rec(0,[])

def group_data(c,units,g):
    units=tuple(units);ev=[e for e in c['events'] if e['component'] in units]
    nr={};cert={}
    for r in R:nr[r],cert[r]=peak([e for e in ev if e['resource_type']==r])
    wt=sum((c['workT'][i] for i in units),F(0));wr=sum((c['workR'][i] for i in units),F(0))
    totalT=sum(c['workT']);totalR=sum(c['workR']); bc=[]
    for w,total in [(wt,totalT),(wr,totalR)]:
        if total:bc.append(abs(w/total-F(1,g))*F(g,2*(g-1)))
    return {'units':units,'services':sorted(z for i in units for z in c['components'][i]),'resources':nr,
            'transport_work_s':wt,'relay_work_s':wr,'b':sum(bc)/len(bc),'peaks':cert}

def evaluate(c,part,cache=None):
    g=len(part);groups=[cache[tuple(u)] if cache else group_data(c,u,g) for u in part]
    d={r:sum(h['resources'][r] for h in groups) for r in R};inv=c['inventory']
    bt=F(g,2*(g-1))*sum(abs(h['transport_work_s']/sum(c['workT'])-F(1,g)) for h in groups)
    br=F(g,2*(g-1))*sum(abs(h['relay_work_s']/sum(c['workR'])-F(1,g)) for h in groups) if sum(c['workR']) else F(0)
    a=sum(F(d[r],inv[r]) for r in R)/8;b=sum(h['b'] for h in groups)
    q=a*96;assert q.denominator==1
    gaps={r:max(d[r]-inv[r],0) for r in R};stock={r:max(inv[r]-d[r],0) for r in R}
    return {'G':g,'partition':part,'partition_code':'|'.join('+'.join(str(i) for i in h) for h in part),
            'groups':groups,'D':d,'A':a,'BT':bt,'BR':br,'B':b,'Q':int(q),'gaps':gaps,'stock':stock,
            'concentrated_P':c['P'],'split_loss':{r:d[r]-c['P'][r] for r in R},
            'H_stock':sum(F(gaps[r],inv[r]) for r in R),'inventory_feasible':all(v==0 for v in gaps.values())}

def dominates(a,b):return a['A']<=b['A'] and a['B']<=b['B'] and (a['A']<b['A'] or a['B']<b['B'])
def front(rows):return [a for a in rows if not any(dominates(b,a) for b in rows)]
def select(rows,delta=F(3,10),weights=None):
    if weights is None:weights={r:F(1,8) for r in R}
    theta=(max(F(0),F(1,2)-delta/2),min(F(1),F(1,2)+delta/2))
    def aa(x):return sum(weights[r]*F(x['D'][r],raw_parameters()[0][r]) for r in R)
    # Inventory is frozen in raw_parameters; compute A once per partition.
    av={x['partition_code']:aa(x) for x in rows}
    v={t:min(t*av[x['partition_code']]+(1-t)*x['B'] for x in rows) for t in theta}
    out=[]
    for x in rows:
        y=dict(x);y['A']=av[x['partition_code']]
        y['regret_lo']=theta[0]*y['A']+(1-theta[0])*y['B']-v[theta[0]]
        y['regret_hi']=theta[1]*y['A']+(1-theta[1])*y['B']-v[theta[1]]
        y['regret_max']=max(y['regret_lo'],y['regret_hi']);out.append(y)
    nd=front(out)
    chosen=min(nd,key=lambda x:(x['regret_max'],x['H_stock'],x['B'],x['Q'],x['partition_code']))
    meta={'delta':delta,'theta_endpoints':theta,'v':{str(t):vv for t,vv in v.items()},'resource_weights':weights}
    return out,chosen,meta

def enumerate_case(c,g):
    import itertools
    cache={u:group_data(c,u,g) for k in range(1,c['M']-g+2) for u in itertools.combinations(range(c['M']),k)}
    rows=[evaluate(c,p,cache) for p in partitions(c['M'],g)]
    return rows,cache

def assignment(c,chosen):
    """Construct a coloring witness; identities are group-exclusive."""
    output=[];checks=[]
    for h,group in enumerate(chosen['groups'],1):
        gid=f"G{chosen['G']}-{h:02}"
        for r in R:
            tasks=sorted([e for e in c['events'] if e['resource_type']==r and e['component'] in group['units']],key=lambda e:(e['start'],e['task']))
            ready={}
            for e in tasks:
                available=[i for i,t in ready.items() if t<=e['start']]
                identity=min(available) if available else len(ready)+1
                ready[identity]=e['ready']
                output.append({'G':chosen['G'],'group':gid,'resource_type':r,'new_resource':f'{gid}-{r}-{identity:02}',
                               **{k:e[k] for k in ['task','task_type','old_resource','start','task_end','ready']}})
            assert len(ready)==group['resources'][r]
            checks.append({'G':chosen['G'],'group':gid,'resource_type':r,'minimum_count':len(ready),
                           'peak_intervals':group['peaks'][r]})
    return output,checks
