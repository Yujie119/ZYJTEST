"""One-shot background checkpoint collection and independent candidate checks."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import uuid
from datetime import datetime, timezone

Q3 = Path(__file__).resolve().parent
sys.path.insert(0, str(Q3/'审查资料'))
from audit_source_and_result import audit
from battery_location_audit import audit_locations
from verify_q3 import Verifier


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def safe(value):
    if isinstance(value, Path): return str(value)
    if hasattr(value, 'tolist'): return safe(value.tolist())
    if hasattr(value, 'item'): return safe(value.item())
    if isinstance(value, dict): return {str(k):safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Nonfinite value cannot enter verified output')
    return value


def write(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(safe(value),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    sha=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''): sha.update(chunk)
    return sha.hexdigest()


def value_sha(value):
    return hashlib.sha256(json.dumps(safe(value),sort_keys=True,ensure_ascii=False,
                          separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


def payload(plan):
    # Worker adds provenance/status fields after the direct solver writes its plan.
    return {k:plan[k] for k in ('objective','routes','relays','boxes')}


def fingerprint(root):
    launch=load(root/'启动计划.json')
    source=Path(launch['source_file'])
    if digest(source)!=launch['source_sha256']:
        raise ValueError('Source library changed after launch')
    data=Q3.parent/'D题/数据'
    files=[data/'无人机应急物资运输基础数据'/name for name in
           ('调度中心与服务区.xlsx','通信链路参数.xlsx','物资需求与配送时限.xlsx',
            '运输无人机数据.xlsx','中继无人机数据.xlsx')]
    dem=list(data.rglob('镇龙乡及周边30米DEM.mat'))
    if not all(p.is_file() for p in files) or len(dem)!=1:
        raise ValueError('Expected five source workbooks and one DEM')
    files+=dem+[source,Q3/'缓存/中继候选位置.json',Q3/'缓存/区间几何.json']
    inputs={str(p.resolve()):digest(p) for p in files}
    frozen=root/'核验输入指纹.json'
    if frozen.exists() and load(frozen)['files']!=inputs:
        raise ValueError('Input files differ from the first collector snapshot')
    if not frozen.exists():
        write(frozen,dict(captured_utc=datetime.now(timezone.utc).isoformat(),files=inputs,
                         limitation='Raw-input snapshot starts at collector preflight, not retroactively at solver launch.'))
    dependencies=['check_q3_background.py','verify_q3.py','q3_inputs.py','q3_common.py',
                  'q3_direct_milp.py','solve_q3_global.py','search_q3_neighborhood_worker.py',
                  '审查资料/audit_source_and_result.py','审查资料/battery_location_audit.py']
    scripts={name:digest(Q3/name) for name in dependencies}
    result=dict(input_files=inputs,scripts=scripts,source_sha256=launch['source_sha256'])
    result['sha256']=value_sha(result)
    return result


def valid_certificate(marker, fingerprint_sha):
    try:
        record=load(marker)
        if record.get('status')!='PASS' or record.get('fingerprint_sha256')!=fingerprint_sha:return False
        bindings=record.get('file_bindings',{})
        required={record['candidate_file'],record['verified_file']}
        if not required<=set(bindings):return False
        return all(digest(path)==sha for path,sha in bindings.items())
    except (OSError,ValueError,KeyError,TypeError):return False


def source_candidates(root):
    # Prefer the unmodified solver candidate. A neighborhood's two PASS aliases
    # must not count as two plans and must not overwrite each other's evidence.
    folders={p.parent for name in ('候选方案_待独立物理核验.json','verified_plan.json')
             for p in root.rglob(name) if '独立核验归档' not in p.parts}
    for folder in sorted(folders,key=str):
        pending=folder/'候选方案_待独立物理核验.json'
        yield pending if pending.exists() else folder/'verified_plan.json'


def solver_scope(path,plan,fp):
    result_path=path.parent/'直接联合MILP结果.json'
    result=load(result_path)
    if value_sha(payload(result['candidate_plan']))!=value_sha(payload(plan)):
        raise ValueError('Candidate differs from the solver result payload')
    scope=dict(result['scope']);scope.update(epsilon_caps=result.get('epsilon_caps',{}),
                                            scalar_objective=result.get('scalar_objective'))
    manifest=path.parent/'冻结候选库清单.json'
    if manifest.exists():
        library=load(manifest)
        if library.get('source_sha256')!=fp['source_sha256']:
            raise ValueError('Solver manifest does not match the launch library')
        if library.get('instances')!=1596 or library.get('patterns')!=1424:
            raise ValueError('Expanded global solver must use 1424 patterns / 1596 instances')
        scope['library_scope']='expanded_global_library'
    else:
        manifest=path.parent/'neighborhood_manifest.json';library=load(manifest)
        scope['library_scope']='this_neighborhood_only'
    scope['library_sha256']=digest(manifest)
    obj=list(map(float,plan['objective']))
    if len(obj)!=4 or not all(math.isfinite(v) for v in obj):raise ValueError('Invalid objective vector')
    tolerances=dict(N=1e-6,E=2e-6,C=2e-4,L=2e-4)
    for key,cap in scope['epsilon_caps'].items():
        if obj[('N','E','C','L').index(key)]>float(cap)+tolerances[key]:
            raise ValueError('Candidate violates its epsilon cap: '+key)
    if obj[2]>float(scope['horizon_s'])+2e-4:raise ValueError('Candidate exceeds finite horizon')
    return scope,{str(result_path):digest(result_path),str(manifest):digest(manifest)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--preflight-only',action='store_true')
    args = parser.parse_args()
    root = Path(args.run).resolve(); root.relative_to(Q3.resolve())
    fp=fingerprint(root)
    if args.preflight_only:
        print(json.dumps(dict(status='COLLECTOR_PREFLIGHT_PASS',fingerprint=fp['sha256']),ensure_ascii=False));return
    state = load(root/'后台状态.json')
    newly_checked = []
    for path in source_candidates(root):
        sha = digest(path)
        marker = path.parent/'完整候选核验.json'
        if marker.exists() and valid_certificate(marker,fp['sha256']):
            continue
        try:
            plan = load(path)
            scope,bindings=solver_scope(path,plan,fp)
            raw = audit(plan)
            location = audit_locations(plan)
            verifier = Verifier(plan)
            verifier.verify_routes(); verifier.verify_boxes(); verifier.verify_relays()
            geometry = verifier.finish()
            passed = raw['status'] == 'PASS' and location['status'] == 'PASS' and geometry['passed']
            if digest(path)!=sha:raise ValueError('Candidate changed while being verified; retry next poll')
            record = dict(status='PASS' if passed else 'FAIL', candidate_sha256=sha,
                          candidate_file=str(path),fingerprint_sha256=fp['sha256'],
                          payload_sha256=value_sha(payload(plan)),finite_model_scope=scope,
                          finite_model_scope_sha256=value_sha(scope),
                          raw_check_count=len(raw['checks']), DEM_check_count=len(geometry['checks']),
                          location_check_count=len(location['checks']), objective=plan['objective'],
                          scope='No spare carried, only O01 swapping, restricted finite model.',
                          full_space_optimality=False)
            archive=path.parent/'独立核验归档'
            reports={'原始数据核验.json':raw,'完整DEM核验.json':geometry,'电池位置核验.json':location}
            for name,value in reports.items():
                report=archive/name;write(report,value);bindings[str(report)]=digest(report)
            if passed:
                plan['status'] = 'independently_verified_background_candidate'
                plan['verification_status'] = 'PASS'
                plan['expert_swap_scope'] = 'Only O01 swapping used; no carried spare; remote swapping not searched.'
                verified=archive/'已核验方案.json';write(verified,plan)
                record['verified_file']=str(verified);bindings[str(verified)]=digest(verified)
            bindings[str(path)]=sha;record['file_bindings']=bindings
            write(marker, record)
            newly_checked.append(dict(path=str(path), **record))
        except Exception as error:
            record = dict(status='ERROR', candidate_sha256=sha, error=type(error).__name__+': '+str(error))
            write(marker, record); newly_checked.append(dict(path=str(path), **record))
    candidates=[];seen=set()
    for marker in root.rglob('完整候选核验.json'):
        if not valid_certificate(marker,fp['sha256']):continue
        record=load(marker)
        if record['payload_sha256'] in seen:continue
        seen.add(record['payload_sha256'])
        candidates.append(dict(file=record['verified_file'],objective=record['objective'],
                               certificate_file=str(marker),finite_model_scope=record['finite_model_scope'],
                               finite_model_scope_sha256=record['finite_model_scope_sha256']))
    # Physical objective comparisons across different finite libraries are only
    # descriptive. Never combine a neighborhood bound with a full-library UB.
    reference=Path(load(state['config']).get('comparison_reference',
                   str(Q3/'搜索精修/扩展固定结构精修_v1/official/已核验方案.json')))
    old=load(reference)['objective'] if reference.is_file() else None
    dominating=[]
    if old is not None:
        dominating=[p for p in candidates if all(a<=b+1e-5 for a,b in zip(p['objective'],old))
                    and any(a<b-1e-5 for a,b in zip(p['objective'],old))]
    checkpoint = dict(updated_utc=datetime.now(timezone.utc).isoformat(), coordinator_status=state['status'],
                      elapsed_s=state['elapsed_s'], remaining_s=state['remaining_s'],
                      jobs=state['jobs'],fingerprint_sha256=fp['sha256'],verification_fingerprint=fp,
                      verified_candidates=candidates, verified_count=len(candidates),
                      dominating_presearch_reference=dominating, newly_checked=newly_checked,
                      reference_file=str(reference),reference_objective=old,
                      reference_comparison_scope='Descriptive four-objective comparison to external historical reference; not a same-model bound/gap certificate.',
                      limitation='Feasibility and improvements in the O01-only strategy; no original global optimality claim.')
    write(root/'轮询核验汇总.json', checkpoint)
    print(json.dumps(dict(status=state['status'], verified_count=len(candidates),
                          improvements=len(dominating), newly_checked=len(newly_checked),
                          remaining_s=state['remaining_s']), ensure_ascii=False))


if __name__ == '__main__':
    main()
