from q3_common import *
from q3_milp import solve_joint
from concurrent.futures import ThreadPoolExecutor,as_completed
if __name__=="__main__":
    ctx=Context();prepare_candidates(ctx);prepare_geometry(ctx)
    old=load(OUT/"缓存/问题二初始化快照.json")
    routes=[]
    for r in old["routes"]:
        rr=make_route(ctx,r["vehicle"],r["deliveries"],r["route_id"])
        if rr is None:raise RuntimeError(("legacy_route_not_covered",r["route_id"]))
        routes.append(rr)
    refs={r["route_id"]:r for r in old["routes"]}
    print("PILOT",len(routes),"NEEDS",sum(len(r["needs"]) for r in routes),flush=True)
    positions=[]
    for i,q in enumerate(ctx.qs):
        count=sum(bool(need["mask"]&(1<<i)) for r in routes for need in r["needs"])
        positions.append((i,count,q["x"],q["y"],q["height"]))
    print("POSITIONS",positions,flush=True)
    def worker(mode):
        p,meta=solve_joint(ctx,routes,required=[r["route_id"] for r in routes],reference=refs,
                           mode=mode,seconds=75,slots_per_uav=3)
        save(OUT/"日志"/f"pilot_{mode}.json",{"meta":meta,"plan":p})
        print("PILOT_RESULT",mode,p["objective"] if p else None,meta,flush=True)
    with ThreadPoolExecutor(max_workers=3) as ex:list(ex.map(worker,["C","L","N"]))
