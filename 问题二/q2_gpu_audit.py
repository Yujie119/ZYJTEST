"""Recompute route physics in float64 on both GPUs from boxes and DEM geometry.

This is an independent tensor implementation, not a sum of cached energies.
It does not accelerate or certify HiGHS' integer optimization.
"""
from __future__ import annotations
import os
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['MKL_NUM_THREADS']='1'
import gzip,json,time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import torch
from q2_data import OUT,load_data,save_json


def evaluate(device_index, data, routes):
    begin=time.perf_counter()
    torch.cuda.set_device(device_index)
    device=torch.device(f'cuda:{device_index}')
    torch.cuda.reset_peak_memory_stats(device)
    inputs=[]; owners=[]; ground=[]; expected=[]; full=[]; reserve=[]
    for k,r in enumerate(routes):
        v=data['vehicles'][r['vehicle']]
        q=sum(data['boxes'][b]['mass'] for e in r['events'] for b in e['boxes'])
        n=sum(len(e['boxes']) for e in r['events'])
        ground.append(v['prep']+n*v['load']+sum(v['handoff0']+len(e['boxes'])*v['handoff1'] for e in r['events']))
        full.append([v['battery'],v['tfull']]);reserve.append(v['rho'])
        expected.append([r['energy'],r['duration'],r['soc'],r['charge_s']])
        here='O01'
        for e in r['events']+[{'zone':'O01','boxes':[]}]:
            geo=data['geos'][here,e['zone']]
            # All inputs below come from the original parameters, box events
            # and the DEM geometry whose traversal has a separate slab audit.
            inputs.append([q,v['capacity'],v['r0'],v['rf'],v['battery'],geo['distance'],v['empty'],geo['up'],v['eta'],v['up'],v['speed'],geo['down'],v['down']])
            owners.append(k)
            q-=sum(data['boxes'][b]['mass'] for b in e['boxes']);here=e['zone']
    raw=torch.tensor(np.array(inputs),device=device,dtype=torch.float64)
    own=torch.tensor(owners,device=device,dtype=torch.long)
    constant=torch.tensor(full,device=device,dtype=torch.float64)
    torch.cuda.synchronize(device)
    compute_start=time.perf_counter()
    q,cap,r0,rf,bat,d,empty,dh,eta,up,speed,dd,down=raw.T
    distance_range=r0-(r0-rf)*(q.clamp_min(0)/cap).pow(1.5)
    leg_energy=bat*d/distance_range+(empty+q)*9.81*dh/(eta*3600000.)
    leg_time=dh/up+d/speed+dd/down
    energy=torch.zeros(len(routes),device=device,dtype=torch.float64).index_add_(0,own,leg_energy)
    duration=torch.tensor(ground,device=device,dtype=torch.float64).index_add_(0,own,leg_time)
    soc=1-energy/constant[:,0]
    charge=constant[:,1]*torch.where(soc<.9,.65*(.9-soc)/.9+.35,.35*(1-soc)/.1)
    result=torch.stack([energy,duration,soc,charge],dim=1)
    torch.cuda.synchronize(device)
    compute_seconds=time.perf_counter()-compute_start
    values=result.cpu().numpy();errors=np.max(np.abs(values-np.asarray(expected)),axis=0)
    okay=bool(np.isfinite(values).all() and np.all(errors<=np.array([1e-7,2e-5,1e-9,2e-5])) and np.all(values[:,2]>=np.array(reserve)-1e-9))
    return dict(device=device_index,name=torch.cuda.get_device_name(device_index),routes=len(routes),legs=len(inputs),dtype='float64',
                passed=okay,max_abs_error=dict(zip(['energy_kwh','duration_s','soc','charge_s'],errors.tolist())),
                compute_seconds=compute_seconds,wall_seconds=time.perf_counter()-begin,
                peak_tensor_bytes=torch.cuda.max_memory_allocated(device))


def main():
    start=time.perf_counter();data=load_data()
    if torch.cuda.device_count()<2:
        save_json(OUT/'子问题二/双GPU物理复算.json',dict(status='unavailable',devices=torch.cuda.device_count(),passed=False))
        raise RuntimeError('Two CUDA devices required for the requested dual-GPU verification')
    with gzip.open(OUT/'子问题一/完整单点逐箱候选.json.gz','rt',encoding='utf-8') as f:catalog=json.load(f)
    pool=json.loads((OUT/'子问题一/联合候选库.json').read_text(encoding='utf-8'))
    routes=list({r['candidate_id']:r for r in catalog+pool}.values())
    mid=(len(routes)+1)//2
    with ThreadPoolExecutor(max_workers=2) as executor:
        tasks=[executor.submit(evaluate,i,data,r) for i,r in enumerate([routes[:mid],routes[mid:]])]
        devices=[t.result() for t in tasks]
    report=dict(status='completed',passed=all(d['passed'] for d in devices),devices=devices,route_count=len(routes),
                torch_version=torch.__version__,cuda_version=torch.version.cuda,wall_seconds=time.perf_counter()-start,
                provenance='Original workbook parameters and box masses; DEM geometry separately checked with independent pixel-rectangle intersections.',
                scope='Independent tensor recomputation of candidate energy, duration, SOC and charging on both GPUs. No GPU MIP or speedup claim.')
    save_json(OUT/'子问题二/双GPU物理复算.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
