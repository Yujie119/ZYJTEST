"""Second bounded cover wave, inheriting verified incumbent selections."""
from concurrent.futures import ProcessPoolExecutor, as_completed
import time
import search_cover_master_warm as s

def main():
    start=time.perf_counter()
    first=s.read(s.HERE/'archive.json')
    s.save_json(s.HERE/'initial_archive.json',first)
    archive=list(first)
    specs=[]
    for j,cap in enumerate([{}, {'N':20},{'N':21},{'N':22},{'N':23},{'N':24},{'E':66.},{'E':65.5}]):
        specs.append(dict(name=f'warm_{j:02d}',cap=cap,weights=[.10,.15,.75],
            schedule_weights=[0,0,1/7000.,.3/600.],noise=.0005,seed=2026092480+j,
            master_seconds=15.,schedule_seconds=12.))
    s.save_json(s.HERE/'warm_config.json',specs)
    logs=[]
    with ProcessPoolExecutor(max_workers=4) as ex:
        for f in as_completed([ex.submit(s.worker,p) for p in specs]):
            r=f.result();logs.append({k:v for k,v in r.items() if k!='plan'})
            if r['plan']:s.archive_add(archive,r['plan'])
            s.save_json(s.HERE/'combined_archive.json',archive)
            s.save_json(s.HERE/'warm_solver_log.json',logs)
    s.save_json(s.HERE/'warm_summary.json',dict(seconds=time.perf_counter()-start,
        jobs=len(specs),objectives=[p['objective'] for p in archive]))

if __name__=='__main__':main()
