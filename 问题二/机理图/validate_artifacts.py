"""Check delivered files and frozen source fingerprints without new packages."""
from pathlib import Path
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from PIL import Image
from build_report import FIGURES

HERE=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    data=json.loads((HERE/'mechanism_data.json').read_text(encoding='utf-8'))
    checks={}
    for relative,digest in data['input_sha256'].items():
        p=HERE.parent/relative
        checks[relative]=sha(p)==digest
    assert all(checks.values()),'A source file changed; rebuild and review the data.'
    files=[]
    for stem,_ in FIGURES:
        for ext in ['png','svg','pdf']:
            p=HERE/f'{stem}.{ext}';raw=p.read_bytes()
            record=dict(file=p.name,bytes=len(raw),sha256=sha(p))
            assert len(raw)>1000,p
            if ext=='png':
                with Image.open(p) as im:
                    record['pixels']=list(im.size);im.verify()
                assert min(record['pixels'])>800
            elif ext=='svg':
                root=ET.fromstring(raw)
                record['svg_valid']=root.tag.endswith('svg')
                assert record['svg_valid']
                record['text_elements']=len(root.findall('.//{http://www.w3.org/2000/svg}text'))
                record['raster_images']=len(root.findall('.//{http://www.w3.org/2000/svg}image'))
                assert record['raster_images']==0,'Expected vector SVG'
            else:
                assert raw.startswith(b'%PDF-') and raw.rstrip().endswith(b'%%EOF')
                record['page_objects']=len(re.findall(rb'/Type\s*/Page\b',raw))
                record['embedded_font_file']=bool(re.search(rb'/FontFile[23]?\b',raw))
                assert record['page_objects']==1
                assert record['embedded_font_file']
            files.append(record)
    for name in ['机理图说明与核验.md','latex_includes.tex','FIGURE_PLAN.md']:
        assert (HERE/name).stat().st_size>100
    report=(HERE/'机理图说明与核验.md').read_text(encoding='utf-8')
    assert not re.search(r'@[A-Z_]+@',report),'Unexpanded report placeholder'
    assert len(re.findall(r'!\[',report))==5
    result=dict(source_fingerprints_unchanged=checks,data_checks=data['validations'],artifacts=files,
        note='PNG files visually inspected by the author. PDF checks are structural; no PDF rendering dependency installed.',
        final_submission_sha256=sha(HERE.parent/'最终求解_20260924/最终方案.json'))
    (HERE/'交付文件核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: 15 figure files, embedded PDF fonts, editable vector SVGs, 5 Markdown image references and unchanged source hashes.')

if __name__=='__main__':main()
