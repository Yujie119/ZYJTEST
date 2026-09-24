"""Run with the configured Anaconda Python; supports independent per-figure reruns."""
from pathlib import Path
import subprocess
import sys

if __name__=='__main__':
    here=Path(__file__).resolve().parent
    for script in ['compute_data.py','fig01_epsilon.py','fig02_adaptive.py',
                   'fig03_relaxation.py','fig04_bounds.py','build_report.py']:
        subprocess.run([sys.executable,'-X','utf8',str(here/script)],check=True,cwd=here)
