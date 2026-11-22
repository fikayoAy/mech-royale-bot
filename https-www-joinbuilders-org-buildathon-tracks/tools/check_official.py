"""Run the unchanged official checker and save exact commands and evidence."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
KIT=Path(os.environ.get('MECHFIGHT_KIT',str(ROOT/'work/official-kit/mechfight-kit')))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sample',action='store_true')
    parser.add_argument('--image')
    parser.add_argument('--platform',default='linux/amd64')
    parser.add_argument('--reports-dir',type=Path,default=ROOT/'reports')
    args=parser.parse_args()
    checker=[sys.executable,str(KIT/'check/check.py')]
    if args.image:
        checker+=['--map-dir','/arena','--']
        command=(['sudo'] if os.name!='nt' and os.geteuid()!=0 else [])+['docker','run','--rm','-i','--platform',args.platform,
            '--network','none','--cpus','1','--memory','512m','--read-only','--tmpfs','/tmp:rw,size=64m','--user','65534:65534',
            '-v',str(KIT/'arena')+':/arena:ro',args.image]
        name='official-docker-'+args.platform.replace('/','-')
    else:
        command=[sys.executable,'-u',str(KIT/'python/example_bot.py' if args.sample else ROOT/'bot.py')]
        checker+=['--']
        name='official-starter' if args.sample else 'official-native'
    started=time.monotonic()
    result=subprocess.run(checker+command,cwd=ROOT,capture_output=True,text=True,timeout=120)
    report={'captured_utc':datetime.now(timezone.utc).isoformat(),'host_system':platform.platform(),
            'host_architecture':platform.machine(),'python':platform.python_version(),
            'command':checker+command,'exit_code':result.returncode,'elapsed_seconds':time.monotonic()-started,
            'stdout':result.stdout,'stderr':result.stderr,
            'note':'Conformance/timing on recorded observations. No match or placement result. AMD64 on an ARM host uses emulation.'}
    args.reports_dir.mkdir(parents=True,exist_ok=True)
    (args.reports_dir/(name+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(result.stdout,end='');print(result.stderr,end='',file=sys.stderr)
    raise SystemExit(result.returncode)


if __name__=='__main__':main()
