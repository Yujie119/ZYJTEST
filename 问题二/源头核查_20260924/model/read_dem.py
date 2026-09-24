from scipy.io import loadmat
from pathlib import Path
p=next(Path(r'D:\研究生\比赛\数学建模\2026\D题').rglob('镇龙乡及周边30米DEM.mat'))
r=loadmat(p)
print(p); print(r.keys())
for k,v in r.items():
 if not k.startswith('__'):
  try: print(k, type(v), getattr(v,'shape',None), v if getattr(v,'size',0)<20 else '')
  except:pass
