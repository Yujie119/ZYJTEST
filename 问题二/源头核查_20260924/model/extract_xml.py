import xml.etree.ElementTree as ET, pathlib, re
p=pathlib.Path(r'D:\研究生\比赛\数学建模\2026\问题二\源头核查_20260924\model\docx_unzip\word\document.xml')
root=ET.parse(p).getroot(); ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
for i,para in enumerate(root.findall('.//w:body/w:p',ns),1):
 t=''.join(x.text or '' for x in para.findall('.//w:t',ns)).strip()
 if any(k in t for k in ['问题二','医疗','首批','期望','时限','附录 2','能源','充电','准备','交接','返回','物资']): print(f'{i}: {t}')
