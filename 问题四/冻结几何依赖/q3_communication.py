"""DEM event construction and direct-first communication export.

A swept link is a triangle. Barycentric coordinates (n,d) give the motion
parameter u=n/d. Clipping this triangle to each closed DEM prism yields the
entire blocked-u interval for that pixel. No temporal sampling is used to
certify feasibility. Distance-sphere intersections supply the other events.
"""
from q3_common import *
from verify_q3 import Verifier

@njit(cache=True,nogil=True)
def clip5(p,n,axis,bound,lower):
    out=np.empty((24,5),np.float64);m=0
    if n==0:return out,0
    a=p[n-1].copy();inside=a[axis]>=bound if lower else a[axis]<=bound
    for i in range(n):
        b=p[i];other=b[axis]>=bound if lower else b[axis]<=bound
        if inside!=other:
            den=b[axis]-a[axis]
            if abs(den)>1e-20:
                out[m]=a+(bound-a[axis])/den*(b-a);m+=1
        if other:out[m]=b;m+=1
        a=b.copy();inside=other
    return out,m

@njit(cache=True,nogil=True)
def blocked_events(a,b,q,dem,nodata):
    tri=np.zeros((24,5),np.float64)
    tri[0,:3]=q;tri[1,:3]=a;tri[2,:3]=b
    tri[1,4]=1.;tri[2,3]=1.;tri[2,4]=1.
    intervals=[];eps=1e-8
    low=max(0,int(math.floor(min(a[1],b[1],q[1])-eps)))
    high=min(dem.shape[0]-1,int(math.floor(max(a[1],b[1],q[1])+eps)))
    for r in range(low,high+1):
        p,n=clip5(tri,3,1,r-eps,True);p,n=clip5(p,n,1,r+1+eps,False)
        if n==0:continue
        xmin=p[0,0];xmax=xmin;zmin=p[0,2]
        for i in range(n):xmin=min(xmin,p[i,0]);xmax=max(xmax,p[i,0]);zmin=min(zmin,p[i,2])
        for c in range(max(0,int(math.floor(xmin-eps))),min(dem.shape[1]-1,int(math.floor(xmax+eps)))+1):
            h=dem[r,c]
            if not np.isfinite(h) or h==nodata:h=1e12
            if h+1e-6<zmin:continue
            pc,nc=clip5(p,n,0,c-eps,True);pc,nc=clip5(pc,nc,0,c+1+eps,False)
            pc,nc=clip5(pc,nc,2,h+1e-6,False)
            if nc==0:continue
            lo=1.;hi=0.;found=False
            for k in range(nc):
                if pc[k,4]>1e-14:
                    u=pc[k,3]/pc[k,4];lo=min(lo,u);hi=max(hi,u);found=True
            if found:intervals.append((max(0.,lo),min(1.,hi)))
    return intervals

def merged(intervals):
    out=[]
    for a,b in sorted(intervals):
        if out and a<=out[-1][1]+1e-12:out[-1][1]=max(b,out[-1][1])
        else:out.append([a,b])
    return out

def sphere_events(a,b,q,radius):
    v=b-a;w=a-q;aa=float(v@v)
    if aa<1e-18:return []
    bb=2*float(v@w);cc=float(w@w)-radius**2;disc=bb*bb-4*aa*cc
    if disc<0:return []
    return [u for u in [(-bb-math.sqrt(disc))/(2*aa),(-bb+math.sqrt(disc))/(2*aa)] if 0<u<1]

def event_partition(v,st):
    a=np.array(st['a']);b=np.array(st['b']);q=v.gateway
    d0=1000*10**((122-32.45-20*math.log10(2400))/20)
    d1=d0/10**.5
    if max(np.linalg.norm(a-q),np.linalg.norm(b-q))<=d1:
        return [0.,1.],[]
    blocked=merged(blocked_events(v.raster(a),v.raster(b),v.raster(q),v.dem,v.nodata))
    events=[0.,1.]+[t for ab in blocked for t in ab]+sphere_events(a,b,q,d0)+sphere_events(a,b,q,d1)
    return sorted(set(events)),blocked

def export_communication(plan):
    v=Verifier(plan);rows=[];certs=[];cache={};sample=[]
    relays={r['slot']:r for r in plan['relays']}
    for r in plan['routes']:
        stages,_,_,_=v.route_stages(r)
        for phaseidx,st in enumerate(stages):
            a=np.array(st['a']);b=np.array(st['b']);dur=st['t1']-st['t0']
            key=tuple(a)+tuple(b)
            if key not in cache:cache[key]=event_partition(v,st)
            events,blocked=cache[key];times=[st['t0']+u*dur for u in events]
            links=[dict(l,t0=l['t0']+r['start'],t1=l['t1']+r['start']) for l in r['links']]
            times += [max(st['t0'],min(st['t1'],l[k])) for l in links for k in ['t0','t1'] if st['t0']<l[k]<st['t1']]
            times=sorted(set(times))
            for t0,t1 in zip(times,times[1:]):
                if t1-t0<1e-9:continue
                mid=(t0+t1)/2;p=v.position(st,mid)
                mu,clear=v.link_margin_q(p,p,v.gateway,122)
                relayid='';source='直连'
                if mu < -1e-7:
                    found=[l for l in links if l['t0']<=mid+2e-4 and l['t1']>=mid-2e-4]
                    if not found:raise RuntimeError(('no relay event',r['route_id'],t0,t1))
                    relay=relays[found[0]['relay_slot']];relayid=relay['relay_id'];source='中继'
                rec=dict(route_id=r['route_id'],phase=st['phase'],t0=t0,t1=t1,mode=source,relay_id=relayid)
                # Adjacent pieces with the same provider/phase are merged.
                if rows and all(rows[-1][k]==rec[k] for k in ['route_id','phase','mode','relay_id']) and abs(rows[-1]['t1']-t0)<1e-7:
                    rows[-1]['t1']=t1
                else:rows.append(rec)
            # Explicit event-point checks resolve closed DEM contacts and
            # direct-first switches without a hidden endpoint gap.
            for t in times:
                p=v.position(st,t);md,_=v.link_margin_q(p,p,v.gateway,122)
                chosen='G01';margin=md
                if md < -1e-7:
                    found=[l for l in links if l['t0']<=t+2e-4 and l['t1']>=t-2e-4]
                    chosen=None
                    for lk in found:
                        rr=relays[lk['relay_slot']];q=np.array([rr['position'][k] for k in ['x','y','z']])
                        ma,_=v.link_margin_q(p,p,q,116);mb,_=v.link_margin_q(q,q,v.gateway,126)
                        if min(ma,mb)>=-1e-6 and rr['alpha']<=t+2e-4 and rr['beta']>=t-2e-4:
                            chosen=rr['relay_id'];margin=min(ma,mb);break
                    if chosen is None:raise RuntimeError(('endpoint failure',r['route_id'],t))
                certs.append(dict(route_id=r['route_id'],time_s=t,provider=chosen,margin_dB=margin))
            for t in np.linspace(st['t0'],st['t1'],max(2,int(dur/10)+1)):
                p=v.position(st,t);md,_=v.link_margin_q(p,p,v.gateway,122)
                sample.append(dict(route_id=r['route_id'],time_s=t,direct_margin_dB=md,phase=st['phase']))
    save(OUT/'子问题二/通信状态分段.json',rows)
    csv(OUT/'子问题二/通信事件端点核验.csv',certs)
    csv(OUT/'子问题二/直连裕量展示采样.csv',sample)
    save(OUT/'子问题二/通信事件核验摘要.json',dict(status='PASS',event_points=len(certs),
         rows=len(rows),direct_duration_s=sum(r['t1']-r['t0'] for r in rows if r['mode']=='直连'),
         relay_duration_s=sum(r['t1']-r['t0'] for r in rows if r['mode']=='中继'),
         note='表中区间内部状态由地形事件和距离球交点分割；精确边界保障主体以事件端点表为准，均已单独核验。展示采样不作为连续证书。'))
    return rows

if __name__=='__main__':
    p=load(OUT/'子问题二/最终方案_待独立核验.json')
    rows=export_communication(p)
    print('COMMUNICATION',len(rows),flush=True)
