"""Adaptive epsilon search with ALNS route/relay repairs and exact local MILPs."""
from q3_common import *
from q3_milp import solve_joint
import argparse,random,itertools,threading,copy
from concurrent.futures import ThreadPoolExecutor,as_completed
from scipy.optimize import linprog
LOCK=threading.RLock()
BOOK={};SIGNATURES={}
def register(ctx,g,ds):
    sig=(g,tuple((d["zone"],tuple(sorted(d["counts"].items()))) for d in ds))
    with LOCK:
        if sig in SIGNATURES:return BOOK[SIGNATURES[sig]]
    r=make_route(ctx,g,ds)
    if r is None:return None
    with LOCK:
        if sig in SIGNATURES:return BOOK[SIGNATURES[sig]]
        r["route_id"]=f"K{len(BOOK)+1:06d}";BOOK[r["route_id"]]=r;SIGNATURES[sig]=r["route_id"]
    return r
def nondom_add(archive,p):
    f=np.asarray(p["objective"])
    if any(np.all(np.asarray(a["objective"])<=f+1e-5) for a in archive):return False
    archive[:]=[a for a in archive if not(np.all(f<=np.asarray(a["objective"])+1e-5) and np.any(f<np.asarray(a["objective"])-1e-5))]
    archive.append(p);return True
def neighborhood(ctx,plan,rng,operator,pool_limit=48):
    routes=plan["routes"];count=min(len(routes),rng.choice([2,3,4]))
    if operator==0:removed=rng.sample(routes,count)
    elif operator==1:removed=sorted(routes,key=lambda r:len(r["needs"])*rng.uniform(.8,1.2),reverse=True)[:count]
    elif operator==2:removed=sorted(routes,key=lambda r:r["energy"]/r["nbox"]*rng.uniform(.8,1.2),reverse=True)[:count]
    else:
        target=rng.choice(plan["relays"])["slot"] if plan["relays"] else -1
        group=[r for r in routes if any(l["relay_slot"]==target for l in r["links"])]
        removed=rng.sample(group,min(count,len(group))) if group else rng.sample(routes,count)
    removed_ids={r["route_id"] for r in removed}
    outside=[r for r in routes if r["route_id"] not in removed_ids]
    remain={}
    for r in removed:
        for c,n in r["counts"].items():remain[c]=remain.get(c,0)+n
    options={r["route_id"]:BOOK.get(r["route_id"],r) for r in removed}
    for r in removed:
        for g in ctx.vs:
            rr=register(ctx,g,r["deliveries"])
            if rr:options[rr["route_id"]]=rr
        if len(r["zones"])>1:
            for d in r["deliveries"]:
                for g in ctx.vs:
                    rr=register(ctx,g,[d])
                    if rr:options[rr["route_id"]]=rr
            for ds in itertools.permutations(r["deliveries"]):
                rr=register(ctx,r["vehicle"],list(ds))
                if rr:options[rr["route_id"]]=rr
    parts={}
    for zone in sorted({c.split("|")[0] for c in remain}):
        cats=sorted(c for c in remain if c.startswith(zone+"|"))
        tuples=list(itertools.product(*(range(remain[c]+1) for c in cats)))
        rng.shuffle(tuples)
        # All one-box and full-region vectors plus a bounded randomized pool.
        vectors=[tuple(int(k==j) for k in range(len(cats))) for j in range(len(cats))]
        vectors += [tuple(remain[c] for c in cats)]+tuples[:24]
        for nums in vectors:
            cc={c:int(n) for c,n in zip(cats,nums) if n}
            if not cc:continue
            d={"zone":zone,"counts":cc}
            for g in ctx.vs:
                rr=register(ctx,g,[d])
                if rr:options[rr["route_id"]]=rr;parts.setdefault((zone,g),[]).append(rr)
    zones=sorted({c.split("|")[0] for c in remain})
    for _ in range(90):
        if len(zones)<2:break
        zz=rng.sample(zones,min(len(zones),rng.choice([2,2,3])))
        g=rng.choice(list(ctx.vs));ds=[]
        for z in zz:
            candidates=parts.get((z,g),[])
            if not candidates:break
            ds.extend(rng.choice(candidates)["deliveries"])
        if len(ds)!=len(zz):continue
        rr=register(ctx,g,ds)
        if rr:options[rr["route_id"]]=rr
    original=[BOOK.get(r["route_id"],r) for r in removed]
    rest=[r for rid,r in options.items() if rid not in removed_ids]
    rng.shuffle(rest)
    # Always retain incumbent routes; sample multiple structures rather than
    # pruning by Q1 energy dominance under changed resource constraints.
    optional=original+rest[:max(0,pool_limit-len(original))]
    final=[]
    outside_ids={r["route_id"] for r in outside}
    for r in optional:
        if r["route_id"] in outside_ids:continue
        if all(r["counts"].get(c,0)<=remain.get(c,0) for c in r["counts"]):final.append(r)
    pool=[BOOK.get(r["route_id"],r) for r in outside]+final
    return pool,{r["route_id"]:r for r in outside},len(removed)

def relax_bound(ctx,book,caps=None,weight=None,scale=None,ideal=None):
    """Valid outer relaxation: empty communication sample set, then drop all
    precedence/relay constraints and retain category coverage and fleet workload.
    This bounds the continuous-communication problem only within this route pool.
    """
    routes=list(book.values());n=len(routes);cats=sorted(ctx.boxes.category.unique())
    Aeq=np.zeros((len(cats),n+1));beq=np.zeros(len(cats))
    for h,c in enumerate(cats):
        beq[h]=sum(ctx.boxes.category==c)
        for i,r in enumerate(routes):Aeq[h,i]=r["counts"].get(c,0)
    Aub=[];bub=[]
    for g,ng in [("A",4),("B",2),("C",2)]:
        row=np.zeros(n+1)
        for i,r in enumerate(routes):
            if r["vehicle"]==g:row[i]=r["duration"]
        row[-1]=-ng;Aub.append(row);bub.append(0.)
    if caps:
        for key in ("N","E"):
            if caps.get(key) is not None:
                row=np.r_[np.ones(n) if key=="N" else [r["energy"] for r in routes],0.]
                Aub.append(row);bub.append(caps[key])
    c=np.zeros(n+1)
    offset=0.
    if weight is None:c[-1]=1
    else:
        c[:n]=weight[0]/scale[0]+weight[1]/scale[1]*np.array([r["energy"] for r in routes])
        c[-1]=weight[2]/scale[2]
        offset=-float(weight@(ideal/scale))
    res=linprog(c,A_ub=np.array(Aub),b_ub=bub,A_eq=Aeq,b_eq=beq,bounds=[(0,1)]*n+[(0,30000)],method="highs",options={"time_limit":30})
    return float(res.fun+offset) if res.success else None

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--iterations",type=int,default=8);ap.add_argument("--workers",type=int,default=4)
    ap.add_argument("--repair-seconds",type=float,default=12);ap.add_argument("--anchor-seconds",type=float,default=40)
    args=ap.parse_args();start=time.perf_counter()
    ctx=Context();prepare_candidates(ctx);prepare_geometry(ctx)
    old=load(OUT/"缓存/问题二初始化快照.json");initial=[];refs={}
    for r in old["routes"]:
        rr=register(ctx,r["vehicle"],r["deliveries"])
        if rr is None:raise RuntimeError(("initial_route_uncovered",r["route_id"]))
        initial.append(rr);refs[rr["route_id"]]=dict(r,route_id=rr["route_id"])
    logs=[];allplans=[];archive=[]
    def anchor(mode):
        p,meta=solve_joint(ctx,initial,required=[r["route_id"] for r in initial],reference=refs,
                           mode=mode,seconds=args.anchor_seconds,lex=True,slots_per_uav=3)
        return mode,p,meta
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for mode,p,meta in ex.map(anchor,["C","L","E","N"]):
            logs.append(dict(kind="anchor",**meta))
            if p:p["source"]="anchor_"+mode;allplans.append(p);nondom_add(archive,p)
            print("ANCHOR",mode,p["objective"] if p else None,flush=True)
    if not archive:save(OUT/"日志/失败日志.json",logs);raise RuntimeError("无联合可行初值")
    anchorF=np.array([p["objective"] for p in allplans])
    ideal=anchorF.min(0);scale=np.maximum(np.ptp(anchorF,axis=0),[2.,5.,1800.,600.])
    save(OUT/"子问题一/冻结比较尺度.json",{"ideal_reference":ideal,"scale":scale,"delta":.3,"center":[.25]*4})
    save(OUT/"子问题一/初始侧重方案.json",allplans)
    # The caps for the next wave use the observed archive. They are updated
    # after each wave; this is an adaptive epsilon exploration, not weighted
    # objective draws relabelled as epsilon scenarios.
    for wave in range(2):
        ff=np.array([p["objective"] for p in archive])
        scenarios=[
            {"N":float(ff[:,0].min()+1),"E":float(ff[:,1].max()+.5),"L":float(ff[:,3].max()+100)},
            {"N":float(ff[:,0].max()+2),"E":float((ff[:,1].min()+ff[:,1].max())/2),"L":float(ff[:,3].max()+300)},
            {"N":float(ff[:,0].min()),"E":float(ff[:,1].max()+1),"L":float(ff[:,3].min()+10)},
            {"N":float(ff[:,0].min()-1),"E":float(ff[:,1].max()+2),"L":float(ff[:,3].max()+500)}]
        basepool=list(archive)
        def alns(job):
            idx,caps=job;seed=202631+wave*10+idx;rng=random.Random(seed)
            feasible=[p for p in basepool if all(p["objective"][{"N":0,"E":1,"L":3}[k]]<=v+1e-5 for k,v in caps.items())]
            current=copy.deepcopy(min(feasible or basepool,key=lambda p:p["objective"][2]))
            local=[];history=[];weights=np.ones(4);scores=np.zeros(4);counts=np.zeros(4)
            for it in range(args.iterations):
                op=rng.choices(range(4),weights=weights,k=1)[0]
                if it and it%4==0:
                    # Reopen all transport times and assignments jointly with
                    # all relay decisions, keeping current routes as required.
                    pool=[BOOK.get(r["route_id"],r) for r in current["routes"]]
                    p,meta=solve_joint(ctx,pool,required=[r["route_id"] for r in pool],mode="C",caps=caps,
                         seconds=args.repair_seconds,slots_per_uav=3,lex=False)
                    removed=len(pool);label="global_resource_retime"
                else:
                    pool,frozen,removed=neighborhood(ctx,current,rng,op)
                    p,meta=solve_joint(ctx,pool,frozen=frozen,mode="C",caps=caps,
                         seconds=args.repair_seconds,slots_per_uav=3,lex=False)
                    label=["random","communication","energy","relay_linked"][op]
                reward=0.
                if p:
                    p["source"]=f"seed{seed}_iter{it}_{label}";local.append(p)
                    improvement=(current["objective"][2]-p["objective"][2])/scale[2]
                    if improvement>=-1e-8 or rng.random()<math.exp(min(0.,improvement/max(.02,.3*(1-it/args.iterations)))):
                        current=p;reward=3. if improvement>1e-5 else 1.
                    reward+=.5  # Additional credit for a feasible repair.
                counts[op]+=1;scores[op]+=reward
                weights[op]=.8*weights[op]+.2*max(.15,scores[op]/counts[op])
                history.append(dict(kind="ALNS",wave=wave,seed=seed,iteration=it,operator=label,removed=removed,
                    feasible=p is not None,objective=p["objective"] if p else None,operator_weights=weights.tolist(),**meta))
                print("ALNS",wave,seed,it,label,p["objective"] if p else "no_incumbent",flush=True)
            return local,history
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for pp,ll in ex.map(alns,list(enumerate(scenarios))):
                logs.extend(ll)
                for p in pp:allplans.append(p);nondom_add(archive,p)
        save(OUT/"子问题一/中间非支配档案.json",archive)
        save(OUT/"日志/搜索记录.json",logs)
    # Final fixed-route polishing of each current nondominated structure.
    candidates=list(archive)
    def polish(p):
        rr=[BOOK.get(r["route_id"],r) for r in p["routes"]]
        new,meta=solve_joint(ctx,rr,required=[r["route_id"] for r in rr],reference={r["route_id"]:r for r in p["routes"]},
                            caps={"N":p["objective"][0],"E":p["objective"][1]+1e-6,"L":p["objective"][3]+1e-5},
                            seconds=35,lex=True,slots_per_uav=3)
        return new,meta
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for p,meta in ex.map(polish,candidates):
            logs.append(dict(kind="final_polish",**meta))
            if p:p["source"]="final_polish";allplans.append(p);nondom_add(archive,p)
    save(OUT/"子问题一/累计候选路线.json",list(BOOK.values()))
    weights=[]
    for i,j in itertools.permutations(range(4),2):
        w=np.ones(4)/4;w[i]+=.15;w[j]-=.15;weights.append(w)
    F=np.array([p["objective"] for p in archive]);norm=(F-ideal)/scale
    base=np.array([min(norm@w) for w in weights])
    lbs=[]
    for w in weights:lbs.append(relax_bound(ctx,BOOK,weight=w,scale=scale,ideal=ideal))
    for i,p in enumerate(archive):
        regrets=np.array([norm[i]@w-v for w,v in zip(weights,base)])
        p["regret_archive"]=float(max(regrets))
        p["regret_lower"]=max(0.,p["regret_archive"])
        p["regret_upper"]=float(max(norm[i]@w-lb for w,lb in zip(weights,lbs))) if all(x is not None for x in lbs) else None
    final=min(archive,key=lambda p:(p["regret_upper"] if p["regret_upper"] is not None else p["regret_archive"],p["objective"][2]))
    save(OUT/"子问题一/非支配方案明细.json",archive)
    save(OUT/"子问题一/全部可行搜索方案.json",allplans)
    save(OUT/"子问题一/偏好极点与有效下界.json",{"weights":weights,"archive_baselines":base,"outer_relaxation_lower_bounds":lbs,
         "scope":"累计路线库内：空通信采样集外松弛，进一步放松资源顺序与整数性；不是全路线全局下界"})
    final["completion_time_lower_bound"]=relax_bound(ctx,BOOK,caps={"N":final["objective"][0],"E":final["objective"][1],"L":final["objective"][3]})
    save(OUT/"子问题二/最终方案_待独立核验.json",final)
    save(OUT/"日志/搜索记录.json",logs)
    save(OUT/"求解运行配置.json",dict(vars(args),seeds=list(range(202631,202635))+list(range(202641,202645)),
         position_count=len(ctx.qs),height_levels=sorted({q["height"] for q in ctx.qs}),slots_per_relay=3,search_horizon_s=30000,
         route_count=len(BOOK),elapsed_s=time.perf_counter()-start,feasible_count=len(allplans),archive_count=len(archive)))
    print("FINAL_UNVERIFIED",final["objective"],"ARCHIVE",len(archive),"ROUTES",len(BOOK),"SECONDS",time.perf_counter()-start,flush=True)
if __name__=="__main__":main()
