"""Problem 3 shared inputs, DEM interval certificates and dual-GPU screening."""
from __future__ import annotations
import os
os.environ["MKL_THREADING_LAYER"]="SEQUENTIAL"
for _k in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS"):
    os.environ[_k]="1"
import json, math, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from scipy.io import loadmat
from numba import njit
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(__file__).resolve().parent
for _d in ("子问题一","子问题二","缓存","图表","日志"):
    (OUT/_d).mkdir(exist_ok=True)
import q3_inputs as q2
from q3_inputs import local_xy, supercover
G=9.81
def save(path,obj):
    Path(path).write_text(json.dumps(q2.jr(obj),ensure_ascii=False,indent=2),encoding="utf-8")
def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
def csv(path,rows):
    pd.DataFrame(rows).to_csv(path,index=False,encoding="utf-8-sig")

@njit(cache=True,nogil=True)
def clip_poly(p,n,axis,bound,lower):
    result=np.empty((12,3),np.float64)
    m=0
    if n==0:return result,0
    a=p[n-1].copy()
    ina=a[axis]>=bound if lower else a[axis]<=bound
    for i in range(n):
        b=p[i]
        inb=b[axis]>=bound if lower else b[axis]<=bound
        if ina != inb:
            den=b[axis]-a[axis]
            if abs(den)>1e-20:
                t=(bound-a[axis])/den
                result[m]=a+t*(b-a);m+=1
        if inb: result[m]=b;m+=1
        a=b.copy();ina=inb
    return result,m

@njit(cache=True,nogil=True)
def sweep_clear(a,b,q,dem,nodata):
    """Exact triangle-vs-closed-pixel clipping under piecewise constant DEM.
    Vertices use raster edge coordinates (column,row) and altitude in metres.
    Degenerate triangles (stationary/vertical/collinear phases) are retained.
    Expansion and a positive clearance tolerance make acceptance conservative.
    """
    tri=np.empty((12,3),np.float64)
    tri[0]=a;tri[1]=b;tri[2]=q
    eps=1e-8
    low=int(math.floor(min(a[1],b[1],q[1])-eps))
    high=int(math.floor(max(a[1],b[1],q[1])+eps))
    if low<0 or high>=dem.shape[0]:return False
    for r in range(low,high+1):
        p,n=clip_poly(tri,3,1,r-eps,True)
        p,n=clip_poly(p,n,1,r+1+eps,False)
        if n==0:continue
        xmin=p[0,0];xmax=xmin
        for i in range(1,n):xmin=min(xmin,p[i,0]);xmax=max(xmax,p[i,0])
        cl=int(math.floor(xmin-eps));ch=int(math.floor(xmax+eps))
        if cl<0 or ch>=dem.shape[1]:return False
        for c in range(cl,ch+1):
            h=dem[r,c]
            if not np.isfinite(h) or h==nodata:return False
            zmin=p[0,2]
            for i in range(1,n):zmin=min(zmin,p[i,2])
            if h+1e-6<zmin:continue
            pc,nc=clip_poly(p,n,0,c-eps,True)
            pc,nc=clip_poly(pc,nc,0,c+1+eps,False)
            if nc:
                z=pc[0,2]
                for i in range(1,nc):z=min(z,pc[i,2])
                if z<=h+1e-6:return False
    return True

class Context:
    def __init__(self):
        _,self.boxes,self.vs,self.nodes,self.manifest=q2.read_inputs()
        self.geos=q2.all_geometry(self.nodes)
        raw=loadmat(next((ROOT/"D题/数据").rglob("镇龙乡及周边30米DEM.mat")))
        self.dem=np.asarray(raw["dem"],dtype=np.float64)
        self.tr=np.asarray(raw["transform"]).ravel()
        self.nodata=float(raw["nodata"].item())
        self.lon0=float(self.nodes.lon.iloc[0]);self.lat0=float(self.nodes.lat.iloc[0])
        self.mx=float(local_xy(self.lon0+1,self.lat0,self.lon0,self.lat0)[0])
        self.my=float(local_xy(self.lon0,self.lat0+1,self.lon0,self.lat0)[1])
        self.xyz=np.array(self.nodes[["x_m","y_m","operation_m"]],float)
        self.gateway=np.array([0.,0.,float(self.nodes.ground_m.iloc[0])+20.])
        self.qs=[];self.arc_cache={};self.node_cache={}
        self.hardware={}
        self.catinfo={cat:group.iloc[0].to_dict() for cat,group in self.boxes.groupby("category")}
    def raster(self,p):
        dx,_,left,_,dy,top=self.tr
        return np.array([(self.lon0+p[0]/self.mx-left)/dx,
                         (self.lat0+p[1]/self.my-top)/dy,p[2]],float)
    def ground(self,x,y):
        c,r,_=self.raster(np.array([x,y,0.]))
        if 0<=r<self.dem.shape[0] and 0<=c<self.dem.shape[1]:
            h=float(self.dem[int(r),int(c)])
            if np.isfinite(h) and h!=self.nodata:return h
        return None
    def margin(self,a,b,q,limit):
        d=max(np.linalg.norm(a-q),np.linalg.norm(b-q))+1e-6
        fs=32.45+20*math.log10(2400.)+20*math.log10(max(d,1e-9)/1000.)
        if limit-fs-10>=1e-7:return limit-fs-10,"worst_blockage"
        if limit-fs<1e-7:return limit-fs-10,"distance_fail"
        clear=sweep_clear(self.raster(a),self.raster(b),self.raster(q),self.dem,self.nodata)
        return limit-fs-(0 if clear else 10)-1e-7,("triangle_clear" if clear else "blocked_or_uncertified")
    def point_margin(self,a,q,limit):return self.margin(a,a,q,limit)[0]
    def relay_geometry(self,x,y,height):
        ground=self.ground(x,y)
        if ground is None:return None
        pos=np.array([x,y,ground+height])
        back=self.point_margin(pos,self.gateway,126.)
        if back<0:return None
        rc0=self.raster(self.xyz[0]);rc1=self.raster(pos)
        cells=supercover(rc0[0],rc0[1],rc1[0],rc1[1],self.dem.shape)
        terrain=max(self.dem[r,c] for r,c in cells)
        H=max(float(terrain)+50.,self.xyz[0,2],pos[2])
        up=H-self.xyz[0,2];down=H-pos[2];dist=float(np.hypot(x,y))
        tout=up/4+dist/15+down/3
        tback=down/4+dist/15+up/3
        travel=1.15*(2*dist/15)/3600+23.5*G*(up+down)/(.72*3.6e6)
        e0=travel+1.1*30/3600
        dmax=(2.56-e0)*3600/1.1
        if dmax<=0:return None
        return dict(x=x,y=y,z=float(pos[2]),ground=ground,height=height,
                    lon=self.lon0+x/self.mx,lat=self.lat0+y/self.my,
                    cruise=H,out_s=tout,back_s=tback,travel_kwh=travel,e0=e0,
                    dmax=dmax,back_margin=back)

def gpu_screen(ctx,candidates,points):
    import torch
    t0=time.perf_counter()
    if torch.cuda.device_count()<2:
        raise RuntimeError("本次配置要求两张CUDA GPU；实际设备不足，不能虚报双GPU运行。")
    chunks=np.array_split(np.arange(len(candidates)),2)
    pos=np.array([[q["x"],q["y"],q["z"]] for q in candidates])
    def work(dev,indices):
        torch.cuda.set_device(dev);torch.cuda.reset_peak_memory_stats(dev)
        device=f"cuda:{dev}"
        dem=torch.as_tensor(ctx.dem,device=device)
        pts=torch.as_tensor(points,device=device,dtype=torch.float64)
        pts_rc=torch.as_tensor(np.array([ctx.raster(p) for p in points]),device=device)
        u=torch.linspace(0,1,257,device=device,dtype=torch.float64)[None,None,:]
        margins=[];count=0
        for start in range(0,len(indices),192):
            ix=indices[start:start+192]
            p=torch.as_tensor(pos[ix],device=device,dtype=torch.float64)
            rc=torch.as_tensor(np.array([ctx.raster(v) for v in pos[ix]]),device=device)
            cols=rc[:,None,0,None]+u*(pts_rc[None,:,0,None]-rc[:,None,0,None])
            rows=rc[:,None,1,None]+u*(pts_rc[None,:,1,None]-rc[:,None,1,None])
            zz=rc[:,None,2,None]+u*(pts_rc[None,:,2,None]-rc[:,None,2,None])
            cc=cols.floor().long().clamp(0,dem.shape[1]-1)
            rr=rows.floor().long().clamp(0,dem.shape[0]-1)
            blocked=(zz<=dem[rr,cc]+1e-6).any(2)
            dist=torch.linalg.vector_norm(p[:,None,:]-pts[None,:,:],dim=2).clamp_min(1e-6)/1000
            m=116-(32.45+20*math.log10(2400)+20*torch.log10(dist)+10*blocked)
            margins.append(m.cpu().numpy());count+=len(ix)*len(points)*257
        torch.cuda.synchronize(dev)
        return indices,np.vstack(margins),dict(device=dev,name=torch.cuda.get_device_name(dev),
                candidate_count=len(indices),ray_sample_evaluations=count,
                peak_allocated_bytes=torch.cuda.max_memory_allocated(dev),
                peak_reserved_bytes=torch.cuda.max_memory_reserved(dev),
                elapsed_s=time.perf_counter()-t0)
    matrix=np.empty((len(candidates),len(points)))
    records=[]
    with ThreadPoolExecutor(max_workers=2) as ex:
        for ix,m,rec in ex.map(lambda p:work(*p),enumerate(chunks)):
            matrix[ix]=m;records.append(rec)
    ctx.hardware["gpu"]=records
    return matrix

def prepare_candidates(ctx,keep=16):
    cache=OUT/"缓存/中继候选位置.json"
    if cache.exists():
        ctx.qs=load(cache)
        if not any(q["height"]<300 for q in ctx.qs):
            for old in list(ctx.qs[:4]):
                for h in (100.,200.):
                    q=ctx.relay_geometry(old["x"],old["y"],h)
                    if q:ctx.qs.append(dict(q,qid=f"Q{len(ctx.qs)+1:03d}"))
            save(cache,ctx.qs)
        h=OUT/"缓存/GPU位置筛选记录.json"
        if h.exists():ctx.hardware["gpu_cached_run"]=load(h)
        return ctx.qs
    cand=[]
    for x in np.arange(-7200,6801,400):
        for y in np.arange(-1200,9201,400):
            for h in (100.,200.,300.):
                # Backhaul worst-blockage range saves exact geometry work.
                q=ctx.relay_geometry(float(x),float(y),h)
                if q:cand.append(q)
    points=list(ctx.xyz[1:])
    for (i,j),g in ctx.geos.items():
        p=(ctx.xyz[i]+ctx.xyz[j])/2;p[2]=g["cruise"]
        points.append(p)
    points=np.array(points)
    m=gpu_screen(ctx,cand,points)
    np.savez_compressed(OUT/"缓存/GPU位置筛选矩阵.npz",margins=m,points=points)
    chosen=[]
    # Greedy coverage with geographical diversity; all 15 delivery positions
    # and many cruise positions enter the actual GPU calculation.
    weight=np.r_[np.ones(15)*12,np.ones(len(points)-15)]
    usage=np.zeros(len(points))
    for _ in range(keep):
        score=((m>=.3)*(weight/(1+usage)) + np.clip(m,0,25)*.001).sum(1)
        if chosen:
            d=np.min(np.linalg.norm(np.array([[q["x"],q["y"],q["height"]] for q in cand])[:,None,:]-
                   np.array([[cand[i]["x"],cand[i]["y"],cand[i]["height"]] for i in chosen])[None,:,:],axis=2),axis=1)
            score*=np.minimum(1.,d/500)
            score[chosen]=-1
        ix=int(np.argmax(score));chosen.append(ix);usage+=(m[ix]>=.3)
    # Add strongest certified access for every delivery point if screening
    # selected points do not cover that point under exact raster traversal.
    for p in ctx.xyz[1:]:
        if not any(ctx.point_margin(p,np.array([cand[i]["x"],cand[i]["y"],cand[i]["z"]]),116)>=0 for i in chosen):
            distances=np.linalg.norm(np.array([[q["x"],q["y"],q["z"]] for q in cand])-p,axis=1)
            for ix in np.argsort(distances):
                if ctx.point_margin(p,np.array([cand[ix]["x"],cand[ix]["y"],cand[ix]["z"]]),116)>=0:
                    chosen.append(int(ix));break
    ctx.qs=[dict(cand[i],qid=f"Q{j+1:03d}") for j,i in enumerate(chosen)]
    for old in list(ctx.qs[:4]):
        for h in (100.,200.):
            q=ctx.relay_geometry(old["x"],old["y"],h)
            if q:ctx.qs.append(dict(q,qid=f"Q{len(ctx.qs)+1:03d}"))
    save(cache,ctx.qs);save(OUT/"缓存/GPU位置筛选记录.json",ctx.hardware["gpu"])
    csv(OUT/"子问题一/中继候选位置.csv",ctx.qs)
    return ctx.qs

def certificate(ctx,a,b):
    dm,how=ctx.margin(a,b,ctx.gateway,122)
    margins=[]
    for q in ctx.qs:
        mu,_=ctx.margin(a,b,np.array([q["x"],q["y"],q["z"]]),116)
        margins.append(min(mu,q["back_margin"]))
    mask=sum(1<<i for i,m in enumerate(margins) if m>=0)
    return {"direct":dm>=0,"direct_lower":dm,"mask":mask,"margins":margins,"direct_method":how}

def prepare_geometry(ctx,step=200.):
    cache=OUT/"缓存/区间几何.json"
    if cache.exists():
        d=load(cache)
        if d["candidate_count"]==len(ctx.qs) and d["step_m"]==step:
            ctx.arc_cache={tuple(map(int,k.split(","))):v for k,v in d["arcs"].items()}
            ctx.node_cache={int(k):v for k,v in d["nodes"].items()}
            return
    t0=time.perf_counter()
    def work(key):
        i,j=key;g=ctx.geos[key]
        p0=ctx.xyz[i].copy();p1=p0.copy();p1[2]=g["cruise"]
        p3=ctx.xyz[j].copy();p2=p3.copy();p2[2]=g["cruise"]
        arcs=[]
        for name,a,b,dist in [("爬升",p0,p1,g["up"]),("巡航",p1,p2,g["distance"]),("下降",p2,p3,g["down"])]:
            if dist<1e-9:continue
            n=max(1,int(math.ceil(dist/(100 if name!="巡航" else step))))
            for h in range(n):
                aa=a+(b-a)*h/n;bb=a+(b-a)*(h+1)/n
                cert=certificate(ctx,aa,bb)
                # Refine only a currently unserviceable interval, preserving
                # full-interval certificates for every accepted child.
                todo=[(aa,bb,dist/n,cert,0)]
                while todo:
                    a0,b0,length,c,level=todo.pop(0)
                    if not c["direct"] and not c["mask"] and level<4:
                        mid=(a0+b0)/2
                        todo[:0]=[(a0,mid,length/2,certificate(ctx,a0,mid),level+1),
                                  (mid,b0,length/2,certificate(ctx,mid,b0),level+1)]
                    else:arcs.append(dict(phase=name,a=a0.tolist(),b=b0.tolist(),length=length,**c))
        return key,arcs
    # First call compiles the kernel before parallel traversal.
    ctx.margin(ctx.xyz[1],ctx.xyz[1],ctx.gateway,122)
    with ThreadPoolExecutor(max_workers=10) as ex:
        for key,arcs in ex.map(work,ctx.geos):
            ctx.arc_cache[key]=arcs
    for i,p in enumerate(ctx.xyz):
        ctx.node_cache[i]=certificate(ctx,p,p)
    save(cache,{"arcs":{f"{i},{j}":v for (i,j),v in ctx.arc_cache.items()},"nodes":ctx.node_cache,
                "step_m":step,"candidate_count":len(ctx.qs),"seconds":time.perf_counter()-t0})
    print("CERTIFICATE_GEOMETRY",len(ctx.arc_cache),len(ctx.qs),round(time.perf_counter()-t0,2),flush=True)

def profile(ctx,route,merge=True):
    v=ctx.vs[route["vehicle"]];t=route["prep_s"];records=[];needs=[]
    ids=[0]+[int(z[1:]) for z in route["zones"]]+[0]
    for h,(i,j) in enumerate(zip(ids,ids[1:])):
        for c in ctx.arc_cache[i,j]:
            speed=v.up if c["phase"]=="爬升" else v.down if c["phase"]=="下降" else v.speed
            dt=c["length"]/speed
            records.append(dict(c,t0=t,t1=t+dt,from_node=ctx.nodes.zone.iloc[i],to_node=ctx.nodes.zone.iloc[j]))
            t+=dt
        if j:
            n=sum(route["deliveries"][h]["counts"].values())
            dt=v.handoff0+n*v.handoff1
            records.append(dict(ctx.node_cache[j],phase="物资交接",a=ctx.xyz[j].tolist(),b=ctx.xyz[j].tolist(),
                                t0=t,t1=t+dt,from_node=ctx.nodes.zone.iloc[j],to_node=ctx.nodes.zone.iloc[j]))
            t+=dt
    if abs(t-route["duration"])>1e-5:raise ValueError(("route_duration_mismatch",route["route_id"],t,route["duration"]))
    for rec in records:
        if rec["direct"]:continue
        if not rec["mask"]:return None
        if merge and needs and needs[-1]["mask"]==rec["mask"] and abs(needs[-1]["t1"]-rec["t0"])<1e-7:
            needs[-1]["t1"]=rec["t1"]
        else:needs.append({k:rec[k] for k in ("t0","t1","mask")})
    return {"records":records,"needs":needs}

def make_route(ctx,vehicle,deliveries,uid=""):
    v=ctx.vs[vehicle];counts={};mass=vol=0.
    for d in deliveries:
        for c,n in d["counts"].items():
            counts[c]=counts.get(c,0)+n
            row=ctx.catinfo[c]
            mass+=row["mass"]*n;vol+=row["volume"]*n
    if mass>v.capacity+1e-8 or vol>v.volume+1e-8:return None
    nbox=sum(counts.values());prep=v.prep+v.load*nbox;t=prep;q=mass;energy=0.;segments=[];offsets={}
    zones=[d["zone"] for d in deliveries];ids=[0]+[int(z[1:]) for z in zones]+[0]
    for h,(i,j) in enumerate(zip(ids,ids[1:])):
        ss=q2.seg(v,ctx.geos[i,j],q);energy+=ss["energy"];t+=ss["time"]
        segments.append(dict(ss,**{"from":ctx.nodes.zone.iloc[i],"to":ctx.nodes.zone.iloc[j],"load":q}))
        if j:
            d=deliveries[h];t+=v.handoff0+sum(d["counts"].values())*v.handoff1
            for c,n in d["counts"].items():
                # Current generated routes visit each zone once. Repeated-zone
                # events need separate offsets and are outside this pool.
                offsets[c]=t
                q-=ctx.catinfo[c]["mass"]*n
    if energy>v.battery*.8+1e-8:return None
    latest=min([float(ctx.catinfo[c]["expected"])-off for c,off in offsets.items()
                if "医疗物资" in c]+[math.inf])
    if latest<0:return None
    r=dict(route_id=uid,vehicle=vehicle,zones=zones,counts=counts,deliveries=deliveries,
           mass=float(mass),volume=float(vol),nbox=nbox,prep_s=prep,duration=t,energy=energy,
           soc=1-energy/v.battery,charge_s=q2.charge(v,1-energy/v.battery),
           latest_start=latest,offsets=offsets,segments=segments)
    pr=profile(ctx,r)
    if pr is None:return None
    r["needs"]=pr["needs"]
    return r
