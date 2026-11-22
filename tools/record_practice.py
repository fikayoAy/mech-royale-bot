"""Record a real user-supplied practice receipt. Never submits to the tournament."""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--score',required=True,type=float)
    ap.add_argument('--commit',required=True);ap.add_argument('--receipt',required=True)
    ap.add_argument('--policy',default='survival');ap.add_argument('--notes',default='')
    ap.add_argument('--file',type=Path,default=ROOT/'reports/practice_results.json');args=ap.parse_args()
    if not math.isfinite(args.score) or not 0<=args.score<=15:ap.error('score must be between 0 and 15')
    commit=subprocess.check_output(['git','rev-parse','--verify',args.commit+'^{commit}'],cwd=ROOT,text=True).strip()
    data=json.loads(args.file.read_text()) if args.file.exists() else {'entries':[]}
    if any(x.get('receipt')==args.receipt for x in data['entries']):ap.error('receipt already recorded')
    data['entries'].append({'receipt':args.receipt,'reported_score':args.score,'commit':commit,
        'source':'user-supplied real practice result','recorded_utc':datetime.now(timezone.utc).isoformat(),
        'policy':args.policy,'notes':args.notes,'average_place_from_score':16-args.score})
    best=max(data['entries'],key=lambda x:x['reported_score'])
    data['best_reported_score']=best['reported_score'];data['best_reported_commit']=best.get('commit')
    args.file.parent.mkdir(parents=True,exist_ok=True);args.file.write_text(json.dumps(data,indent=2)+'\n')
    print('Recorded',args.receipt,'score',args.score,'commit',commit)


if __name__=='__main__':main()
