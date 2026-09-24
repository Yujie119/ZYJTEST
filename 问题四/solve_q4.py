"""Run Q4 subproblems in order; keep their outputs in separate directories."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    for relative in ['子问题一/solve_partition.py','子问题二/analyze_resources.py']:
        subprocess.run([sys.executable,'-X','utf8',str(ROOT/relative)],check=True,cwd=ROOT)
