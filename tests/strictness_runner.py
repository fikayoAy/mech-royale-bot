"""Exactly five deterministic policy levels. Conformance and matches are separate."""
import argparse
import copy
import gc
import json
import math
import random
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot import Bot
from arena_map import ArenaMap
from navigation import Navigator
from test_navigation import HELLO,BASE,SCHEMA,actor,observation,prism,KIT
import gzip

REPORTS=ROOT/'reports'
LEVELS={1:'Basic correctness',2:'Missing information',3:'Tactical pressure',
        4:'Adversarial scenarios',5:'Tournament-grade stress'}


def percentile(values,q):
    s=sorted(values)
    return s[max(0,min(len(s)-1,math.ceil(q*len(s))-1))]


def peak_rss():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    except ImportError:
        try:
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),
                          ('PeakWorkingSetSize',ctypes.c_size_t),('WorkingSetSize',ctypes.c_size_t),
                          ('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),
                          ('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),
                          ('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
            c=Counters();c.cb=ctypes.sizeof(c)
            fn=ctypes.windll.kernel32.GetCurrentProcess
            fn.restype=wintypes.HANDLE
            reader=ctypes.windll.psapi.GetProcessMemoryInfo
            reader.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
            if reader(fn(),ctypes.byref(c),c.cb):return c.PeakWorkingSetSize
        except (AttributeError,OSError):pass
    return None


def scenario(level,index,rng):
    o=observation(index*2)
    if level in (1,3,4,5) or index%6==0:o['mechs']=[actor()]
    if level==2:
        o['sounds']=[{'kind':'gun','bearing':rng.uniform(-math.pi,math.pi),'dist':rng.choice(['near','mid','far']),'age':.1}]
    if level>=3 and index%4==0:
        o['self'].update(hp=250.,energy=10.)
        o['zone'].update(radius=85.,next_radius=65.,shrink_start=o['t']+.2,shrink_end=o['t']+20)
        o['pickups']=[{'id':8001,'kind':'mortar','pos':[1.,0.,0.]}]
        o['projectiles']=[{'id':99,'kind':'gun','pos':[4.,0.,1.],'vel':[-10.,0.,0.]}]
    if level>=4:
        o['mechs']=[actor(j,[30*math.cos(j*.4),30*math.sin(j*.4),0.]) for j in range(1,16)]
        o['mechs'].append(actor(104,[10.,0.,0.],'npc'))
        if index%5==0:o['events']=[{'type':'damaged','amount':90.,'weapon':'gun','bearing':0.,'by':1,'rear':True}]
    if level==5:
        if index%7==0:o['self'].update(grounded=False,pos=[0.,0.,12.],vel=[2.,-3.,4.])
        # These assignments happen BEFORE decide(), unlike the old unused stress data.
        for a in o['mechs']:
            a['pos']=[rng.uniform(-200,200),rng.uniform(-200,200),rng.uniform(-5,15)]
            a['vel']=[rng.uniform(-10,10),rng.uniform(-10,10),0.]
        o['projectiles'] += [{'id':1000+j,'kind':rng.choice(['gun','mortar','npc']),
                             'pos':[rng.uniform(-90,90),rng.uniform(-90,90),rng.uniform(0,20)],
                             'vel':[rng.uniform(-100,100),rng.uniform(-100,100),rng.uniform(-30,30)]} for j in range(32)]
        o['sounds']=[{'kind':'gun','bearing':rng.uniform(-math.pi,math.pi),'dist':rng.choice(['near','mid','far']),'age':rng.random()} for _ in range(16)]
    return o


def run_level(level,seed):
    rng=random.Random(seed+level);hello=copy.deepcopy(HELLO)
    hello['seed']=seed
    if level==5:hello['map']['dir']=str(KIT/'arena')
    else:hello['map']={}
    bot=Bot(hello)
    times=[];failures=[];violations=[];invalid=[];exceptions=[];missed=0
    count={1:80,2:120,3:160,4:200,5:1200}[level]
    for i in range(count):
        o=scenario(level,i,rng)
        errors=SCHEMA.errors(o,'Observation')
        if errors:raise AssertionError('Invalid synthetic fixture: '+str(errors))
        try:
            start=time.perf_counter_ns();a=bot.decide(o);elapsed=(time.perf_counter_ns()-start)/1e6
            times.append(elapsed)
            errors=SCHEMA.errors(a,'Action')
            if errors:invalid.extend(errors);break
            if a['tick']!=o['tick']:missed+=1;break
            if not all(math.isfinite(x) for x in a['move']+a['aim']):invalid.append('non-finite action');break
        except Exception as exc:
            exceptions.append(repr(exc));break
        if level>=3 and i%4==0 and o['self']['grounded']:
            if 'take' in a:violations.append('survival override allowed loot')
            for slot,w in enumerate(o['self']['weapons']):
                if w and a['fire'][slot] and w['kind'] not in ('gun','lightning'):violations.append('survival override began a slowing or splash attack')
            if not a['boost'] or (o['self']['grounded'] and not a['jump']):violations.append('incoming projectile not evaded')
        if level==2 and not o['mechs'] and any(a['fire']):violations.append('fired at an inferred track')
        if len(bot.tracks)>15 or len(bot.npcs)>32 or len(bot.heat)>256:violations.append('memory cap exceeded')
    # A full official recorded workload also exercises the actual map at level 5.
    if level==5:
        recorded=Bot(hello)
        with gzip.open(KIT/'check/stream.jsonl.gz','rt') as stream:
            for line in stream:
                o=json.loads(line)
                if o.get('type')!='obs':continue
                start=time.perf_counter_ns();a=recorded.decide(o)
                times.append((time.perf_counter_ns()-start)/1e6)
                if SCHEMA.errors(a,'Action') or a['tick']!=o['tick']:failures.append('recorded action invalid')
        if recorded.arena.load_error:failures.append('official map failed to load')
    if level==2:
        probe=Bot();o=observation();o['mechs']=[actor()];probe.decide(o)
        early=probe.predict(probe.tracks[1],.1);late=probe.predict(probe.tracks[1],2.)
        if early[1]<=late[1] or early[2]>=late[2]:failures.append('lost-track uncertainty did not grow')
    if level>=4 and not bot.npcs:failures.append('observed NPC not represented')
    # Separate allocation sample: tracemalloc must not distort reported action latency.
    gc.collect();tracemalloc.start()
    memory_bot=Bot(hello)
    for i in range(64):memory_bot.decide(scenario(level,i,rng))
    _,python_peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    rss=peak_rss()
    if rss and rss>512*1024**2:failures.append('process RSS exceeded 512 MiB')
    late_count=sum(t>=50 for t in times)
    timing=[]
    if percentile(times,.99)>=40:timing.append('p99 is not below the 40 ms safety target')
    if late_count>len(times)*.02:timing.append('more than 2 percent at/above 50 ms')
    return {'level':level,'name':LEVELS[level],'seed':seed,'actions':len(times),'invalid_actions':len(invalid),
            'missed_ticks':missed,'exceptions':exceptions,'latency_ms':{'median':statistics.median(times),'p95':percentile(times,.95),
            'p99':percentile(times,.99),'max':max(times)},'late_actions':late_count,'peak_python_bytes':python_peak,
            'process_peak_rss_bytes':rss,'memory_note':'process lifetime peak; allocation sample is separate from latency',
            'safety_rule_violations':sorted(set(violations)),'assertion_failures':failures+invalid,'timing_failures':timing,
            'map':bot.arena.summary() if level==5 else None,
            'note':'Synthetic/recorded implementation checks only; no gameplay or placement result. Official Docker checker is a separate gate.'}


def passed(r):
    return not (r['invalid_actions'] or r['missed_ticks'] or r['exceptions'] or r['safety_rule_violations'] or r['assertion_failures'] or r['timing_failures'])


def main():
    ap=argparse.ArgumentParser();group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--level',type=int,choices=range(1,6));group.add_argument('--all',action='store_true')
    ap.add_argument('--seed',type=int,action='append');ap.add_argument('--reports-dir',type=Path,default=REPORTS)
    args=ap.parse_args();selected=list(range(1,6)) if args.all else [args.level]
    reports=[]
    for seed in args.seed or [17]:
        for level in selected:
            r=run_level(level,seed);reports.append(r)
            print(f"Level {level}, seed {seed}: {'PASS' if passed(r) else 'FAIL'}; p99 {r['latency_ms']['p99']:.2f} ms",flush=True)
    args.reports_dir.mkdir(parents=True,exist_ok=True)
    for n in selected:
        (args.reports_dir/f'strictness_level_{n}.json').write_text(json.dumps({'level':n,'name':LEVELS[n],'runs':[r for r in reports if r['level']==n]},indent=2)+'\n')
    rows=['| Level | Seed | Actions | Invalid | p50 ms | p95 ms | p99 ms | Result |','|---:|---:|---:|---:|---:|---:|---:|---|']
    for r in reports:
        t=r['latency_ms'];rows.append(f"| {r['level']} | {r['seed']} | {r['actions']} | {r['invalid_actions']} | {t['median']:.3f} | {t['p95']:.3f} | {t['p99']:.3f} | {'PASS' if passed(r) else 'FAIL'} |")
    (args.reports_dir/'test_matrix.md').write_text('\n'.join(rows)+'\n')
    if not all(passed(r) for r in reports):raise SystemExit(1)


if __name__=='__main__':main()
