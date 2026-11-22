"""Survival-first mechfight/1 agent. Runtime: Python standard library only."""
import math
import random
import mechfight as mf
from arena_map import ArenaMap
from navigation import Navigator


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

    def __init__(self,hello=None):
        self.rng=random.Random(0);self.tracks={};self.npcs={};self.heat={}
        self.last_pos=None;self.stuck=0;self.last_move=[0.,0.]
        self.arena=ArenaMap();self.nav=Navigator(self.arena);self.config={}
        self.goal=None;self.goal_until=0.;self.target_id=None;self.target_until=0.
        self.mode='observe';self.jet=None;self.predictions=[];self.last_now=0.;self.blocked=0
        self.metrics={'prediction_samples':0,'prediction_error_sum':0.,'stuck_replans':0}
        if hello:self.hello(hello)

    def hello(self,m):
        self.rng.seed(int(m.get('seed',0) or 0))
        self.config=m.get('config',{}) if isinstance(m.get('config'),dict) else {}
        info=m.get('map',{}) if isinstance(m.get('map'),dict) else {}
        if info.get('dir'):
            self.arena=ArenaMap.load(info['dir']);self.nav=Navigator(self.arena)
            if self.arena.load_error:mf.log('Map unavailable:',self.arena.load_error)

    def act(self,o):
        return self.decide(o)

    def predict(self,t,now):
        age=max(0.,now-t['seen']);horizon=min(age,1.5)
        q=[t['pos'][j]+t['vel'][j]*horizon for j in range(3)]
        uncertainty=2.+age*(4.+math.hypot(*t['vel'][:2])*.4)
        # Extrapolation cannot claim motion through solid terrain/buildings.
        if self.arena.walk_segment(t['pos'],q,self.stats,max_drop=8.) is None:q=t['pos'][:]
        return q,max(0.,1-age/5.),uncertainty

    def remember(self,o,now,p):
        for actor in items(o,'mechs'):
            eid=actor.get('id');kind=actor.get('kind','mech')
            if not isinstance(eid,(int,float)) or eid==o.get('self',{}).get('id'):continue
            if kind=='mech' and not 0<=eid<16:continue
            memory=self.npcs if kind=='npc' else self.tracks
            ep,ev=vec(actor.get('pos')),vec(actor.get('vel'));old=memory.get(eid)
            ag=old['aggression'] if old else .5;evidence=old.get('evidence',0) if old else 0
            if old:
                dt=now-old['seen']
                if .01<dt<2:
                    error=dist(ep,[old['pos'][j]+old['vel'][j]*dt for j in range(3)])
                    self.metrics['prediction_samples']+=1;self.metrics['prediction_error_sum']+=error
                    approach=(p[0]-ep[0])*ev[0]+(p[1]-ep[1])*ev[1]
                    if dist(ep,p)<120 and approach>dist(ep,p)*2:
                        ag=ag*.92+.08;evidence+=1
                    else:ag=ag*.98+.5*.02
            memory[eid]={'pos':ep,'vel':ev,'seen':now,'hp':actor.get('hp'),
                         'max_hp':actor.get('max_hp'),'weapons':actor.get('weapons',[]),
                         'aggression':ag,'evidence':evidence,'damaged_us':old.get('damaged_us',-100.) if old else -100.}
        self.tracks={i:t for i,t in self.tracks.items() if 0<=now-t['seen']<30}
        self.npcs=dict(sorted(((i,t) for i,t in self.npcs.items() if 0<=now-t['seen']<8),
                             key=lambda it:it[1]['seen'],reverse=True)[:32])
        self.heat={k:(v[0]*math.exp(-max(0.,now-v[1])*.4),now) for k,v in self.heat.items()
                   if v[0]*math.exp(-max(0.,now-v[1])*.4)>.03}
        sound=self.config.get('sound',{})
        for s in items(o,'sounds'):
            if not isinstance(s.get('bearing'),(float,int)):continue
            near=sound.get('near',60.);mid=sound.get('mid',160.)
            band={'near':(8.,near),'mid':(near,mid),'far':(mid,sound.get('range',{}).get(s.get('kind'),320.))}.get(s.get('dist'),(near,mid))
            if band[1]<band[0]:continue
            weight=.35*math.exp(-clamp(s.get('age',0),0,10)*.4)
            sigma=math.radians(sound.get('bearing_noise_deg',7.))
            for fraction in (.25,.6,.9):
                radius=band[0]+(band[1]-band[0])*fraction
                for offset in (-sigma,0.,sigma):
                    a=s['bearing']+offset;k=(round((p[0]+math.cos(a)*radius)/30),round((p[1]+math.sin(a)*radius)/30))
                    self.heat[k]=(min(3.,self.heat.get(k,(0.,now))[0]+weight/3),now)
        for beam in items(o,'beams'):
            path=beam.get('path',[])
            for q in path[:8]:
                q=vec(q);k=(round(q[0]/30),round(q[1]/30))
                self.heat[k]=(min(3.,self.heat.get(k,(0.,now))[0]+.5),now)
        for ev in items(o,'events'):
            if ev.get('type')=='damaged':
                for memory in (self.tracks,self.npcs):
                    if ev.get('by') in memory:
                        t=memory[ev['by']];t['aggression']=min(1.,t['aggression']+.2)
                        t['damaged_us']=now;t['evidence']+=2
            if ev.get('type')=='kill':self.tracks.pop(ev.get('target'),None)
        if len(self.heat)>256:self.heat=dict(sorted(self.heat.items(),key=lambda kv:kv[1][0],reverse=True)[:256])
        self.predictions=[(i,*self.predict(t,now),t) for i,t in self.tracks.items() if now-t['seen']<5]

    def risk(self,q):
        ix,iy=round(q[0]/30),round(q[1]/30);value=0.
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                k=(ix+dx,iy+dy);v=self.heat.get(k)
                if v:value+=v[0]/(1+dist(q,[k[0]*30,k[1]*30])/20)
        for _,p,confidence,uncertainty,t in self.predictions:
            distance=max(0.,dist(q,p)-uncertainty)
            value+=confidence*(.45+t['aggression']*.5)/(1+(distance/45)**2)
        npc_cfg=self.config.get('npc',{})
        for t in self.npcs.values():
            age=self.last_now-t['seen'];reach=npc_cfg.get('aggro_range',45.)
            if self.last_now-t['damaged_us']<5:reach=npc_cfg.get('deaggro_range',90.)
            distance=dist(q,t['pos'])
            if distance<reach+12:value+=max(0.,1-age/8)*1.8*(1-distance/(reach+12))
        return value

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
        def score(x):
            e,q,_,confidence=x
            hp=e.get('hp');mh=e.get('max_hp')
            weakness=1-clamp(hp/max(1,mh or 1400),0,1) if isinstance(hp,(int,float)) else .25
            crowd=sum(1 for y in choices if y is not x and dist(y[1],q)<70)
            return confidence*(1+weakness*.35)/(1+dist(p,q)/90+crowd*.7)
        best=max(choices,key=score)
        held=next((x for x in choices if x[0].get('id')==self.target_id),None)
        if held and now<self.target_until and score(held)>=score(best)*.8:best=held
        if best[0].get('id')!=self.target_id:self.target_until=now+1.
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
        ranked=[]
        for q in options:
            if dist(q,center)>max(0.,radius-5) and radius>5:continue
            z=self.arena.surface(q[0],q[1],p[2]+self.stats.get('step_up',1.2))
            if not self.arena.in_bounds(q,self.stats['radius']) or self.arena.solid_at([*q,z],self.stats['radius'],self.stats['height']):continue
            score=dist(p,q)*(.15 if not urgent else 1.)+self.risk(q)*65
            if dist(q,center)>radius*.65:score+=15
            ranked.append((score,q))
        self.goal=min(ranked,key=lambda x:x[0])[1] if ranked else list(center)
        self.goal_until=now+2.
        return self.goal

    def incoming(self,o,p,vel):
        threats=[]
        for shot in items(o,'projectiles')[:128]:
            sp,sv=vec(shot.get('pos')),vec(shot.get('vel'))
            gravity=self.config.get('weapons',{}).get('mortar',{}).get('gravity',22.) if shot.get('kind')=='mortar' else 0.
            radius=self.config.get('weapons',{}).get('mortar',{}).get('splash_radius',7.) if gravity else 1.
            for i in range(9):
                t=i*.1
                q=[sp[j]+sv[j]*t for j in range(3)];q[2]-=.5*gravity*t*t
                own=[p[j]+vel[j]*min(t,.25) for j in range(3)]
                if dist(own,q)<self.stats['radius']+radius+3 and own[2]-radius<q[2]<own[2]+self.stats['height']+radius:
                    threats.append((q,sv));break
        return threats

    def decide(self,o):
        tick=int(o.get('tick',0) or 0);now=clamp(o.get('t',tick/20),0,1e7);self.last_now=now
        me=o.get('self') if isinstance(o.get('self'),dict) else {}
        p,vel=vec(me.get('pos')),vec(me.get('vel'))
        self.stats=dict(DEFAULTS)
        self.stats.update({k:v for k,v in self.config.get('mech',{}).items() if isinstance(v,(int,float)) and math.isfinite(v)})
        self.stats.update({k:v for k,v in me.get('stats',{}).items() if isinstance(v,(int,float)) and math.isfinite(v)})
        self.nav.configure(self.stats)
        self.remember(o,now,p)
        zone=o.get('zone') if isinstance(o.get('zone'),dict) else {}
        center=vec(zone.get('center'),2);nc=vec(zone.get('next_center',center),2)
        radius=clamp(zone.get('radius',500),0,1e6);nr=clamp(zone.get('next_radius',radius),0,1e6)
        soon=clamp(zone.get('shrink_start',1e9),0,1e9)-now
        travel=dist(p,nc)/max(1.,self.stats['walk_speed'])*1.35
        urgent=dist(p,center)>radius-12 or (soon<travel+5 and dist(p,nc)>nr-15) or me.get('in_zone') is False
        use_next=soon<max(30.,travel+10)
        safe_center,safe_radius=(nc,nr) if use_next else (center,radius)
        weak=clamp(me.get('hp',1400),0,1e6)/max(1.,clamp(me.get('max_hp',1400),1,1e6))<.42
        threats=self.incoming(o,p,vel);danger=self.risk(p)>.9 or bool(threats)
        target=self.candidates(o,now,p)
        goal=self.safe_goal(p,safe_center,safe_radius,now,urgent)
        self.mode='zone_move' if urgent else 'disengage' if weak or danger else 'reposition'
        # Visible resources only. Never invent NPC homes or random loot positions.
        if not urgent and not danger and not weak:
            loot=[]
            held=[w.get('kind') for w in me.get('weapons',[]) if isinstance(w,dict)]
            empty=any(w is None for w in me.get('weapons',[None,None])) or len(me.get('weapons',[]))<2
            resources=items(o,'cubes')+([x for x in items(o,'pickups') if empty and x.get('kind') not in held])
            resources += [x for x in items(o,'drops') if x.get('lands_in',1)>-1 and x.get('lands_in',1)<=0 and x.get('holder') in (None,me.get('id'))]
            for x in resources:
                q=vec(x.get('pos'))
                if dist(p,q)<45 and abs(q[2]-p[2])<self.stats['step_up']+1 and dist(q,safe_center)<safe_radius-12 and self.risk(q)<.6:
                    loot.append((dist(p,q),q))
            if loot:goal=min(loot,key=lambda x:x[0])[1];self.mode='gather'
        moved=self.last_pos is not None and dist(p,self.last_pos)>.2
        if self.last_pos is not None and not moved and math.hypot(*self.last_move)>.3 and math.hypot(*vel[:2])<1:self.stuck+=1
        else:self.stuck=max(0,self.stuck-1)
        self.last_pos=p
        if self.stuck==5:
            self.nav.invalidate();self.metrics['stuck_replans']+=1
        waypoint=self.nav.waypoint(p,goal,self.risk,now)
        desired=[waypoint[0]-p[0],waypoint[1]-p[1]]
        if math.hypot(*desired)<.1 and self.nav.status in ('no_route','no_anchor'):
            desired=[goal[0]-p[0],goal[1]-p[1]]
        if target and not urgent and not danger and not weak and not target[0].get('inferred') and dist(p,target[1])<110:
            q=target[1];away=[p[0]-q[0],p[1]-q[1]];n=max(1.,math.hypot(*away))
            desired=[-away[1]/n*.7+away[0]/n*.3,away[0]/n*.7+away[1]/n*.3];self.mode='engage'
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
        boost=bool((urgent or threats) and me.get('energy',100)>8)
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
        from combat import aim_and_fire
        aim,fire=aim_and_fire(self,o,p,target,weak or danger or urgent)
        action={'tick':tick,'move':[clamp(x,-1,1) for x in move],'boost':boost,'jump':jump,
                'aim':aim,'fire':fire,'reload':any(isinstance(w,dict) and w.get('kind')=='gun' and w.get('ammo',1)==0 and w.get('reload',0)==0 for w in me.get('weapons',[]))}
        if not weak and not danger and not urgent:
            held=[w.get('kind') for w in me.get('weapons',[]) if isinstance(w,dict)]
            if len(held)<2:
                for x in items(o,'pickups'):
                    q=vec(x.get('pos'))
                    if x.get('kind') not in held and dist(p,q)<self.config.get('loot',{}).get('pickup_radius',4.) and abs(p[2]-q[2])<4:
                        action['take']=x['id'];break
        offer=o.get('offer');choices=offer.get('choices',[]) if isinstance(offer,dict) else []
        if choices:
            ranks={'armor':10,'plating':9,'nanites':8,'servos':7,'reactor':6,'jets':5,'capacitor':4,'sensors':3}
            action['pick']=max(range(min(3,len(choices))),key=lambda i:ranks.get(choices[i].get('id'),1))
        return action


if __name__=='__main__':
    mf.run(Bot)
