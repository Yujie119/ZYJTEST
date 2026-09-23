"""Joint transport/relay MILP used for initialization and ALNS repairs."""
from q3_common import *
from scipy.optimize import milp, Bounds, LinearConstraint, linprog
from scipy.sparse import coo_matrix
import warnings,itertools
UAV={"A":["U01","U02","U03","U04"],"B":["U05","U06"],"C":["U07","U08"]}
BAT={g:[f"{g}-BAT-{i:02d}" for i in range(1,n+1)] for g,n in [("A",6),("B",4),("C",4)]}

class LinearModel:
    def __init__(self):self.names=[];self.lo=[];self.hi=[];self.integer=[];self.rows=[];self.lower=[];self.upper=[]
    def var(self,name,lo=0,hi=math.inf,integer=False):
        i=len(self.names);self.names.append(name);self.lo.append(lo);self.hi.append(hi);self.integer.append(int(integer));return i
    def add(self,co,lo=-math.inf,hi=math.inf):
        self.rows.append({i:v for i,v in co.items() if abs(v)>1e-14});self.lower.append(lo);self.upper.append(hi)
    def eq(self,co,value=0):self.add(co,value,value)
    def matrix(self):
        rr=[];cc=[];vv=[]
        for i,row in enumerate(self.rows):
            for j,v in row.items():rr.append(i);cc.append(j);vv.append(v)
        return coo_matrix((vv,(rr,cc)),shape=(len(self.rows),len(self.names))).tocsc()
    def run(self,c,seconds,relax=False):
        cost=np.zeros(len(self.names))
        for i,v in c.items():cost[i]=v
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return milp(cost,integrality=np.zeros(len(self.names)) if relax else self.integer,
                bounds=Bounds(self.lo,self.hi),
                constraints=LinearConstraint(self.matrix(),self.lower,self.upper),
                options={"time_limit":seconds,"mip_rel_gap":.003,"threads":1,
                         "mip_feasibility_tolerance":1e-8,"primal_feasibility_tolerance":1e-8})

def solve_joint(ctx,routes,required=None,reference=None,frozen=None,mode="C",caps=None,
                seconds=30.,slots_per_uav=3,component_count=6,position_ids=None,lex=False):
    """All route/relay coefficients are certified. Required routes are selected;
    reference fixes only transport resource identities/order, frozen fixes entire
    external transport events for a bounded ALNS repair.
    Relay positions, service times, components remain decision variables.
    """
    started=time.perf_counter();M=50000.;H=30000.
    m=LinearModel();n=len(routes);qn=len(ctx.qs);J=2*slots_per_uav
    required=set(required or []);frozen=frozen or {};reference=reference or {}
    position_ids=list(range(qn)) if position_ids is None else list(position_ids)
    x=[];st=[];u={};b={};late={}
    for i,r in enumerate(routes):
        rid=r["route_id"];force=rid in required or rid in frozen
        x.append(m.var(("x",i),int(force),1,True))
        latest=min(H-r["duration"],r["latest_start"])
        st.append(m.var(("s",i),0,max(0,latest)))
        m.add({st[i]:1,x[i]:-max(0,latest)},hi=0)
        ref=frozen.get(rid,reference.get(rid))
        if rid in frozen:m.lo[st[i]]=m.hi[st[i]]=ref["start"]
        for d in UAV[r["vehicle"]]:
            u[i,d]=m.var(("u",i,d),0,1,True)
            if ref:m.eq({u[i,d]:1,x[i]:-(d==ref["uav"])})
        for p in BAT[r["vehicle"]]:
            b[i,p]=m.var(("b",i,p),0,1,True)
            if ref:m.eq({b[i,p]:1,x[i]:-(p==ref["battery_id"])})
        co={u[i,d]:1 for d in UAV[r["vehicle"]]};co[x[i]]=-1;m.eq(co)
        co={b[i,p]:1 for p in BAT[r["vehicle"]]};co[x[i]]=-1;m.eq(co)
    # Exact category counts plus explicit first-batch selection; named boxes
    # are assigned afterwards to equivalent slots, hard boxes first.
    for cat,group in ctx.boxes.groupby("category"):
        ix=[i for i,r in enumerate(routes) if r["counts"].get(cat,0)>0]
        if not ix:return None,{"reason":"uncovered_category","category":cat}
        m.eq({x[i]:routes[i]["counts"][cat] for i in ix},len(group))
        first=group[group["first"]=="是"]
        if len(first):
            h=[]
            for i in ix:
                v=m.var(("first",cat,i),0,1,True);h.append(v)
                m.add({v:1,x[i]:-1},hi=0)
                m.add({st[i]:1,v:M},hi=M+float(first.iloc[0].first_deadline)-routes[i]["offsets"][cat])
            m.eq({v:1 for v in h},1)
    # One total-time order bit per same-type pair is shared by UAV/battery
    # conflicts. With positive task lengths their real chronological order
    # must agree whenever either resource is shared.
    for i,j in itertools.combinations(range(n),2):
        if routes[i]["vehicle"]!=routes[j]["vehicle"]:continue
        oi=m.var(("order",i,j),0,1,True)
        ri=reference.get(routes[i]["route_id"],frozen.get(routes[i]["route_id"]))
        rj=reference.get(routes[j]["route_id"],frozen.get(routes[j]["route_id"]))
        if ri and rj and (ri["uav"]==rj["uav"] or ri["battery_id"]==rj["battery_id"]):
            m.lo[oi]=m.hi[oi]=float(ri["start"]<=rj["start"])
        for kind,res,table in [("U",UAV[routes[i]["vehicle"]],u),("P",BAT[routes[i]["vehicle"]],b)]:
            ti=routes[i]["duration"]+(routes[i]["charge_s"] if kind=="P" else 0)
            tj=routes[j]["duration"]+(routes[j]["charge_s"] if kind=="P" else 0)
            for d in res:
                m.add({st[i]:1,st[j]:-1,table[i,d]:M,table[j,d]:M,oi:M},hi=3*M-ti)
                m.add({st[j]:1,st[i]:-1,table[i,d]:M,table[j,d]:M,oi:-M},hi=2*M-tj)
    C=m.var("C",0,H);N={xx:1 for xx in x};E={x[i]:r["energy"] for i,r in enumerate(routes)};L={}
    denom=float(ctx.boxes.loc[~ctx.boxes.hard,"priority"].sum())
    for i,r in enumerate(routes):
        m.add({st[i]:1,x[i]:r["duration"],C:-1},hi=0)
        for cat,nc in r["counts"].items():
            row=ctx.boxes[ctx.boxes.category==cat].iloc[0]
            if row.kind=="医疗物资":continue
            ll=m.var(("late",i,cat),0,H);late[i,cat]=ll
            m.add({st[i]:1,x[i]:r["offsets"][cat],ll:-1},hi=float(row.expected))
            m.add({ll:1,x[i]:-H},hi=0)
            L[ll]=nc*float(row.priority)/denom
    y=[];rs=[];alpha=[];beta=[];rf=[];dur=[];en=[];chg=[];z={};cp={}
    for j in range(J):
        y.append(m.var(("relay_on",j),0,1,True));N[y[j]]=1
        rs.append(m.var(("relay_start",j),0,H))
        alpha.append(m.var(("alpha",j),0,H));beta.append(m.var(("beta",j),0,H))
        rf.append(m.var(("relay_finish",j),0,H))
        dur.append(m.var(("duration",j),0,9000))
        en.append(m.var(("energy",j),0,2.56));E[en[j]]=1
        chg.append(m.var(("charge",j),0,1540))
        for vv,upper in [(rs[j],H),(rf[j],H),(en[j],2.56),(chg[j],1540)]:
            m.add({vv:1,y[j]:-upper},hi=0)
        for q in position_ids:z[j,q]=m.var(("position",j,q),0,1,True)
        co={z[j,q]:1 for q in position_ids};co[y[j]]=-1;m.eq(co)
        co={alpha[j]:1,rs[j]:-1}
        for q in position_ids:co[z[j,q]]=-(180+ctx.qs[q]["out_s"]+30)
        m.eq(co);m.eq({beta[j]:1,alpha[j]:-1,dur[j]:-1})
        co={rf[j]:1,beta[j]:-1}
        for q in position_ids:co[z[j,q]]=-ctx.qs[q]["back_s"]
        m.eq(co)
        co={en[j]:1,dur[j]:-1.1/3600}
        for q in position_ids:co[z[j,q]]=-ctx.qs[q]["e0"]
        m.eq(co)
        co={dur[j]:1}
        for q in position_ids:co[z[j,q]]=-ctx.qs[q]["dmax"]
        m.add(co,hi=0)
        m.add({rf[j]:1,C:-1},hi=0)
        # Exact two-branch encoding, equivalent to the manuscript's SOS2.
        branch=m.var(("charge_branch",j),0,1,True)
        m.add({branch:1,y[j]:-1},hi=0)
        m.add({en[j]:1,y[j]:-.32,branch:-2.24},hi=0)
        m.add({en[j]:1,branch:-.32},lo=0)
        for sign in (1,-1):
            m.add({chg[j]:sign,en[j]:-1968.75*sign,branch:-6000},hi=0)
            m.add({chg[j]:sign,en[j]:-406.25*sign,y[j]:-500*sign-6000,branch:6000},hi=0)
        for p in range(component_count):cp[j,p]=m.var(("component",j,p),0,1,True)
        co={cp[j,p]:1 for p in range(component_count)};co[y[j]]=-1;m.eq(co)
        if j%slots_per_uav:
            m.add({y[j]:1,y[j-1]:-1},hi=0)
            m.add({rf[j-1]:1,rs[j]:-1,y[j]:M},hi=M-300)
    # Identical relay bodies/components permit these label symmetries.
    m.add({y[slots_per_uav]:1,y[0]:-1},hi=0)
    m.eq({cp[0,0]:1,y[0]:-1})
    for j,l in itertools.combinations(range(J),2):
        order=m.var(("component_order",j,l),0,1,True)
        if j//slots_per_uav==l//slots_per_uav:m.lo[order]=m.hi[order]=1
        for p in range(component_count):
            m.add({rf[j]:1,chg[j]:1,rs[l]:-1,cp[j,p]:M,cp[l,p]:M,order:M},hi=3*M)
            m.add({rf[l]:1,chg[l]:1,rs[j]:-1,cp[j,p]:M,cp[l,p]:M,order:-M},hi=2*M)
    xis={};support={j:[] for j in range(J)}
    for i,r in enumerate(routes):
        for h,need in enumerate(r["needs"]):
            allowed=[q for q in position_ids if need["mask"]&(1<<q)]
            if not allowed:
                if m.lo[x[i]]==1:return None,{"reason":"selected_positions_cannot_cover","route":r["route_id"]}
                m.hi[x[i]]=0;continue
            vv=[]
            for j in range(J):
                v=m.var(("cover",i,h,j),0,1,True);xis[i,h,j]=v;vv.append(v);support[j].append(v)
                co={v:1}
                for q in allowed:co[z[j,q]]=-1
                m.add(co,hi=0)
                m.add({alpha[j]:1,st[i]:-1,v:M},hi=M+need["t0"])
                m.add({st[i]:1,beta[j]:-1,v:M},hi=M-need["t1"])
            co={v:1 for v in vv};co[x[i]]=-1;m.eq(co)
    for j in range(J):
        co={y[j]:1}
        for v in support[j]:co[v]=-1
        m.add(co,hi=0)
    objectives={"N":N,"E":E,"C":{C:1},"L":L}
    for key,value in (caps or {}).items():
        if value is not None:m.add(objectives[key],hi=float(value))
    order=[mode]+([k for k in ("C","L","E","N") if k!=mode] if lex else [])
    best=None;logs=[]
    for stage in order:
        remaining=seconds-(time.perf_counter()-started)
        if remaining<.1:break
        res=m.run(objectives[stage],remaining/max(1,len(order)-len(logs)))
        log=dict(stage=stage,status=int(res.status),message=res.message,
                 incumbent_available=res.x is not None,
                 bound=getattr(res,"mip_dual_bound",None),gap=getattr(res,"mip_gap",None))
        logs.append(log)
        if res.x is None:break
        best=res.x
        val=sum(best[k]*v for k,v in objectives[stage].items())
        m.add(objectives[stage],hi=val+max(1e-5,abs(val)*1e-7))
    meta=dict(seconds=time.perf_counter()-started,variables=len(m.names),constraints=len(m.rows),
              stages=logs,route_pool=len(routes),required=len(required),mode=mode,caps=caps,
              model_scope="certified finite route/position/relay-slot model; 30000s search horizon")
    if best is None:return None,meta
    # Reject solver incumbents outside numerical feasibility tolerances.
    ax=m.matrix()@best
    violation=max(float(np.max(np.maximum(np.array(m.lower)-ax,0))),
                  float(np.max(np.maximum(ax-np.array(m.upper),0))))
    meta["max_constraint_violation"]=violation
    if violation>2e-4:return None,dict(meta,rejected="constraint_violation")
    transports=[];relay=[]
    for i,r in enumerate(routes):
        if best[x[i]]<.5:continue
        start=max(0.,float(best[st[i]]));finish=start+r["duration"]
        ui=max(UAV[r["vehicle"]],key=lambda d:best[u[i,d]])
        bi=max(BAT[r["vehicle"]],key=lambda p:best[b[i,p]])
        links=[]
        for h,need in enumerate(r["needs"]):
            j=max(range(J),key=lambda j:best[xis[i,h,j]])
            links.append(dict(need,relay_slot=j))
        transports.append(dict(r,start=start,takeoff=start+r["prep_s"],finish=finish,
            recharge=finish+r["charge_s"],uav=ui,battery_id=bi,links=links))
    for j in range(J):
        if best[y[j]]<.5:continue
        q=max(position_ids,key=lambda q:best[z[j,q]])
        start=max(0.,float(best[rs[j]]));duration=max(0.,float(best[dur[j]]))
        qq=ctx.qs[q];aa=start+180+qq["out_s"]+30;bb=aa+duration;ff=bb+qq["back_s"]
        energy=qq["e0"]+1.1*duration/3600
        soc=1-energy/3.2
        chi=1800*(.65*(.9-soc)/.9+.35) if soc<.9 else 1800*.35*(1-soc)/.1
        p=max(range(component_count),key=lambda p:best[cp[j,p]])
        relay.append(dict(slot=j,relay_id=f"Q3-R{j+1:03d}",uav=f"R{j//slots_per_uav+1:02d}",
             component=f"R-EC-{p+1:02d}",qid=q,position=qq,start=start,takeoff=start+180,
             arrival=start+180+qq["out_s"],alpha=aa,beta=bb,finish=ff,duration=duration,
             energy=energy,soc=soc,charge_s=chi,recharge=ff+chi,body_ready=ff+300))
    slots={}
    for r in transports:
        for cat,nc in r["counts"].items():
            slots.setdefault(cat,[]).extend([(r,r["start"]+r["offsets"][cat])]*nc)
    boxes=[]
    for cat,group in ctx.boxes.groupby("category"):
        bb=group.sort_values(["hard","deadline","box"],ascending=[False,True,True]).to_dict("records")
        ss=sorted(slots.get(cat,[]),key=lambda v:v[1])
        if len(bb)!=len(ss):return None,dict(meta,rejected="box_coverage")
        for box,(r,tt) in zip(bb,ss):
            boxes.append(dict(box,route_id=r["route_id"],delivery=tt,uav=r["uav"],battery_id=r["battery_id"]))
    if any(b["hard"] and b["delivery"]>b["deadline"]+2e-4 for b in boxes):
        return None,dict(meta,rejected="hard_deadline")
    NT=len(transports);NR=len(relay);ET=sum(r["energy"] for r in transports);ER=sum(j["energy"] for j in relay)
    actualL=sum(b["priority"]*max(0.,b["delivery"]-b["expected"]) for b in boxes if not b["hard"])/denom
    actualC=max([r["finish"] for r in transports]+[j["finish"] for j in relay])
    plan=dict(routes=sorted(transports,key=lambda r:r["start"]),relays=relay,boxes=boxes,
              objective=[NT+NR,ET+ER,actualC,actualL],NT=NT,NR=NR,ET=ET,ER=ER,meta=meta)
    return plan,meta

