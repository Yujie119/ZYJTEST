"""Exact inner resource scheduling and route-master MILPs for Question 2."""
from __future__ import annotations
import itertools, math, warnings
from copy import deepcopy
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from q2_data import decode, make_route

OBJ_TOL=np.array([0.,1e-7,1e-5,1e-7])

def dominates(a,b):
    a,b=np.asarray(a,float),np.asarray(b,float)
    return bool(np.all(a <= b + OBJ_TOL) and np.any(a < b - OBJ_TOL))

def archive_add(archive,plan):
    f=np.asarray(plan['objective'],float)
    if any(dominates(p['objective'],f) for p in archive): return False
    archive[:]=[p for p in archive if not dominates(f,p['objective'])]
    if any(np.all(np.abs(f-np.asarray(p['objective']))<=OBJ_TOL) for p in archive): return False
    archive.append(deepcopy(plan)); return True

def _solve(c,integ,bounds,A,lo,hi,seconds=10.,seed=202600):
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='Unrecognized options detected')
        return milp(np.asarray(c,float),integrality=np.asarray(integ,int),bounds=bounds,
            constraints=LinearConstraint(A,np.asarray(lo,float),np.asarray(hi,float)),
            options={'time_limit':float(seconds),'mip_rel_gap':0.,'mip_feasibility_tolerance':1e-8,
                     'primal_feasibility_tolerance':1e-8,'dual_feasibility_tolerance':1e-8,
                     'random_seed':int(seed)})

def _rows_to_matrix(rows,n):
    mat=lil_matrix((len(rows),n),dtype=float);lo=[];hi=[]
    for i,(co,l,h) in enumerate(rows):
        for j,v in co.items():
            if v: mat[i,j]=v
        lo.append(l);hi.append(h)
    return mat.tocsc(),lo,hi

class RouteMaster:
    """Exact box-covering MILP over a finite exact-box route library."""
    def __init__(self,data,routes):
        self.data=data;self.routes=list(routes);self.boxes=list(data['boxes'])
        self.inc={b:[i for i,r in enumerate(self.routes) if b in r['box_ids']] for b in self.boxes}
        missing=[b for b,v in self.inc.items() if not v]
        if missing: raise ValueError('uncovered boxes: '+repr(missing))
    def solve(self,w=(.25,)*4,capN=None,capE=None,seconds=8.,seed=202600,noise=0.):
        n=len(self.routes);rows=[]
        for b in self.boxes: rows.append(({i:1. for i in self.inc[b]},1,1))
        if capN is not None: rows.append(({i:1. for i in range(n)},-np.inf,float(capN)))
        if capE is not None: rows.append(({i:r['energy'] for i,r in enumerate(self.routes)},-np.inf,float(capE)))
        e_scale=max(1.,sum(r['energy'] for r in self.routes)/max(1,n));t_scale=max(1.,max(r['duration'] for r in self.routes))
        c=np.array([w[0]+w[1]*r['energy']/e_scale+w[2]*r['duration']/t_scale+
                    w[3]*max(0.,-r['latest_start'])/10800. + noise*((i*7919)%101)/100.
                    for i,r in enumerate(self.routes)])
        A,lo,hi=_rows_to_matrix(rows,n)
        res=_solve(c,np.ones(n),Bounds(np.zeros(n),np.ones(n)),A,lo,hi,seconds,seed)
        meta=dict(stage='route_master',status=int(res.status),message=str(res.message),has_incumbent=res.x is not None,
                  success=bool(res.success),objective=float(res.fun) if res.fun is not None else None,
                  lower_bound=float(res.mip_dual_bound) if res.mip_dual_bound is not None and np.isfinite(res.mip_dual_bound) else None,
                  mip_gap=float(res.mip_gap) if res.mip_gap is not None and np.isfinite(res.mip_gap) else None,
                  nodes=int(res.mip_node_count or 0),capN=capN,capE=capE,seed=seed,candidates=n)
        if res.x is None: return None,meta
        x=np.rint(res.x).astype(int);cov=np.asarray(A[:len(self.boxes)]@x).ravel()
        if np.max(np.abs(cov-1))>1e-7:
            meta['accepted']=False;meta['reject']='cover_residual';return None,meta
        if capN is not None and x.sum()>capN+1e-7: meta['accepted']=False;meta['reject']='N_cap';return None,meta
        if capE is not None and sum(self.routes[i]['energy']*x[i] for i in range(n))>capE+1e-6: meta['accepted']=False;meta['reject']='E_cap';return None,meta
        selected=[deepcopy(self.routes[i]) for i,v in enumerate(x) if v]
        meta['accepted']=True;meta['selected_routes']=len(selected);return selected,meta

class FixedSchedule:
    """Exact scheduling MILP for a fixed exact-box route set."""
    def __init__(self,data,routes):
        self.data=data;self.routes=[]
        for original in routes:
            r=deepcopy(original)
            if r.get('latest_start') is None or r.get('offsets') is None:
                rebuilt=make_route(data,r['vehicle'],r['events'])
                if rebuilt is None: raise ValueError('route cannot be rebuilt from raw events')
                for key,val in rebuilt.items():
                    if key not in ('start','uav','battery_id','finish','recharge'): r[key]=val
            self.routes.append(r)
        self.n=len(self.routes)
        ids=[b for r in self.routes for b in r['box_ids']]
        if len(ids)!=len(set(ids)) or set(ids)!=set(data['boxes']): raise ValueError('route set is not exact cover')
        self.bybox={b:i for i,r in enumerate(self.routes) for b in r['box_ids']}
        self.uavs_by_g={g:[u for u,t in data['uavs'].items() if t==g] for g in data['vehicles']}
        self.bats_by_g={g:[b for b,t in data['batteries'].items() if t==g] for g in data['vehicles']}
        self.H=max(60000.,sum(r['duration']+r['charge_s'] for r in self.routes)+max(r['duration'] for r in self.routes)+max((r['latest_start'] for r in self.routes if math.isfinite(r['latest_start'])),default=0.))
        self._build()
    def _build(self):
        lb=[];ub=[];integ=[];names=[];rows=[];lo=[];hi=[]
        self.s={};self.u={};self.p={};self.yu={};self.yp={};self.l={}
        def var(name,a,b,z=0):
            k=len(lb);lb.append(float(a));ub.append(float(b));integ.append(int(z));names.append(name);return k
        def add(co,a=-np.inf,b=np.inf,**kw):
            if 'low' in kw: a=kw['low']
            if 'high' in kw: b=kw['high']
            rows.append(co);lo.append(a);hi.append(b)
        for i,r in enumerate(self.routes):
            up=min(self.H-r['duration'],r['latest_start'] if math.isfinite(r['latest_start']) else self.H-r['duration'])
            if up < -1e-7: raise ValueError('route has negative hard-start window')
            self.s[i]=var(('s',i),0,max(0.,up))
        self.C=var(('Cmax',),0,self.H)
        for i,r in enumerate(self.routes): add({self.C:1,self.s[i]:-1},low=r['duration'])
        for i,r in enumerate(self.routes):
            g=r['vehicle']
            for d in self.uavs_by_g[g]: self.u[i,d]=var(('u',i,d),0,1,1)
            for p in self.bats_by_g[g]: self.p[i,p]=var(('p',i,p),0,1,1)
            add({k:1 for (ii,_),k in self.u.items() if ii==i},1,1)
            add({k:1 for (ii,_),k in self.p.items() if ii==i},1,1)
        soft=[b for b,v in self.data['boxes'].items() if not v['hard']];self.den=sum(self.data['boxes'][b]['priority'] for b in soft) or 1.
        for b in soft:
            self.l[b]=var(('late',b),0,max(0.,self.H-self.data['boxes'][b]['expected']))
            i=self.bybox[b];add({self.l[b]:1,self.s[i]:-1},low=self.routes[i]['offsets'][b]-self.data['boxes'][b]['expected'])
        for b,v in self.data['boxes'].items():
            if v['hard']:
                i=self.bybox[b];add({self.s[i]:1},high=v['deadline']-self.routes[i]['offsets'][b])
        M=self.H+max(r['duration']+r['charge_s'] for r in self.routes)+1000.
        for i,j in itertools.combinations(range(self.n),2):
            if self.routes[i]['vehicle']!=self.routes[j]['vehicle']: continue
            g=self.routes[i]['vehicle']
            for d in self.uavs_by_g[g]:
                a=var(('yu',i,j,d),0,1,1);b=var(('yu',j,i,d),0,1,1);self.yu[i,j,d]=a;self.yu[j,i,d]=b
                ui,uj=self.u[i,d],self.u[j,d]
                add({a:1,b:1,ui:-1,uj:-1},low=-1);add({a:1,b:1,ui:-1},high=0);add({a:1,b:1,uj:-1},high=0)
                add({self.s[j]:1,self.s[i]:-1,a:-M},low=self.routes[i]['duration']-M)
                add({self.s[i]:1,self.s[j]:-1,b:-M},low=self.routes[j]['duration']-M)
            for p in self.bats_by_g[g]:
                a=var(('yp',i,j,p),0,1,1);b=var(('yp',j,i,p),0,1,1);self.yp[i,j,p]=a;self.yp[j,i,p]=b
                pi,pj=self.p[i,p],self.p[j,p]
                add({a:1,b:1,pi:-1,pj:-1},low=-1);add({a:1,b:1,pi:-1},high=0);add({a:1,b:1,pj:-1},high=0)
                add({self.s[j]:1,self.s[i]:-1,a:-M},low=self.routes[i]['duration']+self.routes[i]['charge_s']-M)
                add({self.s[i]:1,self.s[j]:-1,b:-M},low=self.routes[j]['duration']+self.routes[j]['charge_s']-M)
        self.lb,self.ub,self.integ,self.names=lb,ub,integ,names;self.rows,self.lo,self.hi=rows,lo,hi
        self.A,self.lo,self.hi=_rows_to_matrix(list(zip(rows,lo,hi)),len(lb))
    def _solve_stage(self,stage,capC=None,capL=None,seconds=10.,seed=202600,relax=False):
        c=np.zeros(len(self.lb))
        if stage=='C': c[self.C]=1.
        elif stage=='L':
            for b,k in self.l.items(): c[k]=self.data['boxes'][b]['priority']/self.den
        rows=list(zip(self.rows,self.lo,self.hi))
        if capC is not None: rows.append(({self.C:1},-np.inf,float(capC)))
        if capL is not None: rows.append(({k:self.data['boxes'][b]['priority']/self.den for b,k in self.l.items()},-np.inf,float(capL)))
        A,lo2,hi2=_rows_to_matrix(rows,len(self.lb))
        integ=[0]*len(self.integ) if relax else self.integ
        res=_solve(c,integ,Bounds(np.asarray(self.lb),np.asarray(self.ub)),A,lo2,hi2,seconds,seed)
        meta=dict(stage=stage,status=int(res.status),message=str(res.message),has_incumbent=res.x is not None,success=bool(res.success),optimal=bool(res.success and res.status==0),
                  objective=float(res.fun) if res.fun is not None and np.isfinite(res.fun) else None,
                  lower_bound=(float(res.fun) if relax and res.fun is not None and np.isfinite(res.fun) else (float(res.mip_dual_bound) if res.mip_dual_bound is not None and np.isfinite(res.mip_dual_bound) else None)),
                  mip_gap=float(res.mip_gap) if res.mip_gap is not None and np.isfinite(res.mip_gap) else None,nodes=int(res.mip_node_count or 0),capC=capC,capL=capL,variables=len(self.lb),constraints=len(rows),horizon=self.H,seed=seed)
        if res.x is None:return None,meta
        x=np.asarray(res.x,float);ix=np.flatnonzero(integ);residual=max(0.,float(np.max(self.lb-x)),float(np.max(x-np.asarray(self.ub))),float(np.max(np.asarray(lo2)-A@x)),float(np.max(A@x-np.asarray(hi2))))
        integer_error=float(np.max(np.abs(x[ix]-np.rint(x[ix])))) if len(ix) else 0.
        meta['matrix_residual']=residual;meta['integer_error']=integer_error
        if relax: meta['relaxation']=True
        if residual>2e-5 or (not relax and integer_error>2e-5):meta['accepted']=False;meta['reject']='solver_incumbent_residual';return None,meta
        meta['accepted']=True;out=[]
        for i,r in enumerate(self.routes):
            u=max(self.uavs_by_g[r['vehicle']],key=lambda d:x[self.u[i,d]])
            p=max(self.bats_by_g[r['vehicle']],key=lambda z:x[self.p[i,z]])
            out.append(dict(deepcopy(r),start=max(0.,float(x[self.s[i]])),uav=u,battery_id=p))
        plan=decode(self.data,out);plan['schedule_meta']=meta;return plan,meta

    def continuous_bound(self,stage='C',seconds=5.,seed=202600,capC=None,capL=None):
        """LP relaxation bound for the same fixed-route scheduling model."""
        return self._solve_stage(stage,capC=capC,capL=capL,seconds=seconds,seed=seed,relax=True)
    def solve_lex(self,seconds=10.,seed=202600,capC=None,capL=None):
        p1,m1=self._solve_stage('C',capC=capC,capL=capL,seconds=seconds,seed=seed)
        if p1 is None:return None,[m1]
        cstar=p1['objective'][2];p2,m2=self._solve_stage('L',capC=min(cstar,capC) if capC is not None else cstar,capL=capL,seconds=seconds,seed=seed+1)
        if p2 is None:return p1,[m1,m2]
        p2['schedule_meta']={'stages':[m1,m2],'lex_certified':m1['optimal'] and m2['optimal']};return p2,[m1,m2]

def preference_vertices(center=(.25,)*4,delta=.3):
    center=np.asarray(center,float);n=len(center)
    if abs(center.sum()-1)>1e-10 or np.any(center<0):raise ValueError('invalid center')
    if delta==0:return center[None,:]
    out=[center.copy()];amount=delta/2.
    for i,j in itertools.permutations(range(n),2):
        w=center.copy();w[i]+=amount;w[j]-=amount
        if np.min(w)>=-1e-12:out.append(w)
    unique=[]
    for w in out:
        w[np.abs(w)<1e-12]=0
        if not any(np.allclose(w,q,rtol=0,atol=1e-12) for q in unique):unique.append(w)
    return np.asarray(unique)
