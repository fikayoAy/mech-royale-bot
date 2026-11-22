"""Run all five levels and unit tests inside the exact official runtime sandbox.

Harness and kit are separate read-only mounts. Runtime imports come from /bot
inside the built image. The harness returns its small reports through stdout.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
KIT=Path(os.environ.get('MECHFIGHT_KIT',str(ROOT/'work/official-kit/mechfight-kit')))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--image',default='mech-agent:roadmap')
    ap.add_argument('--reports-dir',type=Path,default=ROOT/'reports/roadmap-amd64');args=ap.parse_args()
    docker=(['sudo'] if os.geteuid()!=0 else [])+['docker']
    name='mech-roadmap-check-'+str(os.getpid())
    run=docker+['run','--name',name,'--platform','linux/amd64','--network','none','--cpus','1','--memory','512m',
        '--read-only','--tmpfs','/tmp:rw,size=64m','--user','65534:65534',
        '-e','PYTHONDONTWRITEBYTECODE=1','-e','MECHFIGHT_KIT=/kit','-e','MECH_RUNTIME_DIR=/bot',
        '-v',str(KIT)+':/kit:ro','-v',str(KIT/'arena')+':/arena:ro','-v',str(ROOT)+':/suite:ro',
        '--entrypoint','python3',args.image,'-B','/suite/tools/sandbox_suite.py']
    args.reports_dir.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    try:
        result=subprocess.run(run,capture_output=True,text=True,timeout=900)
        # tmpfs disappears when a container stops: the harness sends the small
        # JSON reports over stdout, not via a writable project mount.
        payload=json.loads(result.stdout)
        payload['command']=run;payload['exit_code']=result.returncode;payload['elapsed_seconds']=time.monotonic()-started
        payload['stderr']=result.stderr
        (args.reports_dir/'sandbox-suite.json').write_text(json.dumps(payload,indent=2)+'\n')
        for filename,report in payload['reports'].items():
            (args.reports_dir/filename).write_text(report if isinstance(report,str) else json.dumps(report,indent=2)+'\n')
        print(payload['log']);print('Sandbox peak memory bytes:',payload['peak_rss_bytes'])
        raise SystemExit(result.returncode)
    finally:subprocess.run(docker+['rm','-f',name],capture_output=True)


if __name__=='__main__':main()
