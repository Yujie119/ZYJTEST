"""Three source-audit wording fixes outside chapter 5; no numerical change."""
from pathlib import Path
import json, hashlib, re

HERE=Path(__file__).resolve().parent
DOC=HERE.parent.parent/'正文/正文.md'
def sha(b): return hashlib.sha256(b).hexdigest()

def main():
    before=DOC.read_bytes(); text=before.decode('utf-8')
    changes=[
        ('准备、装载不另计附件未给出的电池耗能，同一站本批货箱均以交接完成时刻记为送达。',
         '准备、装载不另计附件未给出的电池耗能；运输交接阶段亦按题给航段能量求和口径不另加耗能项，此为缺少运输机悬停功率时的补充约定，不表示服务区30 m交接时真实悬停功率为零。同一站本批货箱均以交接完成时刻记为送达。'),
        ('DOI: 10.1016/j.cor.2024.106666. 借鉴偏好多面体与最小最大遗憾；本题指标、偏好集合及界评价需按本章定义。',
         'DOI: 10.1016/j.cor.2024.106666. 用于不确定风险偏好与折中决策的研究背景；本轮仅核实著录与摘要，未核实全文。本题L1偏好集合、最小最大遗憾及其界评价由本文定义和推导，不将具体形式归于该文。'),
        ('并非现第5章更新后的28架次代表。',
         '并非第5章此前的28架次代表，也不是现已更新的22架次提交方案。'),
    ]
    performed=[]
    for old,new in changes:
        if new in text: continue
        assert text.count(old)==1, old
        text=text.replace(old,new,1);performed.append({'old':old,'new':new})
    if not performed:
        print('Shared notes already synchronized; original audit preserved.');return
    images=lambda t:re.findall(r'!\[[^\]]*\]\([^\n]*?\)',t)
    assert images(before.decode('utf-8'))==images(text)
    a=re.search(r'^#\s*5[ .．]',text,re.M);b=re.search(r'^#\s*6[ .．]',text,re.M)
    prev=before.decode('utf-8');pa=re.search(r'^#\s*5[ .．]',prev,re.M);pb=re.search(r'^#\s*6[ .．]',prev,re.M)
    assert text[a.start():b.start()]==prev[pa.start():pb.start()]
    backup=HERE/'共同说明_修改前正文备份.md'
    assert not backup.exists()
    backup.write_bytes(before)
    after=text.encode('utf-8');DOC.write_bytes(after)
    rec={'before_sha256':sha(before),'after_sha256':sha(after),'image_references_identical':True,
         'chapter5_unchanged':True,'changes':performed,'scope':'Assumption 5, shared R4 source qualification, historical Q2 cross-reference only; no numerical or Q3 model change.'}
    (HERE/'共同说明同步核验.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rec,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
