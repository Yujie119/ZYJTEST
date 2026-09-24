from pathlib import Path
import subprocess,sys
HERE=Path(__file__).resolve().parent
for name in ['compute_data.py','fig01_epsilon.py','fig02_adaptive.py','fig03_alns.py','fig04_relaxation.py','fig05_bounds.py','export_evidence.py']:
    subprocess.run([sys.executable,'-X','utf8',str(HERE/name)],check=True,cwd=HERE)
print('ALL_FIVE_FIGURES_WRITTEN')
