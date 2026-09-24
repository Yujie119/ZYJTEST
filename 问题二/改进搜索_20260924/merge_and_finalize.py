"""Merge all search branches and certify the published finite-library scope."""
import os
for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']:os.environ[k]='1'
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
import sys,json,gzip,time,shutil
from pathlib import Path
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor,as_completed,ThreadPoolExecutor
HERE=Path(__file__).resolve().parent
Q2=HERE.parent
sys.path[:0]=[str(HERE),str(Q2),str(Q2/'源头核查_20260924/implementation')]
import search_expanded as search
from q2_data import load_data,save_json
from q2_joint import JointModel,archive_add
from q2_verify import verify_plan
from independent_raw_verify import raw_data,verify

def improve(job):
    i,p=job;data=load_data();scale=search.read(Q2/'冻结评价配置.json')['scale']
    model=JointModel(data,deepcopy(p['routes']),mandatory=True,warm=p,
        cap=dict(zip('NECL',p['objective'])),scope=f'final_all_resources_plan_{i}')
    q,m=model.solve([1/s for s in scale],seconds=20,seed=20261101+i)
    if q is None:q=p
    checks,errors,_=verify_plan(data,q)
    if not checks['all']:raise AssertionError(errors)
    q['source']=f'all_resources_polish_of_{p.get("source",i)}'
    return q,m

def main():
    started=time.perf_counter()
    snapshot=HERE/'run1_snapshot';snapshot.mkdir(exist_ok=True)
    for name in ['最终方案.json','联合非支配档案.json','汇总.json','偏好极点基准_扩大库松弛.json','expanded_candidates.json.gz','frozen_evaluation_candidates.json.gz','runtime.json','search_config.json']:
        if (HERE/name).exists() and not (snapshot/name).exists():shutil.copyfile(HERE/name,snapshot/name)
    archive=[];sources=[]
    candidates=[HERE/'联合非支配档案.json',HERE/'run2/联合非支配档案.json',HERE/'direct_joint/archive.json']
    candidates+=sorted((HERE/'target_20_22').glob('worker_*_archive.json'))
    for p in candidates:
        if not p.exists():continue
        sources.append(str(p.relative_to(HERE)))
        for plan in search.read(p):archive_add(archive,plan)
    count_before=len(archive);polished=[];logs=[]
    with ProcessPoolExecutor(max_workers=6) as ex:
        for fut in as_completed([ex.submit(improve,(i,p)) for i,p in enumerate(archive)]):
            p,m=fut.result();archive_add(polished,p);logs.append(m)
            print('POLISH',p['objective'],m['status'],flush=True)
    save_json(HERE/'worker_merged_archive.json',polished)
    save_json(HERE/'全资源终端精修.json',logs)
    # Accumulate exact physical candidate records from every branch.
    allr={}
    for path in [HERE/'expanded_candidates.json.gz',HERE/'run2/frozen_evaluation_candidates.json.gz']:
        if path.exists():
            with gzip.open(path,'rt',encoding='utf-8') as f:
                for r in json.load(f):allr[r['candidate_id']]=r
    for folder in [HERE,HERE/'run2',HERE/'target_20_22']:
        for path in folder.glob('worker_*_discovered.json'):
            for r in search.read(path):allr[r['candidate_id']]=r
    for p in polished:
        for r in p['routes']:allr[r['candidate_id']]=r
    with gzip.open(HERE/'expanded_candidates.json.gz','wt',encoding='utf-8') as f:json.dump(list(allr.values()),f,ensure_ascii=False)
    search.collect()
    final=search.read(HERE/'最终方案.json');arc=search.read(HERE/'联合非支配档案.json')
    independent_raw=raw_data();audits=[]
    for i,p in enumerate(arc):
        r=verify(p,independent_raw)
        if not r['all']:raise AssertionError('independent raw verification failed')
        audits.append(dict(index=i,objective=p['objective'],passed=r['all'],checks=r['checks_count']))
    save_json(HERE/'最终原始数据独立核验.json',dict(final=verify(final,independent_raw),archive=audits,
        scope='Raw XLSX plus independent GeoTIFF slab geometry; O01-only charging/exchange feasible submodel.'))
    # Meaningful dual-GPU tensor verification of all frozen candidates.
    import torch
    from q2_gpu_audit import evaluate
    data=load_data()
    with gzip.open(HERE/'frozen_evaluation_candidates.json.gz','rt',encoding='utf-8') as f:routes=json.load(f)
    if torch.cuda.device_count()<2:raise RuntimeError('Requested dual GPUs unavailable')
    mid=(len(routes)+1)//2
    with ThreadPoolExecutor(max_workers=2) as ex:
        devices=[f.result() for f in [ex.submit(evaluate,0,data,routes[:mid]),ex.submit(evaluate,1,data,routes[mid:])]]
    save_json(HERE/'双GPU全候选复算.json',dict(passed=all(x['passed'] for x in devices),devices=devices,
        candidate_count=len(routes),note='GPU tensor physics verification, not GPU integer programming.'))
    if not all(x['passed'] for x in devices):raise AssertionError('GPU audit')
    save_json(HERE/'合并记录.json',dict(sources=sources,archive_before_polish=count_before,
        archive_after_merge=len(arc),candidate_count=len(routes),seconds=time.perf_counter()-started,
        scope='No sortie count is fixed in the main searches. Per-plan terminal polishing is only an additional dominance improvement.',
        expert_addendum='No spare batteries; initially all at O01. Current solutions do not use off-depot exchanges and remain restricted feasible baselines.'))
    print('FINAL',final['objective'],flush=True)

if __name__=='__main__':main()
