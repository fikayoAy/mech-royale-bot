"""Survival-first mechfight/1 agent. Runtime: Python standard library only."""
import math
import os
import random
import time
import mechfight as mf
from arena_map import ArenaMap
from navigation import Navigator
from virtual_map import VirtualMap
from config import load_policy
from behavior_profiler import BehaviorProfiler
from encounters import EncounterTracker
from telemetry import Telemetry
from survival import Survival
from decision_engine import DecisionEngine
from target_selector import assess,score as target_score


def clamp(x,lo,hi):
    try:
        x=float(x)
        return max(lo,min(hi,x)) if math.isfinite(x) else lo
    except (TypeError,ValueError):return lo


def vec(v,n=3):
    return [clamp(x,-1e6,1e6) for x in v[:n]] if isinstance(v,(list,tuple)) and len(v)>=n else [0.]*n


def dist(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])


def adelta(a,b):
    return (a-b+math.pi)%math.tau-math.pi


def items(o,key):
    return [x for x in o.get(key,[]) if isinstance(x,dict)] if isinstance(o.get(key),list) else []


DEFAULTS={'radius':2.5,'height':9.,'eye_height':8.,'muzzle_height':7.,'walk_speed':11.7,
          'boost_speed':19.5,'ground_accel':58.5,'air_accel':12.,'gravity':22.,'jump_speed':11.,
          'jet_accel':34.,'max_rise_speed':10.,'step_up':1.2,'max_slope_deg':50.,
          'jet_drain':15.,'boost_drain':17.,'min_pitch':-.7,'max_pitch':1.3}


class Bot:
    name='mech-royale-survivor'

    def __init__(self,hello=None,policy=None):
        self.policy=load_policy(policy);self.profiler=BehaviorProfiler(self.policy)
        self.encounters=EncounterTracker(self.policy,self.profiler);self.telemetry=Telemetry(self.policy)
        self.survival=Survival(self.policy);self.controller=DecisionEngine(self.policy)
        self.rng=random.Random(0);self.tracks={};self.npcs={};self.heat={}
        self.last_pos=None;self.stuck=0;self.last_move=[0.,0.]
        self.arena=ArenaMap();self.nav=Navigator(self.arena);self.config={}
        self.stats=dict(DEFAULTS);self.world=VirtualMap(self.arena,self.config)
        self.world.policy=self.policy
        self.debug_map=os.environ.get('MECH_DEBUG_MAP')=='1';self.last_map_revision=-1
        self.goal=None;self.goal_until=0.;self.target_id=None;self.target_until=0.
        self.mode='observe';self.jet=None;self.predictions=[];self.last_now=0.;self.blocked=0
        self.metrics=self.world.metrics
        if hello:self.hello(hello)

    def hello(self,m):
        self.rng.seed(int(m.get('seed',0) or 0))
        self.config=m.get('config',{}) if isinstance(m.get('config'),dict) else {}
        self.world.config=self.config
        info=m.get('map',{}) if isinstance(m.get('map'),dict) else {}
        if info.get('dir'):
            self.arena=ArenaMap.load(info['dir']);self.nav=Navigator(self.arena);self.world.arena=self.arena
            if self.arena.load_error:mf.log('Map unavailable:',self.arena.load_error)

    def act(self,o):
        return self.decide(o)

    def end(self,message):
        self.encounters.end(self.last_now,message)
        return self.telemetry.export(self,message)

    def fallback(self,o):
        """Constant-work escape toward the known zone. No firing or pickup."""
        me=o.get('self',{});p=vec(me.get('pos'));center=vec(o.get('zone',{}).get('center'),2)
        dx,dy=center[0]-p[0],center[1]-p[1];n=max(1.,math.hypot(dx,dy))
        return {'tick':int(o.get('tick',0)),'move':[dx/n,dy/n],'aim':vec(me.get('aim'),2),
                'boost':me.get('in_zone') is False and me.get('energy',0)>self.policy.escape_reserve,
                'jump':False,'fire':[False,False],'reload':False}

    def predict(self,t,now):
        self.world.arena=self.arena;self.world.stats=self.stats
        return self.world.predict(t,now)

    def remember(self,o,now,p):
        self.world.arena=self.arena;self.world.config=self.config
        self.world.update(o,self.stats)
        self.profiler.update(self.world,o);self.encounters.update(self.world,o)
        self.world._risk_cache.clear()
        self.tracks=self.world.tracks;self.npcs=self.world.npcs;self.heat=self.world.heat
        self.predictions=self.world.predictions
        if self.world.revision!=self.last_map_revision:
            if self.goal and self.world.risk(self.goal)>getattr(self,'goal_risk',0.)+.3:self.goal_until=0.
            self.last_map_revision=self.world.revision

    def risk(self,q):
        return self.world.risk(q)

    def candidates(self,o,now,p):
        choices=[]
        for e in items(o,'mechs'):
            if e.get('kind','mech')!='mech' or e.get('id')==o.get('self',{}).get('id'):continue
            q,v=vec(e.get('pos')),vec(e.get('vel'))
            choices.append((e,q,v,1.))
        for eid,t in self.tracks.items():
            if any(x[0].get('id')==eid for x in choices):continue
            q,c,u=self.predict(t,now)
            if c>0:choices.append(({'id':eid,'hp':t['hp'],'max_hp':t['max_hp'],'inferred':True},q,t['vel'],c))
        if not choices:return None
        def score(x):return target_score(self,o,x)
        # Current sensor reports take priority over our own extrapolated
        # tracks, so a remembered opponent cannot prevent a real defensive shot.
        sensed=[x for x in choices if not x[0].get('inferred')]
        pool=sensed or choices
        best=max(pool,key=score)
        held=next((x for x in pool if x[0].get('id')==self.target_id),None)
        if held and now<self.target_until and score(held)>=score(best)*self.policy.target_switch_ratio:best=held
        if best[0].get('id')!=self.target_id:self.target_until=now+self.policy.target_hold_s
        self.target_id=best[0].get('id')
        return best

    def safe_goal(self,p,center,radius,now,urgent):
        if self.goal and now<self.goal_until and dist(self.goal,center)<max(0.,radius-8) and self.risk(self.goal)<1.4:
            return self.goal
        options=[list(center)]
        for fraction in (.25,.5,.72):
            for i in range(16):
                a=math.tau*i/16
                options.append([center[0]+math.cos(a)*radius*fraction,center[1]+math.sin(a)*radius*fraction])
        options.append(p[:2])
        # Every risk term is nonnegative. Visit cheap distance lower bounds first
        # and stop once no remaining candidate can beat the current best score.
        ordered=[]
        for q in options:
            if dist(q,center)>max(0.,radius-5) and radius>5:continue
            if not self.arena.in_bounds(q,self.stats['radius']):continue
            lower=dist(p,q)*(.15 if not urgent else 1.)
            if dist(q,center)>radius*.65:lower+=15
            ordered.append((lower,q))
        best=None
        for lower,q in sorted(ordered,key=lambda x:x[0]):
            if best is not None and lower>best[0]:break
            z=self.arena.surface(q[0],q[1],p[2]+self.stats.get('step_up',1.2))
            if self.arena.solid_at([*q,z],self.stats['radius'],self.stats['height']):continue
            score=lower+self.risk(q)*self.policy.goal_risk_weight
            if best is None or score<best[0]:best=(score,q)
        self.goal=best[1] if best else list(center)
        self.goal_until=now+self.policy.goal_hold_s;self.goal_risk=self.risk(self.goal)
        return self.goal

    def incoming(self,o,p,vel):
        self.world.arena=self.arena;self.world.stats=self.stats
        threats=self.world.projectile_threats(items(o,'projectiles'),p,vel)
        return [(h['pos'],h['vel']) for h in threats]

    def decide(self,o):
        start=time.perf_counter();self.deadline=start+self.policy.decision_budget_ms/1000
        try:action=self._decide(o)
        except Exception:
            self.telemetry.errors+=1
            raise
        self.telemetry.modes[self.mode]+=1
        self.telemetry.observe(o,action,(time.perf_counter()-start)*1000)
        return action

    def _decide(self,o):
        tick=int(o.get('tick',0) or 0);now=clamp(o.get('t',tick/20),0,1e7);self.last_now=now
        me=o.get('self') if isinstance(o.get('self'),dict) else {}
        p,vel=vec(me.get('pos')),vec(me.get('vel'))
        self.stats=dict(DEFAULTS)
        self.stats.update({k:v for k,v in self.config.get('mech',{}).items() if isinstance(v,(int,float)) and math.isfinite(v)})
        self.stats.update({k:v for k,v in me.get('stats',{}).items() if isinstance(v,(int,float)) and math.isfinite(v)})
        self.nav.configure(self.stats)
        self.remember(o,now,p)
        if time.perf_counter()>self.deadline:
            self.telemetry.budget_fallbacks+=1;return self.fallback(o)
        zone=o.get('zone') if isinstance(o.get('zone'),dict) else {}
        center=vec(zone.get('center'),2);nc=vec(zone.get('next_center',center),2)
        radius=clamp(zone.get('radius',500),0,1e6);nr=clamp(zone.get('next_radius',radius),0,1e6)
        soon=clamp(zone.get('shrink_start',1e9),0,1e9)-now
        travel=dist(p,nc)/max(1.,self.stats['walk_speed'])*1.35
        urgent=dist(p,center)>radius-12 or (soon<travel+5 and dist(p,nc)>nr-15) or me.get('in_zone') is False
        use_next=soon<max(30.,travel+10)
        safe_center,safe_radius=(nc,nr) if use_next else (center,radius)
        weak=self.survival.update(o,self.world)
        pursuit=self.survival.pursuit(self.world)
        local_risk=self.risk(p)
        threats=[(h['pos'],h['vel']) for h in self.world.hazards];danger=local_risk>self.policy.danger_enter or bool(threats)
        target=self.candidates(o,now,p)
        self.fight=assess(self,o,target)
        goal=self.safe_goal(p,safe_center,safe_radius,now,urgent)
        loot=[]
        # Visible resources only. Never invent NPC homes or random loot positions.
        if not urgent and not danger and not self.survival.recovering:
            held=[w.get('kind') for w in me.get('weapons',[]) if isinstance(w,dict)]
            empty=any(w is None for w in me.get('weapons',[None,None])) or len(me.get('weapons',[]))<2
            resources=items(o,'cubes')+([x for x in items(o,'pickups') if empty and x.get('kind') not in held])
            resources += [x for x in items(o,'drops') if x.get('lands_in',1)>-1 and x.get('lands_in',1)<=0 and x.get('holder') in (None,me.get('id'))]
            for x in resources:
                q=vec(x.get('pos'))
                if dist(p,q)<self.policy.loot_radius and abs(q[2]-p[2])<self.stats['step_up']+1 and dist(q,safe_center)<safe_radius-12 and self.risk(q)<.6:
                    loot.append((dist(p,q),q))
        self.mode=self.controller.choose(now,urgent,bool(threats),weak,self.survival.recovering,local_risk,
                                         bool(pursuit),self.fight['advantage'],bool(target and not target[0].get('inferred')),bool(loot))
        if self.mode=='gather' and loot:goal=min(loot,key=lambda x:x[0])[1]
        moved=self.last_pos is not None and dist(p,self.last_pos)>.2
        if self.last_pos is not None and not moved and math.hypot(*self.last_move)>.3 and math.hypot(*vel[:2])<1:self.stuck+=1
        else:self.stuck=max(0,self.stuck-1)
        self.last_pos=p
        if self.stuck>=5 and self.stuck%5==0:
            self.nav.invalidate();self.metrics['stuck_replans']+=1
            self.goal_until=0.
        # Persistently blocked movement gets a different checked escape heading.
        # It still passes through the same cylinder/terrain steering checks.
        recovery_heading=None
        if self.stuck>=10:
            angle=(int(self.stuck/10)%8)*math.pi/4+self.rng.random()*.05
            recovery_heading=[math.cos(angle),math.sin(angle)]
        self.current_goal=list(goal)
        waypoint=self.nav.waypoint(p,goal,self.risk,now,budget_ms=self.policy.navigation_budget_ms,revision=self.world.revision)
        desired=[waypoint[0]-p[0],waypoint[1]-p[1]]
        if math.hypot(*desired)<.1 and dist(p,goal)>3 and self.nav.status in ('searching','refining','no_route','no_anchor'):
            desired=[goal[0]-p[0],goal[1]-p[1]]
        if target and self.mode=='engage' and not target[0].get('inferred') and dist(p,target[1])<110:
            q=target[1];away=[p[0]-q[0],p[1]-q[1]];n=max(1.,math.hypot(*away))
            spacing=clamp((self.policy.preferred_range-n)/25,-.5,.7)
            desired=[-away[1]/n*.7+away[0]/n*spacing,away[0]/n*.7+away[1]/n*spacing]
        if recovery_heading:desired=recovery_heading
        if threats:
            q,sv=min(threats,key=lambda x:dist(p,x[0]));side=[-sv[1],sv[0]]
            if side[0]*(p[0]-q[0])+side[1]*(p[1]-q[1])<0:side=[-x for x in side]
            desired=side;self.mode='evade'
        if me.get('grounded',True):
            move=self.nav.steer(p,desired,vel,self.stats,self.risk,self.stuck>=5)
        else:
            move=self.nav.steer_air(p,desired,me,self.stats,bool((urgent or threats) and me.get('energy',100)>8),self.risk)
        # A jet climb is an escape tool after a blocked route, not normal travel.
        self.blocked=self.blocked+1 if math.hypot(*move)<.2 and dist(p,goal)>3 else 0
        if not self.jet and max(self.stuck,self.blocked)>=8 and not threats and math.hypot(*move)<.2:
            self.jet=self.nav.jet_plan(p,[goal[0]-p[0],goal[1]-p[1]],me,self.stats)
            if self.jet:self.jet['expires']=now+self.jet['needed_seconds']+2.
        boost=self.survival.boost(me,bool(urgent or threats),bool(pursuit),self.mode in ('disengage','recover','reposition'))
        jump=bool(threats and me.get('grounded') and me.get('energy',100)>8)
        if self.jet:
            if now>self.jet['expires'] or me.get('energy',0)<10:self.jet=None
            else:
                self.mode='jet_escape';boost=True;jump=bool(me.get('grounded'))
                if p[2]<self.jet['top']:move=[0.,0.]
                else:
                    q=self.jet['goal']
                    n=max(1.,dist(p,q));move=[(q[0]-p[0])/n,(q[1]-p[1])/n]
                    if not self.arena.flight_segment(p,[q[0],q[1],p[2]],self.stats):
                        self.jet=None;move=[0.,0.];boost=False
                    if dist(p,q)<1.5:self.jet=None;self.nav.invalidate()
        self.last_move=move
        if time.perf_counter()>self.deadline:
            self.telemetry.budget_fallbacks+=1
            action=self.fallback(o);action.update(move=move,boost=boost,jump=jump)
            return action
        from combat import aim_and_fire
        unsafe=weak or danger or urgent or self.mode in ('disengage','recover')
        aim,fire=aim_and_fire(self,o,p,target,unsafe)
        if self.mode=='recover' and not pursuit and local_risk<self.policy.danger_exit:
            fire=[False,False]
        if self.mode=='observe' and not target:
            aim=[(now/self.policy.scan_period_s*math.tau+math.pi)%math.tau-math.pi,0.]
        action={'tick':tick,'move':[clamp(x,-1,1) for x in move],'boost':boost,'jump':jump,
                'aim':aim,'fire':fire,'reload':self.survival.reload(me,not target and not danger and not urgent)}
        if not self.survival.recovering and not danger and not urgent:
            action.update(self.survival.pickup(me,items(o,'pickups'),self.config))
        offer=o.get('offer');choices=offer.get('choices',[]) if isinstance(offer,dict) else []
        if choices:
            action['pick']=self.survival.upgrade(choices,me,self.config)
        if self.debug_map:action['debug']=self.world.debug_draw(self.nav.route or [getattr(self.nav,'last_waypoint',p)],goal,self.mode)
        return action


if __name__=='__main__':
    mf.run(Bot)
