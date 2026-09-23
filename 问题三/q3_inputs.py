"""Independent Q3 input layer; no runtime imports from mutable Q1/Q2 solvers."""
import os
os.environ["MKL_THREADING_LAYER"]="SEQUENTIAL"
for k in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS"):os.environ[k]="1"
import math,itertools
from pathlib import Path
from dataclasses import dataclass
import numpy as np,pandas as pd
from scipy.io import loadmat
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"D题/数据/无人机应急物资运输基础数据"
def jr(x):
    if isinstance(x,np.ndarray):return x.tolist()
    if isinstance(x,(np.integer,np.floating)):return x.item()
    if isinstance(x,Path):return str(x)
    if isinstance(x,dict):return {str(k):jr(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [jr(v) for v in x]
    return x
def local_xy(lon,lat,lon0,lat0):
    phi=np.deg2rad(lat0);e2=6.6943799901413165e-3;a=6378137.
    n=a/np.sqrt(1-e2*np.sin(phi)**2);m=a*(1-e2)/(1-e2*np.sin(phi)**2)**1.5
    return np.deg2rad(np.asarray(lon)-lon0)*n*np.cos(phi),np.deg2rad(np.asarray(lat)-lat0)*m
def supercover(x0,y0,x1,y1,shape):
    ts=[0.,1.]
    for p,q in [(x0,x1),(y0,y1)]:
        if abs(q-p)>1e-14:ts.extend((k-p)/(q-p) for k in range(math.floor(min(p,q))+1,math.ceil(max(p,q))))
    ts=np.unique(np.clip(ts,0,1));samples=np.r_[ts,(ts[:-1]+ts[1:])/2];cells=set()
    for t in samples:
        x=x0+t*(x1-x0);y=y0+t*(y1-y0)
        for dx,dy in itertools.product([-1e-9,0,1e-9],repeat=2):
            c,r=math.floor(x+dx),math.floor(y+dy)
            if 0<=r<shape[0] and 0<=c<shape[1]:cells.add((r,c))
    return sorted(cells)
@dataclass
class VInfo:
    id:str;capacity:float;volume:float;empty:float;speed:float;r0:float;rf:float;battery:float;rho_floor:float
    prep:float;load:float;handoff0:float;handoff1:float;up:float;down:float;eta:float;tfull:float
def read_inputs():
    raw=pd.read_excel(DATA/"调度中心与服务区.xlsx",header=None)
    arr=[raw.iloc[2,:5].tolist()]+[raw.iloc[i,:5].tolist() for i in range(6,21)]
    nodes=pd.DataFrame(arr,columns=["zone","name","lon","lat","ground_m"])
    nodes["operation_m"]=nodes.ground_m+np.where(nodes.zone=="O01",0,30)
    nodes["x_m"],nodes["y_m"]=local_xy(nodes.lon,nodes.lat,nodes.lon.iloc[0],nodes.lat.iloc[0])
    rr=pd.read_excel(DATA/"运输无人机数据.xlsx",header=None)
    vs={}
    for row in rr.iloc[2:5].itertuples(index=False,name=None):
        g=row[0];tfull=float(rr.iloc[{"A":19,"B":20,"C":21}[g],2])
        vs[g]=VInfo(g,float(row[3]),float(row[4]),float(row[2]),float(row[5]),float(row[6]),float(row[7]),
            float(row[8]),float(row[9])/100,*map(float,row[10:17]),tfull)
    boxes=pd.read_excel(DATA/"物资需求与配送时限.xlsx",sheet_name="逐箱货箱清单").rename(columns={
        "货箱编号":"box","服务区编号":"zone","物资类型":"kind","单箱质量（kg）":"mass","单箱体积（m³）":"volume",
        "是否首批保障":"first","首批截止时间（s）":"first_deadline","期望送达时间（s）":"expected","应急优先系数":"priority"})
    boxes["hard"]=(boxes["first"]=="是")|(boxes.kind=="医疗物资")
    boxes["deadline"]=np.minimum(np.where(boxes.kind=="医疗物资",boxes.expected,np.inf),
                                  np.where(boxes["first"]=="是",boxes.first_deadline,np.inf))
    boxes["category"]=boxes.zone+"|"+boxes.kind
    return boxes,boxes,vs,nodes,[{"path":str(p)} for p in DATA.glob("*.xlsx")]
def all_geometry(nodes):
    raw=loadmat(next((ROOT/"D题/数据").rglob("镇龙乡及周边30米DEM.mat")))
    dem=raw["dem"];dx,_,left,_,dy,top=raw["transform"].ravel()
    cs=(nodes.lon.to_numpy()-left)/dx;rs=(nodes.lat.to_numpy()-top)/dy;out={}
    for i,j in itertools.permutations(range(len(nodes)),2):
        cells=supercover(cs[i],rs[i],cs[j],rs[j],dem.shape)
        terrain=float(max(dem[r,c] for r,c in cells));h=terrain+50
        up=h-float(nodes.operation_m.iloc[i]);down=h-float(nodes.operation_m.iloc[j])
        if min(up,down)<0:raise ValueError("原运输巡航面低于作业端点")
        out[i,j]={"from":i,"to":j,"distance":float(np.hypot(nodes.x_m.iloc[i]-nodes.x_m.iloc[j],nodes.y_m.iloc[i]-nodes.y_m.iloc[j])),
                  "cruise":h,"up":up,"down":down,"terrain":terrain,"cells":len(cells)}
    return out
def seg(v,g,q):
    length=v.r0-(v.r0-v.rf)*(q/v.capacity)**1.5
    horizontal=v.battery*g["distance"]/length;climb=(v.empty+q)*9.81*g["up"]/(v.eta*3.6e6)
    return {"energy":horizontal+climb,"horizontal":horizontal,"climb":climb,
            "time":g["up"]/v.up+g["distance"]/v.speed+g["down"]/v.down,"distance":g["distance"],"up":g["up"],"down":g["down"]}
def charge(v,soc):
    return v.tfull*(.65*(.9-soc)/.9+.35) if soc<.9 else v.tfull*.35*(1-soc)/.1

