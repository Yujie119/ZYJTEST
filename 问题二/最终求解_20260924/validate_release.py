"""Read back the delivered tables, manuscript results and linked evidence."""
from pathlib import Path
import csv, hashlib, json, math, re
import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def close(a,b): return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-6)

def main():
    f=read(HERE/'最终方案.json')
    wb=openpyxl.load_workbook(HERE/'问题二_结果提交.xlsx',data_only=True)
    rs={r['route_id']:r for r in f['routes']}
    for row in list(wb['Q2_运输架次'].values)[1:]:
        r=rs[row[0]]
        assert list(row[1:4])==[r['uav'],r['vehicle'],r['battery_id']]
        assert close(row[4],r['start']) and close(row[6],r['finish']) and close(row[7],r['energy'])
        assert row[5]=='→'.join(['O01']+r['zones']+['O01'])
    assert wb['Q2_运输架次'].max_row-1==len(rs)==22
    bs={b['box']:b for b in f['boxes']}
    for row in list(wb['Q2_逐箱交付'].values)[1:]:
        b=bs[row[0]]
        assert row[1]==b['route_id'] and row[2]==b['zone'] and close(row[3],b['delivery'])
    assert wb['Q2_逐箱交付'].max_row-1==len(bs)==80
    for name,count in [('最终方案_运输架次.csv',22),('最终方案_逐箱交付.csv',80)]:
        with (HERE/name).open(encoding='utf-8-sig',newline='') as stream:
            assert len(list(csv.reader(stream)))==count+1
    doc=(ROOT/'正文/正文.md').read_text(encoding='utf-8')
    a=re.search(r'^#\s*5[ .．]',doc,re.M)
    b=re.search(r'^#\s*6[ .．]',doc,re.M)
    assert a and b
    chapter=doc[a.start():b.start()]
    assert '65.518517' in chapter and '6206.344443' in chapter
    match=re.search(r'\*\*表5-4[^\n]*\n+((?:\|[^\n]*\n)+)',chapter)
    assert match
    entries=[line.split('|')[1:-1] for line in match.group(1).splitlines() if line.startswith('|Q2-')]
    assert len(entries)==22
    for row in entries:
        r=rs[row[0]]
        assert row[1:4]==[r['uav'],r['vehicle'],r['battery_id']]
        assert close(float(row[4]),r['start']) and close(float(row[6]),r['finish']) and close(float(row[7]),r['energy'])
    report=(HERE/'最终方案说明与核查报告.md').read_text(encoding='utf-8')
    assert not any(ord(ch)<32 and ch not in '\n\r\t' for ch in report+chapter)
    audit=read(HERE/'final_evaluation_audit/summary.json')
    assert audit['final_plan_hash']==sha(HERE/'最终方案.json')
    assert audit['raw_final']['all'] and audit['selection_matches'] and not audit['archive_dominance_pairs']
    assert read(HERE/'独立核验.json')['checks']['all']
    assert read(HERE/'原始数据核验.json')['all']
    assert read(HERE/'电池位置核验.json')['passed']
    assert read(HERE/'导出核验.json')['sha256']==sha(HERE/'问题二_结果提交.xlsx')
    result=dict(passed=True,objective=f['objective'],xlsx_and_csv_and_manuscript_match=True,
        all_22_routes_and_80_boxes_read_back=True,evaluation_matches_final_hash=True,
        final_plan_sha256=sha(HERE/'最终方案.json'),workbook_sha256=sha(HERE/'问题二_结果提交.xlsx'),
        manuscript_sha256=sha(ROOT/'正文/正文.md'),report_sha256=sha(HERE/'最终方案说明与核查报告.md'))
    (HERE/'交付最终校验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
