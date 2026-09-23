"""Paper (5-10)--(5-18): per-box joint selection and continuous resource MILP.

No route proxy objective. All four objective vectors use the same constraints.
SciPy's bundled HiGHS 1.8 API supplies checked MIP starts, without installations.
"""
from __future__ import annotations
import itertools, math, time
from copy import deepcopy
import numpy as np
from scipy.sparse import coo_matrix
from scipy.optimize._highspy import _core as hc
from q2_data import decode, make_route

OBJ_TOL=np.array([0.,1e-7,1e-5,1e-7])
MAT_TOL=2e-5

def dominates(a,b):
    a,b=np.asarray(a,float),np.asarray(b,float)
    return bool(np.all(a<=b+OBJ_TOL) and np.any(a<b-OBJ_TOL))

def archive_add(archive,plan):
    f=np.asarray(plan['objective'])
    if any(dominates(p['objective'],f) for p in archive):return False
    archive[:]=[p for p in archive if not dominates(f,p['objective'])]
    if any(np.all(np.abs(f-np.asarray(p['objective']))<=OBJ_TOL) for p in archive):return False
    archive.append(deepcopy(plan));return True

def vertices(center=(.25,)*4,delta=.3):
    center=np.asarray(center,float);n=len(center)
    if abs(center.sum()-1)>1e-10 or min(center)<0 or delta<0:raise ValueError('preference set')
    if delta==0:return center[None,:]
    A=[-np.eye(n)[i] for i in range(n)];b=[0.]*n
    for v in itertools.product((-1.,1.),repeat=n):
        s=np.array(v);A.append(s);b.append(delta+s@center)
    A,b=np.asarray(A),np.asarray(b);out=[]
    for indices in itertools.combinations(range(len(A)),n-1):
        eq=np.vstack([np.ones(n),A[list(indices)]]);rhs=np.r_[1.,b[list(indices)]]
        if np.linalg.matrix_rank(eq)<n:continue
        w=np.linalg.solve(eq,rhs)
        if np.all(A@w<=b+1e-10) and not any(np.allclose(w,x,rtol=0,atol=1e-10) for x in out):
            w[np.abs(w)<1e-12]=0.;out.append(w)
    return np.array(sorted(out,key=tuple))

class JointModel:
    def __init__(self,data,candidates,*,fixed=None,mandatory=False,fixed_resources=False,warm=None,cap=None,scope='local'):
        self.data=data;self.rs=list({r['candidate_id']:r for r in candidates}.values())
        self.fixed=fixed or {};self.cap=cap or {};self.scope=scope
        self.lb=[];self.ub=[];self.ints=[];self.names=[];self.rows=[];self.low=[];self.high=[]
        self.x={};self.s={};self.u={};self.p={};self.z={};self.c={};self.l={}
        self.index={r['candidate_id']:i for i,r in enumerate(self.rs)}
        nbox=len(data['boxes']);v=data['vehicles']
        # Each selected route contains a distinct box, hence at most nbox routes.
        # Every positive resource-order path has <=nbox vertices. Its edge lengths
        # are bounded by duration+charge. Fixed absolute intervals are included.
        durations=sorted((r['duration']+r['charge_s'] for r in self.rs),reverse=True)
        H=sum(durations[:nbox])+max((r['start'] for r in self.fixed.values()),default=0.)
        if 'C' in self.cap:H=min(H,float(self.cap['C']))
        self.H=H
        warm_by={r['candidate_id']:r for r in warm['routes']} if warm else {}
        for i,r in enumerate(self.rs):
            if r['latest_start'] is None:r['latest_start']=math.inf
            rid=r['candidate_id'];isfixed=rid in self.fixed
            self.x[i]=self.var(('x',i),1 if mandatory or isfixed else 0,1,True)
            upper=min(H-r['duration'],r['latest_start'])
            if upper<0:
                if mandatory or isfixed:raise ValueError('mandatory route outside horizon')
                self.ub[self.x[i]]=0
            self.s[i]=self.var(('s',i),0,max(0.,upper))
            self.add({self.s[i]:1,self.x[i]:-max(0.,upper)},high=0)
            if isfixed:self.lb[self.s[i]]=self.ub[self.s[i]]=self.fixed[rid]['start']
            g=r['vehicle']
            for d,typ in data['uavs'].items():
                if typ!=g:continue
                k=self.var(('u',i,d),0,1,True);self.u[i,d]=k
                if isfixed or fixed_resources:
                    src=self.fixed[rid] if isfixed else warm_by[rid]
                    self.lb[k]=self.ub[k]=int(src['uav']==d)
            for p,typ in data['batteries'].items():
                if typ!=g:continue
                k=self.var(('p',i,p),0,1,True);self.p[i,p]=k
                if isfixed or fixed_resources:
                    src=self.fixed[rid] if isfixed else warm_by[rid]
                    self.lb[k]=self.ub[k]=int(src['battery_id']==p)
            for dic in (self.u,self.p):
                co={k:1 for (ii,_),k in dic.items() if ii==i};co[self.x[i]]=-1;self.add(co,0,0)
        self.cm=self.var(('C',),0,H)
        for i,r in enumerate(self.rs):self.add({self.cm:1,self.s[i]:-1,self.x[i]:-r['duration']},low=0)
        cover={b:[] for b in data['boxes']}
        for i,r in enumerate(self.rs):
            for b in r['box_ids']:cover[b].append(i)
        for b,raw in data['boxes'].items():
            cand=cover[b]
            if not cand:raise ValueError(f'uncovered {b}')
            self.add({self.x[i]:1 for i in cand},1,1)
            self.c[b]=self.var(('c',b),0,min(H,raw['deadline']) if raw['hard'] else H)
            co={self.c[b]:1}
            for i in cand:co[self.s[i]]=-1;co[self.x[i]]=-self.rs[i]['offsets'][b]
            self.add(co,0,0)
            if not raw['hard']:
                self.l[b]=self.var(('l',b),0,max(0,H-raw['expected']))
                self.add({self.l[b]:1,self.c[b]:-1},low=-raw['expected'])
        # A common order bit is equivalent to the paper's per-resource y:
        # if two tasks share both resources, positive durations force the same
        # order. No bit/constraints are needed for mutually exclusive box sets.
        memberships=[set(r['box_ids']) for r in self.rs]
        resource_by_g={g:([d for d,t in data['uavs'].items() if t==g],[d for d,t in data['batteries'].items() if t==g]) for g in data['vehicles']}
        for i,j in itertools.combinations(range(len(self.rs)),2):
            ri,rj=self.rs[i],self.rs[j]
            if ri['vehicle']!=rj['vehicle'] or memberships[i]&memberships[j]:continue
            if ri['candidate_id'] in self.fixed and rj['candidate_id'] in self.fixed:continue
            z=self.var(('z',i,j),0,1,True);self.z[i,j]=z
            for dic,extra,resources in ((self.u,False,resource_by_g[ri['vehicle']][0]),(self.p,True,resource_by_g[ri['vehicle']][1])):
                for d in resources:
                    vi=dic[i,d]
                    vj=dic[j,d]
                    if self.ub[vi]==0 or self.ub[vj]==0:continue
                    ti=ri['duration']+(ri['charge_s'] if extra else 0)
                    tj=rj['duration']+(rj['charge_s'] if extra else 0)
                    mi=self.ub[self.s[i]]+ti;mj=self.ub[self.s[j]]+tj
                    self.add({self.s[j]:1,self.s[i]:-1,self.x[i]:-ti,vi:-mi,vj:-mi,z:-mi},low=-3*mi)
                    self.add({self.s[i]:1,self.s[j]:-1,self.x[j]:-tj,vi:-mj,vj:-mj,z:mj},low=-2*mj)
        for g in data['vehicles']:
            co={self.x[i]:r['duration'] for i,r in enumerate(self.rs) if r['vehicle']==g}
            co[self.cm]=-sum(t==g for t in data['uavs'].values());self.add(co,high=0)
        den=sum(b['priority'] for b in data['boxes'].values() if not b['hard']) or 1.
        self.f=[{k:1. for k in self.x.values()},{self.x[i]:r['energy'] for i,r in enumerate(self.rs)},
                {self.cm:1.},{k:data['boxes'][b]['priority']/den for b,k in self.l.items()}]
        for label,j in [('N',0),('E',1),('C',2),('L',3)]:
            if label in self.cap:self.add(self.f[j],high=float(self.cap[label]))
        self.compile();self.warm=self.encode(warm) if warm else None

    def var(self,name,lo,hi,integer=False):
        k=len(self.lb);self.names.append(name);self.lb.append(float(lo));self.ub.append(float(hi));self.ints.append(int(integer));return k
    def add(self,co,low=-math.inf,high=math.inf):self.rows.append(co);self.low.append(low);self.high.append(high)
    def compile(self):
        rr=[];cc=[];vv=[]
        for i,row in enumerate(self.rows):
            for k,v in row.items():
                if v:rr.append(i);cc.append(k);vv.append(v)
        self.A=coo_matrix((vv,(rr,cc)),shape=(len(self.rows),len(self.lb))).tocsc()
    def coeff(self,weights):
        cost=np.zeros(len(self.lb))
        for w,f in zip(weights,self.f):
            for k,v in f.items():cost[k]+=w*v
        return cost
    def residual(self,x,integer=True):
        if x is None or len(x)!=len(self.lb) or not np.isfinite(x).all():return math.inf
        ax=self.A@x
        err=max(float(np.max(np.asarray(self.lb)-x)),float(np.max(x-np.asarray(self.ub))),float(np.max(np.asarray(self.low)-ax)),float(np.max(ax-np.asarray(self.high))),0.)
        ix=np.flatnonzero(self.ints)
        if integer and len(ix):err=max(err,float(np.max(abs(x[ix]-np.rint(x[ix])))))
        return err
    def feasible(self,x,integer=True):return self.residual(x,integer)<=MAT_TOL
    def encode(self,plan):
        if plan is None or any(r['candidate_id'] not in self.index for r in plan['routes']):return None
        x=np.zeros(len(self.lb));chosen={}
        for r in plan['routes']:
            i=self.index[r['candidate_id']];chosen[i]=r;x[self.x[i]]=1;x[self.s[i]]=r['start']
            x[self.u[i,r['uav']]]=1;x[self.p[i,r['battery_id']]]=1
        for (i,j),k in self.z.items():x[k]=int(i in chosen and j in chosen and chosen[i]['start']<=chosen[j]['start'])
        for b in plan['boxes']:
            x[self.c[b['box']]]=b['delivery']
            if b['box'] in self.l:x[self.l[b['box']]]=max(0,b['delivery']-self.data['boxes'][b['box']]['expected'])
        x[self.cm]=plan['objective'][2]
        return x if self.feasible(x) else None
    def unpack(self,x):
        out=[]
        for i,r in enumerate(self.rs):
            if x[self.x[i]]<.5:continue
            u=next(d for (ii,d),k in self.u.items() if ii==i and x[k]>.5)
            p=next(d for (ii,d),k in self.p.items() if ii==i and x[k]>.5)
            q=deepcopy(r);q.pop('route_id',None);q.update(start=max(0.,float(x[self.s[i]])),uav=u,battery_id=p);out.append(q)
        # Compress the selected two-resource order DAG; earlier starts never
        # worsen deadlines or objectives. Preserve frozen external task times.
        out.sort(key=lambda r:(r['start'],r['candidate_id']))
        ua={u:0. for u in self.data['uavs']};ba={p:0. for p in self.data['batteries']}
        for r in out:
            earliest=max(ua[r['uav']],ba[r['battery_id']])
            if r['candidate_id'] in self.fixed:
                if earliest>r['start']+MAT_TOL:raise ValueError('frozen task conflict')
            else:r['start']=earliest
            ua[r['uav']]=r['start']+r['duration'];ba[r['battery_id']]=ua[r['uav']]+r['charge_s']
        return decode(self.data,out)
    def solve(self,weights,seconds=3.,seed=202600,relax=False):
        t=time.perf_counter();cost=self.coeff(weights);h=hc._Highs()
        for name,value in [('output_flag',False),('threads',1),('time_limit',float(seconds)),('mip_rel_gap',0.),
                           ('mip_abs_gap',1e-8),('mip_feasibility_tolerance',1e-8),('primal_feasibility_tolerance',1e-8),('random_seed',int(seed))]:
            if h.setOptionValue(name,value)!=hc.HighsStatus.kOk:raise RuntimeError(f'option {name}')
        lp=hc.HighsLp();lp.num_col_=len(self.lb);lp.num_row_=len(self.rows);lp.col_cost_=cost
        lp.col_lower_=np.asarray(self.lb);lp.col_upper_=np.asarray(self.ub);lp.row_lower_=np.asarray(self.low);lp.row_upper_=np.asarray(self.high)
        lp.a_matrix_.num_col_=len(self.lb);lp.a_matrix_.num_row_=len(self.rows);lp.a_matrix_.format_=hc.MatrixFormat.kColwise
        lp.a_matrix_.start_=self.A.indptr.astype(np.int32);lp.a_matrix_.index_=self.A.indices.astype(np.int32);lp.a_matrix_.value_=self.A.data
        lp.integrality_=[hc.HighsVarType.kContinuous if relax or not x else hc.HighsVarType.kInteger for x in self.ints]
        if h.passModel(lp)!=hc.HighsStatus.kOk:raise RuntimeError('model rejected')
        if self.warm is not None and self.feasible(self.warm) and not relax:
            sol=hc.HighsSolution();sol.col_value=self.warm;sol.value_valid=True
            if h.setSolution(sol)!=hc.HighsStatus.kOk:raise RuntimeError('warm start rejected')
        h.run();status=h.getModelStatus();info=h.getInfo();sol=h.getSolution();optimal=status==hc.HighsModelStatus.kOptimal
        x=np.asarray(sol.col_value) if sol.value_valid else None;accepted=self.feasible(x,not relax);fallback=False
        if not relax and self.warm is not None and self.feasible(self.warm) and (not accepted or cost@self.warm<cost@x-1e-7):
            x=self.warm.copy();accepted=True;fallback=True
        bound=(float(info.objective_function_value) if optimal else None) if relax else float(info.mip_dual_bound)
        if bound is not None and not math.isfinite(bound):bound=None
        upper=float(cost@x) if accepted and not relax else None
        meta=dict(scope=self.scope,status=h.modelStatusToString(status),optimal=bool(optimal),incumbent=bool(accepted and not relax),
                  warm_fallback=fallback,lower_bound=bound,upper_bound=upper,weights=list(weights),epsilon=dict(self.cap),
                  gap=(max(0.,upper-bound)/max(1,abs(upper)) if upper is not None and bound is not None else None),
                  matrix_residual=self.residual(x,not relax) if accepted else None,variables=len(self.lb),constraints=len(self.rows),
                  horizon=self.H,seconds=time.perf_counter()-t,seed=seed,relaxation=relax,nodes=int(info.mip_node_count) if not relax else 0)
        plan=self.unpack(x) if accepted and not relax else None
        if plan:self.warm=self.encode(plan)
        return plan,meta
    def lexsolve(self,order=(2,3,1,0),seconds=2.,seed=202600):
        logs=[];plan=None;certified=True
        for j in order:
            trial,meta=self.solve(np.eye(4)[j],seconds,seed);meta['stage']='NECL'[j];meta['prior_stages_certified']=certified;logs.append(meta)
            if trial is None:break
            plan=trial;certified &= meta['optimal']
            # A timed-out stage fixes only its incumbent upper bound, not an
            # optimum claim; subsequent stages are conditional improvements.
            self.add(self.f[j],high=plan['objective'][j]+OBJ_TOL[j]);self.compile();self.warm=self.encode(plan)
        return plan,logs
