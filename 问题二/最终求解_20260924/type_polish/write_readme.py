from pathlib import Path
import json,hashlib
d=Path(__file__).resolve().parent
s=json.loads((d/'summary.json').read_text(encoding='utf-8'))
lines=['# 按机型终端精修独立核验','',
       '全部11个档案方案均完成；每型先最小迟到，再在不增加该型迟到和全局C上限下最小完成时间。合并后按全局max返场计算C。','',
       '|idx|原目标|精修目标|C改善s|L改善s|生产核验|原始核验|','|---:|---|---|---:|---:|---|---|']
for r in s['results']:
    old=r['old'];new=r['new']
    lines.append(f"|{r['index']}|{old}|{new}|{old[2]-new[2]:.6f}|{old[3]-new[3]:.6f}|{r['verified']}|{r['raw']}|")
lines += ['', '所有结果只写本目录，未修改改进搜索档案、正式结果或正文。原始数据核验直接读取XLSX与GeoTIFF，并独立重算航段、交付、SOC、资源区间和四目标.','', '范围：固定每个方案原有候选路线与箱组；同型无人机、电池、开始时刻和先后关系开放。N/E不变，C取合并全局路线返场最大值。']
(d/'README.md').write_text('\n'.join(lines),encoding='utf-8')
h={str(x.relative_to(d)):hashlib.sha256(x.read_bytes()).hexdigest() for x in d.glob('*.json') if x.name!='hashes.json'}
(d/'hashes.json').write_text(json.dumps(h,ensure_ascii=False,indent=2),encoding='utf-8')
