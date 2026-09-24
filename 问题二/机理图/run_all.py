"""Reproduce figures with the current Python; --recompute rebuilds LP data."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse
import subprocess
import sys

HERE=Path(__file__).resolve().parent

def run(name):
    subprocess.run([sys.executable,str(HERE/name)],check=True,cwd=HERE)
    return name

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--recompute',action='store_true')
    args=parser.parse_args()
    if args.recompute or not (HERE/'mechanism_data.json').exists():run('compute_data.py')
    with ThreadPoolExecutor(max_workers=3) as executor:
        for name in executor.map(run,sorted(p.name for p in HERE.glob('fig0*.py'))):print('OK',name)
    run('build_report.py')
    run('validate_artifacts.py')

if __name__=='__main__':main()
