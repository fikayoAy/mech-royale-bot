"""Bounded match measurements. No stdout logs or default filesystem writes."""
from collections import Counter,deque
import json
import math
import os
from pathlib import Path


class Telemetry:
    def __init__(self,policy):
        self.policy=policy;self.latencies=deque(maxlen=1024);self.modes=Counter();self.last=None
        self.actions=0;self.errors=0;self.late=0;self.max_ms=0.;self.stuck_seconds=0.;self.zone_seconds=0.
        self.zone_damage=0.;self.weapon_damage=0.;self.damage_dealt=0.;self.ammo_spent=0
        self.firing_actions=0;self.budget_fallbacks=0;self.end_message=None

    def observe(self,obs,action,elapsed_ms):
        me=obs.get('self',{});now=obs.get('t',0.);p=me.get('pos',[0.,0.,0.])
        self.actions+=1;self.latencies.append(elapsed_ms);self.max_ms=max(self.max_ms,elapsed_ms);self.late+=elapsed_ms>=50
        self.firing_actions+=any(action.get('fire',[]))
        if self.last:
            dt=max(0.,min(2.,now-self.last['t']))
            if not me.get('in_zone',True):self.zone_seconds+=dt
            if math.hypot(*self.last['move'])>.25 and math.dist(p[:2],self.last['pos'][:2])<.08 and me.get('grounded',True):self.stuck_seconds+=dt
            weapons=me.get('weapons',[])
            ammo=next((w.get('ammo') for w in weapons if isinstance(w,dict) and w.get('kind')=='gun'),None)
            if ammo is not None and self.last['ammo'] is not None:self.ammo_spent+=max(0,self.last['ammo']-ammo)
        for event in obs.get('events',[]):
            amount=max(0.,event.get('amount',0.))
            if event.get('type')=='damaged':
                if event.get('weapon')=='zone':self.zone_damage+=amount
                else:self.weapon_damage+=amount
            if event.get('type')=='hit':self.damage_dealt+=amount
        ammo=next((w.get('ammo') for w in me.get('weapons',[]) if isinstance(w,dict) and w.get('kind')=='gun'),None)
        self.last={'t':now,'pos':p[:],'move':action.get('move',[0,0]),'ammo':ammo}

    def summary(self,bot):
        samples=sorted(self.latencies)
        pct=lambda f:samples[min(len(samples)-1,int((len(samples)-1)*f))] if samples else 0.
        return {'schema':'mech-match-summary/1','actions':self.actions,'errors':self.errors,'mode_counts':dict(self.modes),
                'decision_ms':{'p50_recent':pct(.5),'p95_recent':pct(.95),'p99_recent':pct(.99),'max':self.max_ms,'late':self.late},
                'stuck_seconds':self.stuck_seconds,'zone_seconds':self.zone_seconds,'zone_damage':self.zone_damage,
                'weapon_damage_received':self.weapon_damage,'damage_dealt':self.damage_dealt,'ammo_spent':self.ammo_spent,
                'firing_actions':self.firing_actions,'budget_fallbacks':self.budget_fallbacks,'policy':self.policy.export(),
                'encounters':bot.encounters.summary(),'prediction_metrics':dict(bot.world.metrics),'end':self.end_message,
                'latency_sample_cap':1024,'score_source':'end message; recorded fixtures are not genuine match results',
                'score':(16-self.end_message['place']) if self.end_message and 'place' in self.end_message else None}

    def export(self,bot,message):
        self.end_message=dict(message);summary=self.summary(bot)
        destination=os.environ.get('MECH_TELEMETRY_FILE')
        if destination:
            path=Path(destination).resolve()
            if Path('/tmp').resolve() not in path.parents:raise ValueError('Telemetry files must be inside /tmp')
            path.write_text(json.dumps(summary,separators=(',',':')),encoding='utf-8')
        if os.environ.get('MECH_TELEMETRY_STDERR','1')=='1':
            import sys
            compact={k:v for k,v in summary.items() if k not in ('policy','encounters')}
            compact['encounters']={k:v for k,v in summary['encounters'].items() if k not in ('recent','escape_definition','loss_definition')}
            print(json.dumps(compact,separators=(',',':')),file=sys.stderr,flush=True)
        return summary
