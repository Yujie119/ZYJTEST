"""Read-only source/results review; writes independent_review/ only."""
from pathlib import Path
import sys,json,gzip,hashlib,math
from collections import Counter
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
AUD=ROOT/'问题二/源头核查_20260924/implementation'
OUT=HERE/'independent_review';OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(AUD))
from independent_raw_verify import raw_data,verify

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    raw=raw_data();plan=read(HERE/'最终方案.json');arc=read(HERE/'联合非支配档案.json');bases=read(HERE/'偏好极点基准_扩大库松弛.json')
    with gzip.open(HERE/'frozen_evaluation_candidates.json.gz','rt',encoding='utf-8') as f:pool=json.load(f)
    # Reverse route ordering relative to production and use sorted box ordering.
    pool=sorted(pool,key=lambda r:r['candidate_id'],reverse=True)
    boxes=sorted(raw[3]);bi={b:i for i,b in enumerate(boxes)};types=sorted(raw[0]);tidx={g:i for i,g in enumerate(types)}
    r=[];c=[];v=[]
    for j,route in enumerate(pool):
        for b in route['box_ids']:r.append(bi[b]);c.append(j);v.append(1.)
    A=coo_matrix((v,(r,c)),shape=(len(boxes),len(pool)+1)).tocsr()
    G=np.zeros((len(types),len(pool)+1))
    for j,route in enumerate(pool):G[tidx[route['vehicle']],j]=route['duration']
    counts=np.array([sum(t==g for t in raw[1].values()) for g in types])
    G[:,-1]=-counts
    final=verify(plan,raw);save('final_raw_verification.json',final)
    checks=[];archive_raw=[]
    for i,p in enumerate(arc):
        out=verify(p,raw);archive_raw.append({'index':i,'source':p.get('source'),'objective':out['objective'],'all':out['all'],'checks_count':out['checks_count']})
        if not out['all']:save(f'archive_{i}_failed_raw_verification.json',out)
    save('archive_raw_verifications.json',archive_raw)
    assert final['all'] and all(p['all'] for p in archive_raw)
    scale=np.array(read(ROOT/'问题二/冻结评价配置.json')['scale'])
    certificates=[]
    for i,base in enumerate(bases):
        coeff=np.array(base['weight'])/scale
        assert np.allclose(coeff,base['coefficients'],rtol=0,atol=1e-12)
        cost=np.array([coeff[0]+coeff[1]*route['energy'] for route in pool]+[coeff[2]])
        sol=linprog(cost,A_ub=G,b_ub=np.zeros(len(types)),A_eq=A,b_eq=np.ones(len(boxes)),bounds=[(0,1)]*len(pool)+[(0,None)],method='highs')
        assert sol.success
        y=np.array(sol.eqlin.marginals);z=np.minimum(np.array(sol.ineqlin.marginals),0.)
        # A valid weak-duality certificate for finite route upper bounds. Shrink
        # any negative resource duals enough to ensure C's reduced cost >= 0.
        use=float(-counts@z)
        if use>coeff[2]:z*=np.nextafter(coeff[2]/use,0.)
        rc=cost-np.asarray(A.T@y).ravel()-G.T@z
        if rc[-1]<0:
            z*=1-1e-12
            rc=cost-np.asarray(A.T@y).ravel()-G.T@z
        assert rc[-1]>=0
        dual=float(y.sum()+np.minimum(rc[:-1],0.).sum())
        certificate=dual-1e-8*max(1,abs(dual))
        scores=[float(coeff@np.array(p['objective'])) for p in arc]
        upper=min(scores)
        certificates.append({'index':i,'solver_success':bool(sol.success),'reported_lower':base['lower'],'independent_LP':float(sol.fun),'dual_certificate_before_safety':dual,'conservative_dual_certificate':certificate,'C_reduced_cost':float(rc[-1]),'equality_dual':y.tolist(),'resource_dual':z.tolist(),'reported_lower_matches_LP':abs(base['lower']-sol.fun)<1e-6,'reported_upper_matches_archive':abs(base['upper']-upper)<1e-8,'upper':upper})
    save('LP_dual_certificates.json',certificates)
    for p in arc:
        scores=np.array([np.array(b['coefficients'])@np.array(p['objective']) for b in bases])
        lower=max(0.,float(np.max(scores-np.array([b['upper'] for b in bases]))));upper=float(np.max(scores-np.array([b['lower'] for b in bases])))
        checks.append({'source':p.get('source'),'objective':p['objective'],'recomputed_regret':[lower,upper],'reported_regret':[p['regret_lower'],p['regret_upper']],'match':abs(lower-p['regret_lower'])<1e-8 and abs(upper-p['regret_upper'])<1e-8})
    save('regret_recheck.json',checks)
    selected=min(arc,key=lambda p:(p['regret_upper'],p['objective'][2],p['objective'][3]))
    dominates=[]
    tol=np.array([0,1e-7,1e-5,1e-7])
    for i,p in enumerate(arc):
        for j,q in enumerate(arc):
            if i==j:continue
            fp=np.array(p['objective']);fq=np.array(q['objective'])
            if np.all(fp<=fq+tol) and np.any(fp<fq-tol):dominates.append([i,j])
    poolids={r['candidate_id'] for r in pool}
    metadata={'final_objective':final['objective'],'final_raw_checks':final['checks_count'],'all_final_raw_checks':final['all'],'archive_count':len(arc),'all_archive_raw_checks':all(p['all'] for p in archive_raw),'all_archive_regrets_match':all(x['match'] for x in checks),'final_is_reported_choice':selected['objective']==plan['objective'],'archive_dominance_pairs':dominates,'candidate_count':len(pool),'all_archive_candidates_in_evaluation_pool':all(r['candidate_id'] in poolids for p in arc for r in p['routes']),'all_LP_recomputations_match':all(c['reported_lower_matches_LP'] for c in certificates),'all_preference_uppers_match':all(c['reported_upper_matches_archive'] for c in certificates),'scope':'expanded finite evaluation library, original frozen scale; weak-duality certificates independently reconstructed','files_sha256':{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ['search_expanded.py','最终方案.json','联合非支配档案.json','偏好极点基准_扩大库松弛.json','frozen_evaluation_candidates.json.gz']}}
    save('summary.json',metadata);print(json.dumps(metadata,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
