"""Target 20--22 sorties and 66 kWh as epsilon search conditions, not truth."""
import os
for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:
    os.environ[k]='1'
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
import json,gzip,shutil,sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import search_expanded as search
DEST=HERE/'target_20_22'
def run(spec):
    search.HERE=DEST
    return search.worker(spec)
def main():
    DEST.mkdir(exist_ok=True)
    shutil.copyfile(HERE/'frozen_evaluation_candidates.json.gz',DEST/'expanded_candidates.json.gz')
    initial=search.read(HERE/'联合非支配档案.json')
    for p in (HERE/'run2').glob('worker_*_archive.json'):initial+=search.read(p)
    search.save_json(DEST/'initial_archive.json',initial)
    specs=[(0,60,4.,20,dict(cap={'N':20},weights=[.01,.04,.8,.15])),
           (1,60,4.,20,dict(cap={'N':21,'E':66.},weights=[.01,.04,.8,.15])),
           (2,60,4.,20,dict(cap={'N':22,'E':66.},weights=[.01,.04,.8,.15])),
           (3,60,4.,20,dict(cap={'N':22},weights=[.05,.05,.7,.2]))]
    search.save_json(DEST/'target_config.json',dict(jobs=specs,
        meaning='N is an upper epsilon bound, never fixed to 28 or any externally reported answer; 66 kWh is a search threshold only.',
        reference_89_min_s=5340,reference_is_unverified=True))
    with ProcessPoolExecutor(max_workers=4) as executor:
        out=[f.result() for f in as_completed([executor.submit(run,s) for s in specs])]
    search.save_json(DEST/'worker_summary.json',out)
if __name__=='__main__':main()
