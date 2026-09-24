"""Two CUDA workers for dense physical-parameter sweeps (float64).

HiGHS itself runs on CPU. This module does not claim GPU acceleration of MILP.
"""
import os
import time


def gpu_capacity_worker(device, rows, rho_values, eta_values):
    os.environ["MKL_THREADING_LAYER"] = "SEQUENTIAL"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    import torch
    torch.set_num_threads(1)
    if not torch.cuda.is_available() or device >= torch.cuda.device_count():
        raise RuntimeError(f"Requested CUDA device {device} unavailable")
    torch.cuda.set_device(device)
    torch.cuda.reset_peak_memory_stats(device)
    start = time.perf_counter()
    raw = torch.tensor(rows, dtype=torch.float64, device=f"cuda:{device}")
    # rows: m0,Q,L0,LF,battery,d,hu,hd
    m0,qmax,l0,lf,bat,d,hu,hd = [raw[:,i,None,None] for i in range(8)]
    rho=torch.tensor(rho_values,dtype=torch.float64,device=raw.device)[None,:,None]
    eta=torch.tensor(eta_values,dtype=torch.float64,device=raw.device)[None,None,:]
    budget=(1-rho)*bat
    def energy(q):
        length=l0-(l0-lf)*(q/qmax).pow(1.5)
        return bat*d/length+bat*d/l0+((m0+q)*hu+m0*hd)*9.81/(eta*3.6e6)
    lo=torch.zeros((len(rows),len(rho_values),len(eta_values)),dtype=torch.float64,device=raw.device)
    hi=qmax.expand_as(lo).clone()
    for _ in range(65):
        mid=(lo+hi)*.5
        ok=energy(mid)<=budget
        lo=torch.where(ok,mid,lo)
        hi=torch.where(ok,hi,mid)
    result=torch.where(energy(torch.zeros_like(lo))>budget+1e-9,
                       torch.full_like(lo,float("nan")),lo)
    result=torch.where(energy(qmax)<=budget+1e-9,qmax,result)
    torch.cuda.synchronize(device)
    elapsed=time.perf_counter()-start
    capacities=result.cpu().numpy()
    return capacities,dict(device=device,name=torch.cuda.get_device_name(device),
                            torch_version=torch.__version__,cuda_version=torch.version.cuda,
                            dtype="float64",capacity_cases=int(result.numel()),
                            seconds=elapsed,peak_allocated_bytes=torch.cuda.max_memory_allocated(device),
                            peak_reserved_bytes=torch.cuda.max_memory_reserved(device))

