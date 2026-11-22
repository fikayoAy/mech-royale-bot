"""Check saved release gates and source identity; never creates a match score."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/'reports';VM=REPORTS/'roadmap-amd64'


def main():
    sandbox=json.loads((VM/'sandbox-suite.json').read_text())
    expected={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.glob('*.py'))}
    source_match=expected==sandbox['runtime_sha256']
    runs=[]
    for level in range(1,6):
        report=json.loads((VM/f'strictness_level_{level}.json').read_text());runs.extend(report['runs'])
        (REPORTS/f'strictness_level_{level}.json').write_text(json.dumps(report,indent=2)+'\n')
    checker_files=sorted(VM.glob('repeat-*/official-docker-linux-amd64.json')) or [VM/'official-docker-linux-amd64.json']
    checkers=[json.loads(p.read_text()) for p in checker_files]
    errors=('invalid_actions','missed_ticks','exceptions','safety_rule_violations','assertion_failures','timing_failures')
    green=source_match and sandbox['passed'] and all(not any(r[k] for k in errors) for r in runs) and all(r['exit_code']==0 for r in checkers)
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    size=sum((ROOT/p).stat().st_size for p in paths if p and (ROOT/p).is_file())
    green=green and size<=20_000_000 and sandbox['peak_rss_bytes']<=512*1024**2
    build=json.loads((VM/'build-final.json').read_text());green=green and build['exit_code']==0 and build['seconds']<=600
    gates={'all_five_levels':all(not any(r[k] for k in errors) for r in runs),'unit_tests':sandbox['unit_failures']==0,
           'official_checker':all(r['exit_code']==0 for r in checkers),'runtime_source_hashes_match':source_match,
           'repository_under_20_MB':size<=20_000_000,'build_under_10_minutes':build['seconds']<=600,
           'memory_under_512_MiB':sandbox['peak_rss_bytes']<=512*1024**2}
    summary={'captured_utc':datetime.now(timezone.utc).isoformat(),'release_gates_pass':bool(green),'gates':gates,
        'host_architecture':sandbox['architecture'],'uid':sandbox['uid'],'runtime_module':sandbox['runtime_module'],
        'unit_tests':sandbox['unit_tests'],'strictness_levels':5,'seeds':sorted({r['seed'] for r in runs}),
        'strictness_actions':sum(r['actions'] for r in runs),'strictness_late_actions':sum(r['late_actions'] for r in runs),
        'worst_strictness_p99_ms':max(r['latency_ms']['p99'] for r in runs),'peak_stress_rss_bytes':sandbox['peak_rss_bytes'],
        'official_container_runs':len(checkers),'official_reports':[str(p.relative_to(ROOT)) for p in checker_files],
        'build_seconds':build['seconds'],'tracked_tree_bytes':size,'runtime_sha256':expected,
        'build_sha256':hashlib.sha256((ROOT/'Dockerfile').read_bytes()).hexdigest(),
        'sandbox':'1 CPU; 512 MiB; uid 65534; network none; read-only root and arena; /tmp 64 MiB',
        'match_result_for_this_version':None,'note':'Scripted and recorded inputs test implementation, not placement or victories.'}
    kit=Path(os.environ.get('MECHFIGHT_KIT',str(ROOT/'work/official-kit/mechfight-kit')))
    candidates=[ROOT/'work/mechfight-kit.tar.gz',kit.parents[1]/'mechfight-kit.tar.gz']
    archive=next((p for p in candidates if p.is_file()),None)
    summary['official_kit_archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest() if archive else None
    (REPORTS/'validation_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (REPORTS/'test_matrix.md').write_text('Native AMD64; official sandbox limits. Synthetic and recorded inputs, not matches.\n\n'+(VM/'test_matrix.md').read_text())
    (REPORTS/'official-native.json').write_bytes((VM/'official-native.json').read_bytes())
    (REPORTS/'map_coverage.json').write_bytes((VM/'map_coverage.json').read_bytes())
    print(json.dumps({k:v for k,v in summary.items() if k not in ('runtime_sha256','official_reports')},indent=2))
    if not green:raise SystemExit(1)


if __name__=='__main__':main()
