import os
os.environ["MKL_THREADING_LAYER"]="SEQUENTIAL"
for k in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS"):os.environ[k]="1"
import sys,json,torch,numpy,scipy,psutil
from pathlib import Path
records=[]
for d in range(torch.cuda.device_count()):
    torch.manual_seed(20260924)
    x=torch.randn((128,128),device=f"cuda:{d}",dtype=torch.float64)
    y=x@x.T;torch.cuda.synchronize(d)
    records.append(dict(device=d,name=torch.cuda.get_device_name(d),witness=float(y.diag().sum()),free_bytes=torch.cuda.mem_get_info(d)[0]))
assert len(records)>=2,"需要两张可用CUDA GPU"
result=dict(python=sys.executable,torch=torch.__version__,cuda=torch.version.cuda,numpy=numpy.__version__,scipy=scipy.__version__,
            logical_cpu=psutil.cpu_count(),physical_cpu=psutil.cpu_count(logical=False),ram_bytes=psutil.virtual_memory().total,
            available_ram_bytes=psutil.virtual_memory().available,gpu=records)
Path(__file__).with_name("环境核验.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print("Q3_ENVIRONMENT_WITNESS",json.dumps(result,ensure_ascii=False))

