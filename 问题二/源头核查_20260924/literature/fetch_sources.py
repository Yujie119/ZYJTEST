from pathlib import Path
import requests, json, hashlib, concurrent.futures
from bs4 import BeautifulSoup

OUT=Path(__file__).parent
SOURCES={
 'dorling_author_pdf':'https://arxiv.org/pdf/1608.02305',
 'zhang_openalex':'https://api.openalex.org/works/https://doi.org/10.1016/j.trd.2020.102668',
 'zhang_publisher_api':'https://api.elsevier.com/content/article/PII:S1361920920308531?httpAccept=text/xml',
 'zhang_umsl':'https://profiles.umsl.edu/en/publications/energy-consumption-models-for-delivery-drones-a-comparison-and-as/',
 'zhang_corrigendum_api':'https://api.elsevier.com/content/article/doi/10.1016/j.trd.2023.103609?httpAccept=text/xml',
 'zeng_energy_author_pdf':'https://arxiv.org/pdf/1804.02238',
 'task_ref_08_author_pdf':'https://arxiv.org/pdf/1602.03602',
 'R3_publisher_pdf':'https://link.springer.com/content/pdf/10.1007/s00186-023-00841-0.pdf',
 'R4_publisher_api':'https://api.elsevier.com/content/article/PII:S0305054824001382?httpAccept=text/xml',
}
def fetch(item):
 name,url=item
 try:
  r=requests.get(url,timeout=50,headers={'User-Agent':'Mozilla/5.0 (research source verification)'})
  pdf=r.content.startswith(b'%PDF')
  ext='.pdf' if pdf else '.json' if 'json' in r.headers.get('Content-Type','') else '.html' if '<html' in r.text[:500].lower() else '.xml'
  p=OUT/(name+ext);p.write_bytes(r.content)
  if not pdf:
   (OUT/(name+'.txt')).write_text(BeautifulSoup(r.content,'html.parser').get_text('\n',strip=True),encoding='utf-8')
  result={'name':name,'url':url,'resolved_url':r.url,'status':r.status_code,'type':r.headers.get('Content-Type'),'bytes':len(r.content),'file':p.name,'pdf':pdf,'sha256':hashlib.sha256(r.content).hexdigest()}
 except Exception as e:result={'name':name,'url':url,'error':str(e)}
 print(json.dumps(result,ensure_ascii=False),flush=True)
 return result
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(fetch,SOURCES.items()))
 (OUT/'source_access_20260924.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
