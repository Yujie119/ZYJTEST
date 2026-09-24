"""Run a bounded Q3 search independently of the chat, with durable checkpoints.

The coordinator owns only its subprocesses. It never stops unrelated Python
jobs, changes official submissions, installs software, or invents swap rules.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

Q3 = Path(__file__).resolve().parent
ROOT = Q3.parent
PYTHON = Path(r'E:\tool\anaconda3\python.exe')


def utc():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stop_owned(process):
    """The subprocess handle identifies a process created by this coordinator."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = read(config_path)
    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise RuntimeError('Use the configured Anaconda base Python')
    output = Path(config['output_dir']).resolve()
    output.relative_to(Q3.resolve())
    output.mkdir(parents=True, exist_ok=True)
    seconds = float(config.get('wall_seconds', 7200))
    if not 60 <= seconds <= 7500:
        raise ValueError('Expected the authorized approximately two-hour budget')
    source = Path(config['route_source']).resolve()
    seed = Path(config['seed_reference']).resolve()
    marker = Path(config['neighborhood_ready']).resolve()
    for path in [source, seed, marker, Q3/'search_q3_neighborhood_worker.py']:
        if not path.is_file():
            raise FileNotFoundError(str(path))
    source_routes = read(source)
    if not isinstance(source_routes, list) or not source_routes or not all(
            isinstance(r, dict) and 'vehicle' in r and 'deliveries' in r for r in source_routes):
        raise ValueError('route_source must be the complete route list, not an export metadata envelope')
    if config.get('expected_source_records') is not None and len(source_routes) != config['expected_source_records']:
        raise ValueError('Complete source record count differs from configured manifest')
    ready = read(marker)
    if not ready.get('ready', False):
        raise RuntimeError('Neighborhood worker smoke check not ready')
    if ready.get('script_sha256') != digest(Q3/'search_q3_neighborhood_worker.py'):
        raise RuntimeError('Neighborhood script differs from tested fingerprint')

    caps = {
        'C': {'N':24.000001, 'E':65.120070, 'L':465.2585},
        'E': {'N':24.000001, 'C':9165.854, 'L':465.2585},
        'L': {'N':24.000001, 'E':65.120070, 'C':9165.854},
        'N': {'E':65.120070, 'C':9165.854, 'L':465.2585},
    }
    work_budget = max(30., seconds-120.)
    jobs = []
    for mode, cap in caps.items():
        folder = output/('全库_'+mode)
        command = [str(PYTHON), '-X', 'utf8', str(Q3/'solve_q3_global.py'),
                   '--seconds', str(work_budget), '--round-seconds', '300', '--mode', mode,
                   '--caps-json', json.dumps(cap, separators=(',', ':')),
                   '--route-file', str(source), '--seed-reference', str(seed),
                   '--output-dir', str(folder)]
        jobs.append(dict(name='full_'+mode, kind='full_library', command=command, folder=str(folder)))
    for random_seed in config.get('neighborhood_seeds', [2026092401, 2026092402]):
        folder = output/('邻域_'+str(random_seed))
        command = [str(PYTHON), '-X', 'utf8', str(Q3/'search_q3_neighborhood_worker.py'),
                   '--seconds', str(work_budget), '--task-seconds', '90',
                   '--output', str(folder), '--seed', str(random_seed)]
        jobs.append(dict(name='neighborhood_'+str(random_seed), kind='neighborhood',
                         command=command, folder=str(folder)))
    plan = dict(created_utc=utc(), coordinator_pid=os.getpid(), wall_seconds=seconds,
                subprocess_search_budget_s=work_budget, jobs=jobs,
                source_sha256=digest(source), source_file=str(source), seed_sha256=digest(seed),
                scope='No spare battery carried; only O01 swaps searched. The expert-allowed remote-swap domain is not exhausted.',
                full_space_global_optimality=False, gpu_integer_optimization=False,
                official_results_modified=False,
                completion_policy='Stop owned solvers at hard deadline; preserve all partial logs and label unverified candidates.')
    write(output/'启动计划.json', plan)
    if args.dry_run:
        print(json.dumps({'status':'DRY_RUN_PASS', 'jobs':len(jobs), 'output':str(output)}, ensure_ascii=False))
        return
    started = time.monotonic()
    deadline = started+seconds
    deadline_epoch = time.time()+seconds
    running, handles = [], []
    state = dict(status='starting', started_utc=utc(), started_epoch=time.time(), deadline_epoch=deadline_epoch,
                 coordinator_pid=os.getpid(), config=str(config_path), jobs=[],
                 elapsed_s=0., remaining_s=seconds, only_O01_swaps=True,
                 completion_does_not_mean_optimality=True)
    env = os.environ.copy()
    for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        env[key] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    env['MKL_THREADING_LAYER'] = 'SEQUENTIAL'
    try:
        for job in jobs:
            folder = Path(job['folder']); folder.mkdir(parents=True, exist_ok=True)
            stdout = (folder/'stdout.log').open('w', encoding='utf-8')
            stderr = (folder/'stderr.log').open('w', encoding='utf-8')
            handles.extend([stdout, stderr])
            process = subprocess.Popen(job['command'], cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            record = dict(name=job['name'], kind=job['kind'], pid=process.pid,
                          folder=str(folder), status='running', started_utc=utc(), returncode=None)
            running.append((process, record)); state['jobs'].append(record)
            write(output/'后台状态.json', state)
        state['status'] = 'running'
        while True:
            active = 0
            for process, record in running:
                code = process.poll()
                if code is None:
                    active += 1
                elif record['status'] == 'running':
                    record.update(status='finished', returncode=code, ended_utc=utc())
                    # Solver no-incumbent status is not a physical infeasibility claim.
                    record['interpretation'] = 'Read solver JSON and independent verifier outputs; exit alone is not a certificate.'
            elapsed = time.monotonic()-started
            state.update(updated_utc=utc(), elapsed_s=elapsed, remaining_s=max(0., deadline-time.monotonic()),
                         active_jobs=active,
                         verified_plan_files=[str(p.relative_to(output)) for p in output.rglob('已核验方案.json')],
                         pending_plan_files=[str(p.relative_to(output)) for p in output.rglob('候选方案_待独立物理核验.json')])
            if not active:
                state['status'] = 'searches_finished'
                break
            if time.monotonic() >= deadline or (output/'STOP_REQUESTED').exists():
                reason = 'deadline' if time.monotonic() >= deadline else 'requested_stop_file'
                for process, record in running:
                    if process.poll() is None:
                        stop_owned(process)
                        record.update(status='stopped_'+reason, returncode=process.returncode, ended_utc=utc())
                state['status'] = 'stopped_'+reason
                break
            write(output/'后台状态.json', state)
            time.sleep(min(10., max(.1, deadline-time.monotonic())))
    except BaseException:
        state.update(status='coordinator_error', error=traceback.format_exc())
        for process, record in running:
            if process.poll() is None:
                stop_owned(process)
                record.update(status='stopped_coordinator_error', returncode=process.returncode)
        raise
    finally:
        for handle in handles:
            handle.close()
        state.update(updated_utc=utc(), elapsed_s=time.monotonic()-started,
                     remaining_s=max(0., deadline-time.monotonic()), active_jobs=0,
                     finished_utc=utc())
        write(output/'后台状态.json', state)
        write(output/'运行结束摘要.json', state)
        print(json.dumps({'status':state['status'], 'elapsed_s':state['elapsed_s'],
                          'output':str(output)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
