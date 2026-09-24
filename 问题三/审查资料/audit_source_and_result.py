"""Raw-workbook arithmetic audit plus full-DEM verification of a dominance witness.

The arithmetic branch does not import q3_inputs.seg/charge or trust route
totals. The continuous-communication branch deliberately reuses the existing
geometric verifier and is reported separately, not as an independent algorithm.
All outputs stay in 审查资料/本轮复核; the submitted workbook is unchanged.
"""
from __future__ import annotations
import copy, json, math, sys, itertools
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.io import loadmat

HERE = Path(__file__).resolve().parent
Q3 = HERE.parent
ROOT = Q3.parent
DATA = ROOT / 'D题/数据/无人机应急物资运输基础数据'
OUT = HERE / '本轮复核'


def write(name, value):
    OUT.mkdir(exist_ok=True)
    def conv(v):
        if isinstance(v, (np.integer, np.floating)): return v.item()
        if isinstance(v, np.bool_): return bool(v)
        raise TypeError(type(v).__name__)
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                   default=conv, allow_nan=False), encoding='utf-8')


def table(path, header, begin, end):
    df = pd.read_excel(DATA/path, header=None)
    names = list(df.iloc[header])
    return [{str(k): v for k, v in zip(names, list(df.iloc[i])) if pd.notna(k)}
            for i in range(begin, end)]


def cells_on_segment(a, b, shape):
    # Cross all grid-line events and their open-interval midpoints. Closed
    # pixel contacts on either side of an integer line belong to both cells.
    cuts = [0., 1.]
    for p, q in zip(a, b):
        if abs(q-p) > 1e-14:
            cuts += [(k-p)/(q-p) for k in range(math.floor(min(p,q))+1, math.ceil(max(p,q)))]
    cuts = sorted(set(cuts))
    points = cuts + [(p+q)/2 for p,q in zip(cuts, cuts[1:])]
    cells = set()
    for t in points:
        c, r = np.asarray(a) + t*(np.asarray(b)-a)
        for dc, dr in itertools.product((-1e-9, 0., 1e-9), repeat=2):
            ic, ir = math.floor(c+dc), math.floor(r+dr)
            if not (0 <= ir < shape[0] and 0 <= ic < shape[1]):
                raise ValueError('flight leaves DEM')
            cells.add((ir, ic))
    return cells


def audit(plan):
    raw = pd.read_excel(DATA/'物资需求与配送时限.xlsx', sheet_name='逐箱货箱清单')
    bybox = raw.set_index('货箱编号').to_dict('index')
    vehicles = {r['机型编号']: r for r in table('运输无人机数据.xlsx',1,2,5)}
    uavs = {r['无人机编号']: r['机型编号'] for r in table('运输无人机数据.xlsx',7,8,16)}
    inv = {r['机型编号']: r for r in table('运输无人机数据.xlsx',18,19,22)}
    ndf = pd.read_excel(DATA/'调度中心与服务区.xlsx', header=None)
    node_rows = [list(ndf.iloc[2,:5])] + [list(ndf.iloc[i,:5]) for i in range(6,21)]
    lon0, lat0 = map(float, node_rows[0][2:4])
    phi = math.radians(lat0); e2 = 6.6943799901413165e-3
    radius_n = 6378137./math.sqrt(1-e2*math.sin(phi)**2)
    radius_m = 6378137.*(1-e2)/(1-e2*math.sin(phi)**2)**1.5
    nodes = {z: dict(x=math.radians(float(lon)-lon0)*radius_n*math.cos(phi),
                    y=math.radians(float(lat)-lat0)*radius_m,
                    lon=float(lon), lat=float(lat), z=float(h)+(0 if z=='O01' else 30))
             for z,_,lon,lat,h in node_rows}
    dem_raw = loadmat(next((ROOT/'D题/数据').rglob('镇龙乡及周边30米DEM.mat')))
    dem = dem_raw['dem']; dx,_,left,_,dy,top = dem_raw['transform'].ravel()
    nodata = float(dem_raw['nodata'].item())
    cache = {}
    def geo(i,j):
        if (i,j) not in cache:
            a,b = nodes[i], nodes[j]
            rc0 = np.array([(a['lon']-left)/dx,(a['lat']-top)/dy])
            rc1 = np.array([(b['lon']-left)/dx,(b['lat']-top)/dy])
            heights = [float(dem[r,c]) for r,c in cells_on_segment(rc0,rc1,dem.shape)]
            assert all(math.isfinite(h) and h!=nodata for h in heights)
            h = max(heights)+50.
            cache[i,j] = (math.hypot(a['x']-b['x'],a['y']-b['y']), h-a['z'], h-b['z'])
        return cache[i,j]

    checks = []
    def check(name, good, detail=None):
        checks.append({'check':name,'passed':bool(good),'detail':detail})
    rr = plan['routes']; assigned = plan['boxes']; relay=plan['relays']
    check('transport IDs unique',len({r['route_id'] for r in rr})==len(rr))
    check('relay IDs unique',len({r['relay_id'] for r in relay})==len(relay))
    check('relay slots unique',len({r['slot'] for r in relay})==len(relay))
    boxids = [b['box'] for b in assigned]
    check('80 named boxes exactly once',Counter(boxids)==Counter(bybox.keys()))
    ridmap = {r['route_id']:r for r in rr}
    check('each named box has an actual route',all(b['route_id'] in ridmap for b in assigned))
    check('visit order equals delivery-event order',all(r['zones']==[d['zone'] for d in r['deliveries']] for r in rr))
    # Fail fast for a malformed plan instead of continuing with a mislocated
    # unloading event. This catches the legacy verifier's missing association.
    if not all(c['passed'] for c in checks):
        return {'status':'FAIL','checks':checks}
    byroute = defaultdict(list)
    for b in assigned: byroute[b['route_id']].append(bybox[b['box']] | {'id':b['box']})
    records=[]; recomputed_delivery={}; resource=defaultdict(list)
    for r in rr:
        rid=r['route_id']; g=r['vehicle']; v=vehicles[g]
        cargo=byroute[rid]
        counts=Counter(b['服务区编号']+'|'+b['物资类型'] for b in cargo)
        dc=Counter()
        for d in r['deliveries']: dc.update(d['counts'])
        check(rid+'/named payload equals declared counts',dict(counts)==r['counts']==dict(dc))
        check(rid+'/all destinations physically visited',all(b['服务区编号'] in r['zones'] for b in cargo))
        mass=sum(float(b['单箱质量（kg）']) for b in cargo)
        volume=sum(float(b['单箱体积（m³）']) for b in cargo)
        check(rid+'/mass and volume',mass<=v['最大载货质量（kg）']+1e-8 and volume<=v['可用装载体积（m³）']+1e-8)
        # Exact workbook headers are retained in the serialized parameter audit.
        energy_capacity=float(v['电池可用能量（kWh）'])
        t=float(v['工位固定准备时间（s）'])+len(cargo)*float(v['每箱装载时间（s）'])
        q=mass; energy=0.; hor=0.; upenergy=0.
        seq=['O01']+r['zones']+['O01']
        for a,b in zip(seq,seq[1:]):
            distance,up,down=geo(a,b)
            check(rid+'/'+a+'-'+b+'/nonnegative heights',min(up,down)>=0)
            length=float(v['空载标准航程（m）'])-(float(v['空载标准航程（m）'])-float(v['满载标准航程（m）']))*(q/float(v['最大载货质量（kg）']))**1.5
            eh=energy_capacity*distance/length
            eu=(float(v['含电池空载总质量（kg）'])+q)*9.81*up/(float(v['爬升能耗效率'])*3.6e6)
            hor+=eh;upenergy+=eu;energy+=eh+eu
            t+=up/float(v['最大爬升速度（m/s）'])+distance/float(v['计划巡航速度（m/s）'])+down/float(v['最大下降速度（m/s）'])
            if b!='O01':
                delivered=[bb for bb in cargo if bb['服务区编号']==b]
                t+=float(v['接收点基础交接时间（s）'])+len(delivered)*float(v['每箱增加交接时间（s）'])
                for bb in delivered: recomputed_delivery[bb['id']]=r['start']+t
                q-=sum(float(bb['单箱质量（kg）']) for bb in delivered)
        soc=1-energy/energy_capacity
        tfull=float(inv[g]['等效完全充电时间（s）'])
        charge=tfull*(max(.9-soc,0)*.65/.9+(1-max(.9,soc))*.35/.1)
        end=r['start']+t
        check(rid+'/energy',abs(energy-r['energy'])<2e-6)
        check(rid+'/duration',abs(t-r['duration'])<2e-4)
        check(rid+'/finish',abs(end-r['finish'])<2e-4)
        check(rid+'/reserve',soc>=float(v['返航电量下限（%）'])/100-2e-6)
        check(rid+'/charge',abs(charge-r['charge_s'])<2e-4)
        check(rid+'/UAV type',uavs.get(r['uav'])==g)
        check(rid+'/battery identity',r['battery_id'] in {f'{g}-BAT-{i:02d}' for i in range(1,int(inv[g]['共享电池组总数（组）'])+1)})
        resource[r['uav']].append((r['start'],end,rid))
        resource[r['battery_id']].append((r['start'],end+charge,rid))
        records.append({'route_id':rid,'energy':energy,'horizontal':hor,'climb':upenergy,'duration':t,'finish':end,'soc':soc})
    late_num=0.;denom=0.;hard=0;late_count=0
    for b in assigned:
        rawb=bybox[b['box']];time=recomputed_delivery[b['box']]
        check(b['box']+'/named attributes',b['zone']==rawb['服务区编号'] and b['kind']==rawb['物资类型'])
        check(b['box']+'/delivery recomputed',abs(time-b['delivery'])<2e-4)
        is_hard=rawb['物资类型']=='医疗物资' or rawb['是否首批保障']=='是'
        if is_hard:
            deadline=min(float(rawb['期望送达时间（s）']) if rawb['物资类型']=='医疗物资' else math.inf,
                         float(rawb['首批截止时间（s）']) if rawb['是否首批保障']=='是' else math.inf)
            check(b['box']+'/hard deadline',time<=deadline+2e-4);hard+=1
        else:
            late=max(0.,time-float(rawb['期望送达时间（s）']))
            late_num+=float(rawb['应急优先系数'])*late;denom+=float(rawb['应急优先系数']);late_count+=late>2e-4
    for name,items in resource.items():
        items=sorted(items)
        check(name+'/nonoverlap',all(a[1]<=b[0]+2e-4 for a,b in zip(items,items[1:])))
    homogeneous=[]
    for (z,k),grp in raw.groupby(['服务区编号','物资类型']):
        same=all(grp[c].nunique()==1 for c in ['单箱质量（kg）','单箱体积（m³）','期望送达时间（s）','应急优先系数'])
        f=grp[grp['是否首批保障']=='是']
        good=same and len(f)<=1 and (len(f)==0 or float(f.iloc[0]['首批截止时间（s）'])<=float(f.iloc[0]['期望送达时间（s）']))
        homogeneous.append({'category':z+'|'+k,'aggregation_preconditions':good})
    check('category aggregation assumptions',all(x['aggregation_preconditions'] for x in homogeneous))
    return {'status':'PASS' if all(x['passed'] for x in checks) else 'FAIL','checks':checks,
            'transport_energy':sum(x['energy'] for x in records),'routes':records,
            'hard_box_count':hard,'soft_box_count':len(assigned)-hard,
            'soft_priority_denominator':denom,'weighted_lateness':late_num/denom,
            'late_soft_boxes':late_count,'category_data_checks':homogeneous}


def main():
    plan=json.loads((Q3/'子问题二/最终方案.json').read_text(encoding='utf-8'))
    # Save all field names first so a raw-workbook schema mismatch is visible.
    write('原始字段参数.json',{'transport':table('运输无人机数据.xlsx',1,2,5),
                           'relay':table('中继无人机数据.xlsx',1,2,3)})
    baseline=audit(plan);write('原始工作簿独立算术复核.json',baseline)
    print('RAW_ARITHMETIC',baseline['status'],len(baseline['checks']),flush=True)
    witness=copy.deepcopy(plan)
    target=next(r for r in witness['routes'] if r['route_id']=='Q3-T020')
    for key in ('start','takeoff','finish','recharge'): target[key]-=10.
    for b in witness['boxes']:
        if b['route_id']==target['route_id']: b['delivery']-=10.
    witness['objective'][2]=max([r['finish'] for r in witness['routes']]+[r['finish'] for r in witness['relays']])
    witness['audit_note']='Only Q3-T020 shifted 10 seconds earlier; dominance witness, not global optimum.'
    wa=audit(witness);write('支配见证原始数据算术复核.json',wa)
    write('支配见证方案.json',witness)
    # Legacy geometry verifier and exact communication-event checks are run
    # on both full plans against the original DEM; their shared kernel is
    # explicitly disclosed instead of being called a fresh geometric proof.
    sys.path.insert(0,str(Q3))
    import verify_q3 as vmod
    import q3_communication as comm
    results={}
    for label,p in [('baseline',plan),('witness',witness)]:
        v=vmod.Verifier(p);v.verify_routes();v.verify_boxes();v.verify_relays();res=v.finish()
        res['plan']=str(Q3/'子问题二/最终方案.json') if label=='baseline' else str(OUT/'支配见证方案.json')
        write(label+'_完整DEM核验.json',res)
        # Redirect the export directory only inside this audit process.
        sub=OUT/label; (sub/'子问题二').mkdir(parents=True,exist_ok=True)
        comm.OUT=sub
        events=comm.export_communication(p)
        results[label]={'status':res['status'],'checks':len(res['checks']),
                        'objective':res['objective_recomputed'],'certified_intervals':res['certified_intervals'],
                        'communication_rows':len(events)}
        print(label,res['status'],res['objective_recomputed'],flush=True)
    malformed=copy.deepcopy(plan)
    malformed['routes'][0]['deliveries'][0]['zone']='S999'
    mutation=audit(malformed)
    write('目的地错配拒绝测试.json',mutation)
    results['destination_mismatch_rejected']=mutation['status']=='FAIL'
    results['dominance_time_improvement_s']=plan['objective'][2]-witness['objective'][2]
    results['raw_arithmetic_status']=baseline['status']
    results['scope']='Arithmetic uses raw workbooks and DEM without production energy/time functions; communication rerun uses legacy sweep kernel. No proof of global optimality.'
    write('本轮复核摘要.json',results)


if __name__=='__main__':main()
