from pathlib import Path
import sys, json, hashlib, zipfile, xml.etree.ElementTree as ET
from copy import deepcopy
from collections import Counter
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
Q2 = ROOT / '问题二'
sys.path.insert(0, str(Q2))
from q2_data import load_data, save_json, decode
from q2_verify import verify_plan
from q2_joint import JointModel

def read(name): return json.loads((Q2/name).read_text(encoding='utf-8'))
def sources():
    doc=ROOT/'D题/山区洪涝灾害下无人机运输与通信协同优化.docx'
    with zipfile.ZipFile(doc) as z: rt=ET.fromstring(z.read('word/document.xml'))
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    paras=[''.join(t.text or '' for t in p.iter() if t.tag.split('}')[-1]=='t') for p in rt.findall('.//w:p',ns)]
    (OUT/'raw_task_paragraphs.txt').write_text('\n'.join(f'{i+1}: {s}' for i,s in enumerate(paras)),encoding='utf-8')
    import openpyxl
    lines=[]
    for p in sorted((ROOT/'D题/数据/无人机应急物资运输基础数据').glob('*.xlsx')):
        if p.name not in ['运输无人机数据.xlsx','调度中心与服务区.xlsx','物资需求与配送时限.xlsx']:continue
        wb=openpyxl.load_workbook(p,data_only=True)
        for ws in wb:
            lines.append(f'FILE {p.relative_to(ROOT)} SHEET {ws.title}')
            for i,row in enumerate(ws.values,1):lines.append(f'{i}: {repr(row)}')
    (OUT/'raw_workbook_cells.txt').write_text('\n'.join(lines),encoding='utf-8')
    paths=[doc,*sorted((ROOT/'D题/数据/无人机应急物资运输基础数据').glob('*.xlsx'))]
    paths += [Q2/name for name in ['q2_data.py','q2_joint.py','q2_candidates.py','q2_run.py','q2_verify.py','audit_q2_implementation.py','report_q2.py','冻结评价配置.json','联合求解配置.json','求解摘要.json','子问题二/最终方案.json','子问题二/完整联合运行日志.json','子问题二/偏好极点基准.json','子问题二/单目标有效下界.json','子问题二/联合非支配档案.json','子问题二/构造初始化档案.json','子问题二/ALNS对照日志.json','子问题二/独立核验.json']]
    save_json(OUT/'input_hashes.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    logs=read('子问题二/完整联合运行日志.json')
    abr=[]
    for z in logs:
        abr.append({'job':z['job'],'stages':[{k:m.get(k) for k in ['stage','status','optimal','incumbent','warm_fallback','lower_bound','upper_bound','gap','matrix_residual','variables','constraints','horizon','seconds','nodes']} for m in z['stages']]})
    save_json(OUT/'log_summary.json',abr)

def recheck():
    data=load_data(); plan=read('子问题二/最终方案.json')
    checks,errors,rec=verify_plan(data,plan)
    save_json(OUT/'existing_verifier_fresh_run.json',{'checks':checks,'errors':errors,'recomputed':rec})
    # Frozen route identities and resource identities; only timing and order free.
    # This is a search-quality witness, not an external ground-truth experiment.
    caps=dict(zip('NECL',plan['objective']))
    model=JointModel(data,deepcopy(plan['routes']),mandatory=True,fixed_resources=True,warm=plan,cap=caps,scope='fresh_audit_fixed_final_routes_resources')
    witness,meta=model.solve([0,0,0,1],15,20260924)
    verify=verify_plan(data,witness) if witness else None
    save_json(OUT/'fixed_resources_timing_witness.json',{'source_objective':plan['objective'],'plan':witness,'solver':meta,'verification':dict(zip(['checks','errors','recomputed'],verify)) if verify else None})
    print(json.dumps({'source':plan['objective'],'fixed_resources':witness['objective'] if witness else None,'status':meta['status'],'verified':verify[0]['all'] if verify else None},ensure_ascii=False))

if __name__=='__main__':
    sources(); recheck()
