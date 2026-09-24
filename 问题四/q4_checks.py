"""Independent numerical MILP/LP and GPU cross-checks of exact Q4 enumeration."""
from fractions import Fraction as F
import time
import numpy as np
from scipy.optimize import milp,linprog,Bounds,LinearConstraint
from q4_core import R,frac,evaluate

def milp_checks(c,g,rows,cache,chosen,meta):
    cols=list(cache);n=len(cols)
    eq=np.array([[int(m in u) for u in cols] for m in range(c['M'])]+[[1]*n],float)
    rhs=np.array([1]*c['M']+[g],float)
    bq=[cache[u]['b'] for u in cols]
    qq=[sum(F(12,c['inventory'][r])*cache[u]['resources'][r] for r in R) for u in cols]
    b=np.array([float(v) for v in bq]);q=np.array([float(v) for v in qq])
    base=LinearConstraint(eq,rhs,rhs);bounds=Bounds(np.zeros(n),np.ones(n))
    def run(obj,extra=()):
        return milp(np.asarray(obj),integrality=np.ones(n),bounds=bounds,
                    constraints=[base,*extra],options={'mip_rel_gap':0.0})
    def reconstruct(res):
        assert res.status==0,res.message
        part=tuple(sorted([cols[i] for i,z in enumerate(res.x[:n]) if z>.5],key=lambda u:u[0]))
        return evaluate(c,part)
    eps=int(sum(sum(F(12,c['inventory'][r])*cache[(m,)]['resources'][r] for r in R) for m in range(c['M'])))
    records=[]
    while True:
        feasible=[r for r in rows if r['Q']<=eps];extra=LinearConstraint(q,-np.inf,eps)
        res=run(b,[extra])
        lp=linprog(b,A_ub=q[None,:],b_ub=[eps],A_eq=eq,b_eq=rhs,bounds=(0,1),method='highs')
        if not feasible:
            assert res.status==2,res.message
            records.append({'G':g,'epsilon':eps,'status':'INTEGER_INFEASIBLE','Q':None,'B':None,
                            'partition_code':None,'LP_status':int(lp.status),'LP_bound':None,
                            'LP_bound_exact':None,'gap':None,'MILP_gap':None,
                            'dual_y_exact':None,'dual_t_exact':None});break
        best=min(feasible,key=lambda r:(r['B'],r['Q'],r['H_stock'],r['partition_code']))
        first=reconstruct(res);assert first['B']==best['B']
        res2=run(q,[extra,LinearConstraint(b,-np.inf,float(best['B'])+1e-9)])
        second=reconstruct(res2);assert (second['Q'],second['B'])==(best['Q'],best['B'])
        assert lp.status==0,lp.message
        # A valid rational lower bound from any dual trial: residuals are
        # minimized over 0<=x<=1, correcting all floating dual infeasibility.
        y=[frac(v) for v in lp.eqlin.marginals];t=min(F(0),frac(lp.ineqlin.marginals[0]))
        lower=sum(y[i]*int(rhs[i]) for i in range(len(y)))+eps*t
        lower+=sum(min(F(0),bq[j]-sum(int(eq[i,j])*y[i] for i in range(len(y)))-qq[j]*t) for j in range(n))
        assert lower<=best['B']
        records.append({'G':g,'epsilon':eps,'status':'EXACT_ENUM_MILP_AGREE','Q':best['Q'],'B':best['B'],
                        'partition_code':best['partition_code'],'LP_status':int(lp.status),'LP_bound':lower,
                        'LP_bound_exact':str(lower),'gap':best['B']-lower,'MILP_gap':float(res.mip_gap),
                        'dual_y_exact':[str(v) for v in y],'dual_t_exact':str(t)})
        eps=best['Q']-1
    endpoints=[]
    for theta in sorted(set(meta['theta_endpoints'])):
        rt=reconstruct(run(float(theta)*q/96+(1-float(theta))*b))
        value=theta*rt['A']+(1-theta)*rt['B'];assert value==meta['v'][str(theta)]
        endpoints.append({'theta':theta,'value':value,'value_exact':str(value),'partition_code':rt['partition_code']})
    cons=[LinearConstraint(np.pad(eq,((0,0),(0,1))),rhs,rhs)]
    for theta in sorted(set(meta['theta_endpoints'])):
        cons.append(LinearConstraint(np.r_[float(theta)*q/96+(1-float(theta))*b,-1.0],
                                     -np.inf,float(meta['v'][str(theta)])))
    res=milp(np.r_[np.zeros(n),1.0],integrality=np.r_[np.ones(n),0],
             bounds=Bounds(np.zeros(n+1),np.r_[np.ones(n),np.inf]),constraints=cons,
             options={'mip_rel_gap':0.0})
    mm=reconstruct(res)
    regret=max(t*mm['A']+(1-t)*mm['B']-meta['v'][str(t)] for t in meta['theta_endpoints'])
    assert regret==chosen['regret_max']
    stock=np.array([[cache[u]['resources'][r] for u in cols] for r in R],float)
    stock_res=run(np.zeros(n),[LinearConstraint(stock,-np.inf,[c['inventory'][r] for r in R])])
    assert (stock_res.status==0 if any(x['inventory_feasible'] for x in rows) else stock_res.status==2)
    return {'G':g,'candidate_groups':n,'epsilon':records,'endpoints':endpoints,
            'minimax_value':regret,'minimax_value_exact':str(regret),
            'minimax_milp_partition':mm['partition_code'],'stock_milp_status':int(stock_res.status)}

def gpu_peak_check(c,g,cache,device):
    import torch
    begin=time.perf_counter();dev=torch.device(f'cuda:{device}');torch.cuda.set_device(dev)
    torch.cuda.reset_peak_memory_stats(dev);cols=list(cache);comparisons=0;cells=0
    for r in R:
        ev=[e for e in c['events'] if e['resource_type']==r]
        if not ev:continue
        tt=sorted({v for e in ev for v in [e['start'],e['ready']]})[:-1]
        starts=torch.tensor([float(e['start']) for e in ev],dtype=torch.float64,device=dev)
        ends=torch.tensor([float(e['ready']) for e in ev],dtype=torch.float64,device=dev)
        points=torch.tensor([float(t) for t in tt],dtype=torch.float64,device=dev)
        active=((starts[:,None]<=points)&(points<ends[:,None])).to(torch.float64)
        member=torch.tensor([[e['component'] in u for e in ev] for u in cols],dtype=torch.float64,device=dev)
        actual=(member@active).amax(dim=1).to(torch.int64).cpu().tolist()
        assert actual==[cache[u]['resources'][r] for u in cols],(g,r)
        comparisons+=len(cols);cells+=active.numel()+member.numel()
    torch.cuda.synchronize(dev)
    return {'device':device,'name':torch.cuda.get_device_name(dev),'G':g,'candidate_resource_checks':comparisons,
            'tensor_cells':cells,'peak_allocated_bytes':torch.cuda.max_memory_allocated(dev),
            'seconds_including_transfer':time.perf_counter()-begin,'agreement':True,
            'role':'float64 tensor peak cross-check; exact CPU enumeration is authoritative'}
