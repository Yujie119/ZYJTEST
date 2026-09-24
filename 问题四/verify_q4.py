"""Convenience entry for the independent verifier in subproblem 2."""
from pathlib import Path
import subprocess
import sys
if __name__=='__main__':
    subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve().parent/'子问题二/verify_q4.py')],check=True)
