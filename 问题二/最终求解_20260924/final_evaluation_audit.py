"""Independent audit of final packaging/evaluation, read-only.

Avoids rerunning all LPs when the frozen expanded candidate library hash is
unchanged; independently recomputes route identity, regrets, Pareto choice,
and original-XLSX/GeoTIFF feasibility.
"""
from __future__ import annotations
from pathlib import Path
import gzip,hashlib,json,re,sys
import numpy as np
HERE=Path(__file__).resolve().parent; Q2=HERE.parent; OLD=Q2/'改进搜索_20260924'; AUD=Q2/'源头核查_20260924/implementation'
OUT=HERE/'final_evaluation_audit';OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(AUD));sys.path.insert(0,str(Q2))
from independent_raw_verify import raw_data,verify as raw_verify
from q2_data import load_data

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(n,x):(OUT/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(routes):
    props=['candidate_id','vehicle','events','box_ids','energy','duration','charge_s','offsets','latest_start']
    raw=[{k:r[k] for k in props} for r in sorted(routes,key=lambda r:r['candidate_id'])]
    return hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def main():
    code=(HERE/'finalize_submission.py').read_text(encoding='utf-8')
    source_mentions={'combined_archive': 'combined_archive.json' in code,
                     'old_archive': 'OLD/\'联合非支配档案.json\'' in code or 'OLD/"联合非支配档案.json"' in code,
                     'cover_archive': 'cover_search/archive.json' in code}
    with gzip.open(OLD/'frozen_evaluation_candidates.json.gz','rt',encoding='utf-8') as f:pool=json.load(f)
    pool_hash=digest(pool)
    bases_path=HERE/'偏好极点基准_扩大库松弛.json' if (HERE/'偏好极点基准_扩大库松弛.json').exists() else OLD/'偏好极点基准_扩大库松弛.json'
    old_bases=read(bases_path);frozen=read(Q2/'冻结评价配置.json');scale=np.array(frozen['scale'])
    base_scope={'candidate_count':len(pool),'candidate_digest':pool_hash,'old_reported_library_hash':old_bases[0].get('library_coefficient_sha256'),'old_reported_base_hashes':sorted(set(b.get('library_coefficient_sha256') for b in old_bases)),'frozen_scale':frozen['scale'],'source_mentions':source_mentions,'finalize_sha256':sha(HERE/'finalize_submission.py')}
    issues=[]
    if not source_mentions['combined_archive']:issues.append('FAIL: finalize_submission.py does not mention cover_search/combined_archive.json; it may package stale archive.json.')
    if source_mentions['old_archive']:issues.append('WARN: finalize includes OLD/联合非支配档案.json in addition to combined_archive.json; this broadens the source archive and should remain explicit in the release record.')
    final_path=HERE/'最终方案.json';archive_path=HERE/'联合非支配档案.json'
    if not final_path.exists() or not archive_path.exists():
        save('summary.json',{'status':'WAITING_FOR_FINAL_FILES','scope':base_scope,'issues':issues})
        print(json.dumps({'status':'WAITING_FOR_FINAL_FILES','issues':issues},ensure_ascii=False));return
    final=read(final_path);archive=read(archive_path)
    ids={r['candidate_id']:r for r in pool};route_errors=[]
    for pi,p in enumerate(archive):
        for r in p['routes']:
            old=ids.get(r['candidate_id'])
            if old is None:route_errors.append({'plan':pi,'candidate_id':r['candidate_id'],'error':'outside frozen candidate library'});continue
            for key in ['vehicle','box_ids','events','offsets']:
                if r.get(key)!=old.get(key):route_errors.append({'plan':pi,'candidate_id':r['candidate_id'],'field':key,'error':'identity mismatch'})
            for key in ['energy','duration','charge_s','latest_start']:
                a,b=r.get(key),old.get(key)
                # save_json encodes +inf latest_start as null; treat null and
                # positive infinity as the same unbounded deadline.
                if key=='latest_start' and ((a is None and (b is None or b==float('inf'))) or (b is None and a==float('inf'))):
                    continue
                if a is None or b is None or abs(float(a)-float(b))>1e-8:route_errors.append({'plan':pi,'candidate_id':r['candidate_id'],'field':key,'error':'coefficient mismatch','current':a,'library':b})
    if route_errors:issues.append('FAIL: final archive has routes outside or inconsistent with frozen evaluation library.')
    # The same LP lower bounds are reusable only when the coefficient digest and
    # frozen scale match; do not call them full-route bounds.
    old_scope_hashes=set(b.get('library_coefficient_sha256') for b in old_bases)
    if pool_hash not in old_scope_hashes:issues.append('FAIL: recomputed candidate coefficient digest differs from archived LP bound hash.')
    base_coeff=[]
    for i,b in enumerate(old_bases):
        coeff=np.array(b['weight'])/scale
        base_coeff.append(coeff)
        if not np.allclose(coeff,np.array(b['coefficients']),rtol=0,atol=1e-12):issues.append(f'FAIL: preference coefficient mismatch at extreme {i}')
    upper=[]; regret_errors=[]
    for i,b in enumerate(old_bases):
        u=min(float(np.dot(b['coefficients'],p['objective'])) for p in archive);upper.append(u)
        if abs(u-b.get('upper',u))>1e-8:issues.append(f'WARN: stale upper bound in old basis {i}; expected {u}, saved {b.get("upper")}')
    for i,p in enumerate(archive):
        vals=np.array([float(np.dot(b['coefficients'],p['objective'])) for b in old_bases])
        lo=max(0.,float(np.max(vals-np.array(upper))))
        hi=float(np.max(vals-np.array([b['lower'] for b in old_bases])))
        if abs(lo-p.get('regret_lower',lo))>1e-8 or abs(hi-p.get('regret_upper',hi))>1e-8:regret_errors.append({'plan':i,'reported':[p.get('regret_lower'),p.get('regret_upper')],'recomputed':[lo,hi]})
    if regret_errors:issues.append('FAIL: final archive regret interval does not match same-library coefficients/bounds.')
    tol=np.array([0,1e-7,1e-5,1e-7]);dom=[]
    for i,p in enumerate(archive):
        for j,q in enumerate(archive):
            if i!=j and np.all(np.array(p['objective'])<=np.array(q['objective'])+tol) and np.any(np.array(p['objective'])<np.array(q['objective'])-tol):dom.append([i,j])
    selected=min(archive,key=lambda p:(p['regret_upper'],p['objective'][2],p['objective'][3]))
    if selected['objective']!=final['objective']:issues.append('FAIL: final plan is not archive argmin under reported regret/C/L tie break.')
    raw=raw_data();raw_final=raw_verify(final,raw);raw_archive=[]
    for i,p in enumerate(archive):
        v=raw_verify(p,raw);raw_archive.append({'index':i,'all':v['all'],'checks_count':v['checks_count'],'objective':v['objective']})
        if not v['all']:issues.append(f'FAIL: original-data verification failed for archive plan {i}')
    # Confirm finalized summary names the actual final archive and keeps scope.
    summary=read(HERE/'汇总.json') if (HERE/'汇总.json').exists() else {}
    if summary and summary.get('route_count_not_fixed') is not True:issues.append('WARN: summary does not explicitly state route count was not fixed.')
    if summary and summary.get('source_library_file_sha256')!=sha(OLD/'frozen_evaluation_candidates.json.gz'):issues.append('FAIL: summary source library file hash mismatch.')
    report={'status':'PASS_WITH_SCOPE_WARNINGS' if not any(x.startswith('FAIL') for x in issues) else 'FAIL','issues':issues,'scope':base_scope,'final_objective':final['objective'],'archive_count':len(archive),'archive_route_count':len({r['candidate_id'] for p in archive for r in p['routes']}),'route_identity_errors':route_errors,'regret_errors':regret_errors,'archive_dominance_pairs':dom,'selection_matches':selected['objective']==final['objective'],'raw_final':{'all':raw_final['all'],'checks_count':raw_final['checks_count'],'objective':raw_final['objective']},'raw_archive':raw_archive,'lower_bounds_reused_same_library':pool_hash in old_scope_hashes,'lower_bound_scope':'frozen expanded finite library only; not unrestricted full-route problem','upper_bounds_recomputed':upper,'final_source_archive_hash':sha(archive_path),'final_plan_hash':sha(final_path)}
    save('summary.json',report);save('raw_final_verification.json',raw_final);save('raw_archive_verification.json',raw_archive);save('route_identity_check.json',route_errors);save('regret_recheck.json',{'upper':upper,'errors':regret_errors,'dominance':dom})
    print(json.dumps({'status':report['status'],'issues':issues,'final':final['objective'],'archive_count':len(archive),'raw_final':raw_final['all'],'dominance_pairs':len(dom)},ensure_ascii=False))

if __name__=='__main__':main()
