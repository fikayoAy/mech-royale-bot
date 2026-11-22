import os
"""Small in-container measurement run; recorded inputs do not react to actions."""
import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
KIT=Path(os.environ.get('MECHFIGHT_KIT',str(ROOT/'work/official-kit/mechfight-kit')))
PROGRAM="""
import json,sys,os,resource,time,statistics
from bot import Bot
messages=[json.loads(line) for line in sys.stdin if line.strip()]
hello=messages[0];hello['map']['dir']='/arena'
bot=Bot(hello);times=[]
for obs in messages:
 if obs.get('type')!='obs':continue
 start=time.perf_counter_ns();bot.decide(obs);times.append((time.perf_counter_ns()-start)/1e6)
out={'uid':os.getuid(),'observations':len(times),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
     'p50_ms':statistics.median(times),'p99_ms':sorted(times)[int(len(times)*.99)],'map':bot.arena.summary(),
     'note':'Recorded workload under the sandbox, not a match. Peak RSS includes map/model.'}
print(json.dumps(out))
"""


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--image',default='mech-agent:map-aware')
    ap.add_argument('--reports-dir',type=Path,default=ROOT/'reports/vm')
    args=ap.parse_args()
    with gzip.open(KIT/'check/stream.jsonl.gz','rt') as f:stream=f.read()
    command=['sudo','docker','run','--rm','-i','--platform','linux/amd64','--network','none','--cpus','1','--memory','512m',
             '--read-only','--tmpfs','/tmp:rw,size=64m','--user','65534:65534','-v',str(KIT/'arena')+':/arena:ro',
             '--entrypoint','python3',args.image,'-c',PROGRAM]
    result=subprocess.run(command,input=stream,capture_output=True,text=True,timeout=90)
    if result.returncode:print(result.stderr,file=sys.stderr);raise SystemExit(result.returncode)
    report=json.loads(result.stdout);report['command']=command
    args.reports_dir.mkdir(parents=True,exist_ok=True)
    (args.reports_dir/'sandbox-memory.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='command'},indent=2))


if __name__=='__main__':main()
