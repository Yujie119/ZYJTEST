"""Freeze Q3 and original inputs; derive actual, direct-first communication locally."""
from pathlib import Path
import concurrent.futures as cf
import csv
import hashlib
import json
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SNAP = HERE / '输入快照'
POLISH = ROOT / '问题三/搜索精修/扩展固定结构精修_v1'

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def save(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def csvout(p, rows):
    if not rows:
        return
    with Path(p).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def comm_worker(spec):
    """Each process owns its compatibility module globals and output directory."""
    name, target = spec
    target = Path(target)
    sys.path.insert(0, str(HERE / '冻结几何依赖'))
    import q3_communication as comm
    plan = json.loads((target / '方案.json').read_text(encoding='utf-8'))
    captured = {}
    comm.save = lambda p, obj: captured.__setitem__(Path(p).name, obj)
    comm.csv = lambda p, obj: captured.__setitem__(Path(p).name, obj)
    rows = comm.export_communication(plan)
    # No output is sent to Q3. All derived records retain source IDs.
    save(target / '实际通信分段.json', rows)
    csvout(target / '实际通信分段.csv', rows)
    points = captured['通信事件端点核验.csv']
    csvout(target / '通信事件端点核验.csv', points)
    summary = captured['通信事件核验摘要.json']
    summary['source_sha256'] = digest(target / '方案.json')
    summary['minimum_endpoint_margin_dB'] = min(x['margin_dB'] for x in points)
    slots = {int(r['slot']):r['relay_id'] for r in plan['relays']}
    assert len(slots) == len(plan['relays'])
    rr = {r['relay_id']:r for r in plan['relays']}
    for row in rows:
        if row['mode'] == '中继':
            r = rr[row['relay_id']]
            assert r['alpha'] - 2e-4 <= row['t0'] <= row['t1'] <= r['beta'] + 2e-4
    for point in points:
        if point['provider'] != 'G01':
            r = rr[point['provider']]
            assert r['alpha'] - 2e-4 <= point['time_s'] <= r['beta'] + 2e-4
    save(target / '通信核验.json', summary)
    csvout(target / 'slot_中继任务映射.csv', [{'snapshot': name, 'slot':s, 'relay_id':j} for s,j in sorted(slots.items())])
    return {'snapshot':name, **summary}

def main():
    SNAP.mkdir(exist_ok=True)
    input_dir = SNAP / '原始附件'; input_dir.mkdir(exist_ok=True)
    sources = list((ROOT / 'D题/数据/无人机应急物资运输基础数据').glob('*.xlsx'))
    sources += [next((ROOT/'D题/数据').rglob('镇龙乡及周边30米DEM.mat')), ROOT/'D题/结果提交模板.xlsx']
    sources += [ROOT/'D题/山区洪涝灾害下无人机运输与通信协同优化.docx']
    manifests = []
    for src in sources:
        dst = input_dir / src.name
        shutil.copy2(src, dst)
        assert digest(src) == digest(dst)
        manifests.append({'original':str(src), 'copy':str(dst), 'sha256':digest(dst)})
    # Isolate inherited geometry code. This is the Q3 physical kernel, not a new
    # independent propagation proof. Only input/output roots are adapted.
    dep = HERE/'冻结几何依赖'; dep.mkdir(exist_ok=True)
    for fn in ['q3_inputs.py','q3_common.py','verify_q3.py','q3_communication.py']:
        src = ROOT/'问题三'/fn
        text = src.read_text(encoding='utf-8')
        if fn == 'q3_inputs.py':
            text = text.replace('ROOT=Path(__file__).resolve().parents[1]', 'ROOT=Path(__file__).resolve().parents[1]')
            text = text.replace('DATA=ROOT/"D题/数据/无人机应急物资运输基础数据"', 'DATA=ROOT/"输入快照/原始附件"')
            text = text.replace('(ROOT/"D题/数据")', '(ROOT/"输入快照/原始附件")')
        elif fn == 'q3_common.py':
            text = text.replace('(ROOT/"D题/数据")', '(ROOT/"输入快照/原始附件")')
        elif fn == 'verify_q3.py':
            text = text.replace('(ROOT / "D题" / "数据")', '(ROOT / "输入快照" / "原始附件")')
        (dep/fn).write_text(text, encoding='utf-8')
        manifests.append({'original':str(src), 'copy':str(dep/fn), 'original_sha256':digest(src),
                          'sha256':digest(dep/fn), 'adaptation':'Q4-local input roots only'})
    specs = []
    for src in sorted(POLISH.glob('*/已核验方案.json')):
        name = src.parent.name
        if name == 'mapped_witness':
            continue  # Duplicate semantic main plan; retained in Q3 provenance.
        dst = SNAP / ('主方案' if name=='official' else '备选方案/'+name)
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst/'方案.json')
        for fn in ['记录.json','独立DEM核验.json','原始数据结构审计.json']:
            p = src.parent/fn
            d = json.loads(p.read_text(encoding='utf-8'))
            assert d.get('status') == 'PASS', (name,fn)
            shutil.copy2(p,dst/fn)
        if name == 'official':
            assert digest(src) == digest(SNAP/'精修方案_源文件.json')
        manifests.append({'original':str(src), 'copy':str(dst/'方案.json'), 'sha256':digest(src)})
        specs.append((name,str(dst)))
    save(SNAP/'源文件清单.json', manifests)
    with cf.ProcessPoolExecutor(max_workers=min(4,len(specs))) as pool:
        summaries = list(pool.map(comm_worker,specs))
    save(SNAP/'全部快照通信核验.json', summaries)
    print(json.dumps([{'snapshot':r['snapshot'],'rows':r['rows'],'endpoints':r['event_points'],'status':r['status']} for r in summaries],ensure_ascii=False))

if __name__ == '__main__':
    main()
