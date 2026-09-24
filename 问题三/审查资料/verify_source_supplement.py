"""Read-only source checks for the supplemental Q3 review; writes evidence only."""
from pathlib import Path
from zipfile import ZipFile
import json
import sys
import xml.etree.ElementTree as ET
import openpyxl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DATA = ROOT / 'D题/数据/无人机应急物资运输基础数据'
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
      'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math'}

def rows(name, sheet='数据'):
    wb = openpyxl.load_workbook(DATA / name, read_only=True, data_only=True)
    data = list(wb[sheet].values)
    wb.close()
    return data

def main():
    with ZipFile(ROOT / 'D题/山区洪涝灾害下无人机运输与通信协同优化.docx') as z:
        doc = ET.fromstring(z.read('word/document.xml'))
    ptexts = []
    out = []
    for i, p in enumerate(doc.find('w:body', NS).iter(f"{{{NS['w']}}}p"), 1):
        value = ''.join(n.text or '' for n in p.iter() if n.tag in {
            f"{{{NS['w']}}}t", f"{{{NS['m']}}}t"})
        ptexts.append({'paragraph': i, 'text': value})
        if value:
            out.append(f'P{i}: {value}')
        for j, m in enumerate(p.iter(f"{{{NS['m']}}}oMath"), 1):
            out.append(f'  OMML-{i}.{j}: ' + ET.tostring(m, encoding='unicode'))
    (OUT / '原题含OMML提取.txt').write_text('\n'.join(out), encoding='utf-8')
    boxes = rows('物资需求与配送时限.xlsx', '逐箱货箱清单')[1:]
    med = {r[0] for r in boxes if r[2] == '医疗物资'}
    first = {r[0] for r in boxes if r[5] == '是'}
    soft = [r for r in boxes if r[0] not in med | first]
    cp = {(r[0], r[3]): r[4] for r in rows('通信链路参数.xlsx')[2:] if r[0]}
    threshold = cp['接收参数', 'Psens'] + cp['接收参数', 'M']
    links = []
    for a, b in [('运输无人机','固定网关 G01'),('运输无人机','中继接入端'),('中继回传端','固定网关 G01')]:
        forward = cp[a,'Pt'] + cp[a,'G'] + cp[b,'G'] - cp['传播参数','Lsys'] - threshold
        reverse = cp[b,'Pt'] + cp[b,'G'] + cp[a,'G'] - cp['传播参数','Lsys'] - threshold
        links.append({'a':a,'b':b,'forward_db':forward,'reverse_db':reverse,'bidirectional_db':min(forward,reverse)})
    routes = json.loads((ROOT / '问题三/子问题一/累计候选路线.json').read_text(encoding='utf-8'))
    points = json.loads((ROOT / '问题三/缓存/中继候选位置.json').read_text(encoding='utf-8'))
    max_tr = max(180 + q['out_s'] + 30 + q['dmax'] + q['back_s'] for q in points)
    max_duration = max(r['duration'] for r in routes)
    max_charge = max(r['charge_s'] for r in routes)
    max_sum = max(r['duration'] + r['charge_s'] for r in routes)
    # Eq. 6-14 uses separate maxima for transport duration and charge.
    w = max(max_duration + max_charge, max_tr + 1800)
    result = {
        'review_independence':'same-family','acceptance_status':'provisional',
        'scope':'Original DOCX text including OMML; raw workbook counts/budgets; current finite-library time bounds. No optimization rerun or full DEM communication certification.',
        'source_math_paragraphs':[p for p in ptexts if p['paragraph'] in [48,51,54,57,64,78,81,84,87,90,94]],
        'boxes':{'total':len(boxes),'medical':len(med),'first':len(first),'overlap':len(med&first),'hard':len(med|first),'soft':len(soft),'soft_weight_sum':sum(r[8] for r in soft),
                 'first_deadline_after_expected':[r[0] for r in boxes if r[5]=='是' and r[6]>r[7]]},
        'links':links,
        'finite_library':{'route_count':len(routes),'position_count':len(points),'max_transport_duration_s':max_duration,'max_transport_charge_s':max_charge,'max_transport_duration_plus_charge_s':max_sum,
                          'max_relay_duration_s':max_tr,'W_s':w,'H3_with_6_slots_s':87*w,'code_H_s':30000,'code_M_s':50000,
                          'transport_inactive_release_bound_s':30000+max_charge,'relay_inactive_release_bound_s':30000+1540},
        'raw_transport_inventory_rows':rows('运输无人机数据.xlsx')[19:22],
        'raw_relay_inventory_rows':rows('中继无人机数据.xlsx')[11:12]
    }
    (OUT / '源头审查补充核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
