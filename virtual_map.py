"""Shared virtual battlefield. Static facts, sensed facts and estimates stay distinct.

No unknown actors or spawn locations are invented. All memories, caches and
prediction branches have fixed caps. Geometry/physics remain planning estimates.
"""
import math
import copy


def vector(value,n=3):
    if not isinstance(value,(list,tuple)) or len(value)<n:return [0.]*n
    return [float(x) if isinstance(x,(int,float)) and math.isfinite(x) else 0. for x in value[:n]]


def objects(obs,name):
    return [x for x in obs.get(name,[]) if isinstance(x,dict)] if isinstance(obs.get(name),list) else []


def distance(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])


def _swept_hit(a,b,radius,half_height):
    """Closest horizontal point while the segment is inside the vertical slab."""
    lo,hi=0.,1.
    dz=b[2]-a[2]
    if abs(dz)<1e-9:
        if abs(a[2])>half_height:return None
    else:
        t0,t1=sorted(((-half_height-a[2])/dz,(half_height-a[2])/dz))
        lo,hi=max(lo,t0),min(hi,t1)
        if lo>hi:return None
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(lo,min(hi,-(a[0]*dx+a[1]*dy)/max(1e-12,dx*dx+dy*dy)))
    return t if (a[0]+t*dx)**2+(a[1]+t*dy)**2<=radius*radius else None


class VirtualMap:
    def __init__(self,arena,config=None):
        self.arena=arena;self.config=config or {};self.stats={}
        self.now=0.;self.tick=-1;self.position=[0.,0.,0.];self.velocity=[0.,0.,0.]
        self.hp=1400.;self.tracks={};self.npcs={};self.heat={};self.predictions=[]
        self.resources={};self.zone={};self.projectiles=[];self.hazards=[]
        self.revision=0;self._signature=None;self._risk_cache={};self._cover_cache={}
        self._rays_left=0;self._prediction_cache={}
        self.metrics={'prediction_samples':0,'prediction_error_sum':0.,'stuck_replans':0,
                      'map_updates':0,'projectile_threats':0,'cover_queries':0}

    def memory_seconds(self):
        return max(.1,float(self.config.get('vision',{}).get('memory_s',5.)))

    def predict(self,track,now):
        key=(id(track),now)
        if key in self._prediction_cache:return self._prediction_cache[key]
        age=max(0.,now-track['seen']);horizon=min(age,1.5)
        q=[track['pos'][j]+track['vel'][j]*horizon for j in range(3)]
        uncertainty=2.+age*(4.+math.hypot(*track['vel'][:2])*.4)
        if age and self.arena.walk_segment(track['pos'],q,self.stats,max_drop=8.) is None:q=track['pos'][:]
        result=(q,max(0.,1-age/self.memory_seconds()),uncertainty)
        self._prediction_cache[key]=result
        return result

    def hypotheses(self,track):
        """Weighted straight/left/right/stay possibilities, not exact positions."""
        age=max(0.,self.now-track['seen']);mean,confidence,uncertainty=self.predict(track,self.now)
        if age<.05:return [{'pos':mean,'weight':1.,'confidence':1.,'uncertainty':2.,'source':'sensed'}]
        speed=math.hypot(*track['vel'][:2]);travel=min(age,1.5)*speed
        heading=math.atan2(track['vel'][1],track['vel'][0])
        branches=[(mean,.5)]
        for angle in (-.7,.7):
            q=[track['pos'][0]+math.cos(heading+angle)*travel,
               track['pos'][1]+math.sin(heading+angle)*travel,track['pos'][2]]
            if self.arena.walk_segment(track['pos'],q,self.stats,max_drop=8.) is not None:branches.append((q,.15))
            else:branches.append((track['pos'][:],.15))
        branches.append((track['pos'][:],.2))
        return [{'pos':p,'weight':weight,'confidence':confidence,'uncertainty':uncertainty,'source':'inferred'}
                for p,weight in branches]

    def _heat_add(self,p,weight):
        if not self.arena.in_bounds(p):return
        key=(round(p[0]/30),round(p[1]/30))
        self.heat[key]=(min(3.,self.heat.get(key,(0.,self.now))[0]+weight),self.now)

    def update(self,obs,stats):
        policy=getattr(self,'policy',None)
        self.stats=stats
        self.now=float(obs.get('t',obs.get('tick',0)/20));self.tick=obs.get('tick',0)
        me=obs.get('self',{})
        self.position=vector(me.get('pos'));self.velocity=vector(me.get('vel'));self.hp=max(0.,me.get('hp',1400.))
        self.zone=dict(obs.get('zone') or {})
        self._risk_cache.clear();self._prediction_cache.clear();self._cover_cache.clear();self._rays_left=policy.cover_rays if policy else 4
        decay=policy.heat_decay if policy else .4
        self.heat={k:(v[0]*math.exp(-max(0.,self.now-v[1])*decay),self.now) for k,v in self.heat.items()
                   if v[0]*math.exp(-max(0.,self.now-v[1])*decay)>.03}
        sensed=set()
        for actor in objects(obs,'mechs'):
            eid=actor.get('id');kind=actor.get('kind','mech')
            if not isinstance(eid,(int,float)) or eid==me.get('id') or kind not in ('mech','npc'):continue
            if kind=='mech' and not 0<=eid<16:continue
            memory=self.npcs if kind=='npc' else self.tracks;sensed.add((kind,eid))
            old=memory.get(eid);p,v=vector(actor.get('pos')),vector(actor.get('vel'))
            ag=old['aggression'] if old else None;evidence=old.get('evidence',0) if old else 0
            if old:
                dt=self.now-old['seen']
                if .01<dt<2:
                    err=distance(p,[old['pos'][j]+old['vel'][j]*dt for j in range(3)])
                    self.metrics['prediction_samples']+=1;self.metrics['prediction_error_sum']+=err
            memory[eid]={'id':eid,'kind':kind,'pos':p,'vel':v,'seen':self.now,'hp':actor.get('hp'),
                         'max_hp':actor.get('max_hp'),'weapons':actor.get('weapons',[]),'aim':vector(actor.get('aim'),2),
                         'charging':bool(actor.get('charging')),'aggression':ag,'evidence':evidence,
                         'damaged_us':old.get('damaged_us',-100.) if old else -100.,'source':'sensed'}
        for kind,memory,ttl in [('mech',self.tracks,max(30.,self.memory_seconds())),('npc',self.npcs,8.)]:
            for eid in list(memory):
                if not 0<=self.now-memory[eid]['seen']<ttl:del memory[eid]
                else:memory[eid]['source']='sensed' if (kind,eid) in sensed else 'inferred'
        if len(self.npcs)>32:
            self.npcs=dict(sorted(self.npcs.items(),key=lambda x:x[1]['seen'],reverse=True)[:32])
        sound=self.config.get('sound',{})
        noise=math.radians(sound.get('bearing_noise_deg',7.)*stats.get('hearing',1.))
        for s in objects(obs,'sounds')[:64]:
            if not isinstance(s.get('bearing'),(int,float)):continue
            near,mid=sound.get('near',60.),sound.get('mid',160.)
            carry=sound.get('range',{}).get(s.get('kind'),320.)
            lo,hi={'near':(0.,min(near,carry)),'mid':(near,min(mid,carry)),'far':(mid,carry)}.get(s.get('dist'),(near,mid))
            if hi<lo:continue
            weight=.12*math.exp(-max(0.,s.get('age',0.))*.4)
            for fraction in (.25,.6,.9):
                r=lo+(hi-lo)*fraction
                for offset in (-noise,0.,noise):
                    a=s['bearing']+offset
                    self._heat_add([self.position[0]+math.cos(a)*r,self.position[1]+math.sin(a)*r],weight)
        for beam in objects(obs,'beams')[:32]:
            for q in beam.get('path',[])[:8]:self._heat_add(vector(q),.5)
        for ev in objects(obs,'events'):
            if ev.get('type')=='damaged':
                if isinstance(ev.get('bearing'),(int,float)) and ev.get('weapon')!='zone':
                    # Bearing-only damage adds a broad activity area, never an ID.
                    for offset in (-noise,0.,noise):
                        for reach in (30.,70.,130.):
                            angle=ev['bearing']+offset
                            self._heat_add([self.position[0]+math.cos(angle)*reach,self.position[1]+math.sin(angle)*reach],.12)
                for memory in (self.tracks,self.npcs):
                    if ev.get('by') in memory:
                        t=memory[ev['by']];t['aggression']=1.;t['damaged_us']=self.now;t['evidence']+=1
            if ev.get('type')=='kill':self.tracks.pop(ev.get('target'),None)
            if ev.get('type')=='took':self.resources.pop(('pickups',ev.get('id')),None)
        cap=policy.max_heat_cells if policy else 256
        if len(self.heat)>cap:self.heat=dict(sorted(self.heat.items(),key=lambda x:x[1][0],reverse=True)[:cap])
        if policy and len(self.tracks)>policy.max_tracks:
            self.tracks=dict(sorted(self.tracks.items(),key=lambda x:x[1]['seen'],reverse=True)[:policy.max_tracks])
        self.predictions=[]
        for eid,t in self.tracks.items():
            q,c,u=self.predict(t,self.now)
            if c>0:self.predictions.append((eid,q,c,u,t))
        self._branches={eid:self.hypotheses(t) for eid,t in self.tracks.items() if self.now-t['seen']<self.memory_seconds()}
        for name,ttl in [('crates',30.),('cubes',8.),('pickups',20.),('drops',0.)]:
            current=set()
            for item in objects(obs,name)[:128]:
                if not isinstance(item.get('id'),(int,float)):continue
                key=(name,item['id']);current.add(key)
                self.resources[key]={**item,'pos':vector(item.get('pos')),'category':name,'seen':self.now,'source':'sensed'}
            for key,item in list(self.resources.items()):
                if key[0]!=name:continue
                if key not in current:
                    if name=='drops' or self.now-item['seen']>ttl:del self.resources[key]
                    else:item['source']='inferred'
        if len(self.resources)>384:
            self.resources=dict(sorted(self.resources.items(),key=lambda x:x[1]['seen'],reverse=True)[:384])
        self.projectiles=objects(obs,'projectiles')[:128]
        self.hazards=self.projectile_threats(self.projectiles,self.position,self.velocity)
        self.metrics['projectile_threats']+=len(self.hazards);self.metrics['map_updates']+=1
        # Revisions track meaningful map changes, not tiny floating-point drift.
        signature=(tuple(sorted((t['kind'],eid,round(t['pos'][0]/12),round(t['pos'][1]/12),
                                 int(max(0.,1-(self.now-t['seen'])/self.memory_seconds())*4))
                                for memory in (self.tracks,self.npcs) for eid,t in memory.items())),
                   tuple(sorted(k for k,v in self.heat.items() if v[0]>.5)),
                   tuple(round(x/8) for x in vector(self.zone.get('center'),2)),
                   round(self.zone.get('radius',500.)/8))
        if signature!=self._signature:self.revision+=1;self._signature=signature

    def zone_at(self,seconds=0.):
        z=self.zone;c=vector(z.get('center'),2);n=vector(z.get('next_center',c),2)
        radius=max(0.,z.get('radius',500.));nr=max(0.,z.get('next_radius',radius))
        start=max(self.now,z.get('shrink_start',self.now+1e6));end=z.get('shrink_end',start+1.)
        f=max(0.,min(1.,(self.now+max(0.,seconds)-start)/max(.001,end-start)))
        return [c[j]+(n[j]-c[j])*f for j in range(2)],radius+(nr-radius)*f

    def _exposure(self,source,target):
        key=tuple(round(x,3) for x in source+target)
        if key in self._cover_cache:return self._cover_cache[key]
        if self._rays_left<=0:return 1. # Unknown clearance stays dangerous.
        self._rays_left-=1;self.metrics['cover_queries']+=1
        clear=self.arena.shot_clear(source,target,max_terrain_samples=12)
        # Solid cover reduces immediate fire exposure, never future flank risk to zero.
        result=1. if clear else .22
        self._cover_cache[key]=result
        return result

    def risk_details(self,q,eta=None):
        q=list(q)
        if len(q)<3:q.append(self.arena.surface(q[0],q[1],self.position[2]+self.stats.get('step_up',1.2)))
        eta=min(30.,distance(q,self.position)/max(1.,self.stats.get('walk_speed',11.7))) if eta is None else max(0.,eta)
        key=tuple(round(x,3) for x in q)+(round(eta,2),)
        if key in self._risk_cache:return self._risk_cache[key]
        values={'activity':0.,'enemies':0.,'npcs':0.,'zone':0.,'projectiles':0.}
        ix,iy=round(q[0]/30),round(q[1]/30)
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                cell=(ix+dx,iy+dy);v=self.heat.get(cell)
                if v:values['activity']+=v[0]/(1+distance(q,[cell[0]*30,cell[1]*30])/20)
        target=[q[0],q[1],q[2]+self.stats.get('height',9.)*.5]
        for eid,p,confidence,uncertainty,t in self.predictions:
            # Nearby possibilities carry most of the exposure calculation.
            for branch in self._branches[eid]:
                bp=branch['pos'];d=max(0.,distance(q,bp)-uncertainty)
                aggression=t.get('aggression');aggression=.5 if aggression is None else aggression
                behavior=t.get('behavior',{})
                strength=confidence*branch['weight']*(.45+aggression*.5)*behavior.get('threat_multiplier',1.)/(1+(d/45.)**2)
                # Tendencies only adjust uncertainty-weighted exposure modestly;
                # a quiet history never cancels an immediate projectile threat.
                strength*=1+behavior.get('confidence',0.)*(.15*(behavior.get('chase') or 0.)+.15*(behavior.get('ambush') or 0.))
                if strength<.025:continue
                source=[bp[0],bp[1],bp[2]+self.config.get('mech',{}).get('muzzle_height',7.)]
                values['enemies']+=strength*(self._exposure(source,target) if d<140. else 1.)
        npc=self.config.get('npc',{})
        for t in self.npcs.values():
            reach=npc.get('deaggro_range',90.) if self.now-t['damaged_us']<5 else npc.get('aggro_range',45.)
            d=distance(q,t['pos'])
            if d<reach+12:
                strength=max(0.,1-(self.now-t['seen'])/8)*1.8*(1-d/(reach+12))
                source=[*t['pos'][:2],t['pos'][2]+npc.get('height',3.5)*.7]
                values['npcs']+=strength*self._exposure(source,target)
        c,r=self.zone_at(eta)
        outside=distance(q,c)+self.stats.get('radius',2.5)-r
        if outside>0:values['zone']=min(12.,.6+outside/15+self.zone.get('dps',20.)/max(20.,self.hp*.08))
        for h in self.hazards:
            d=distance(q,h['pos']);reach=h['radius']+self.stats.get('radius',2.5)+5
            if d<reach:values['projectiles']+=2.*(1-d/reach)
        values['total']=sum(values.values())
        if len(self._risk_cache)<1024:self._risk_cache[key]=values
        return values

    def risk(self,q):
        return self.risk_details(q)['total']

    def projectile_threats(self,shots,p,velocity):
        """Swept collision over linear segments; fast bullets cannot skip a test."""
        result=[];height=self.stats.get('height',9.);body=self.stats.get('radius',2.5)
        for shot in shots[:128]:
            sp,sv=vector(shot.get('pos')),vector(shot.get('vel'));kind=shot.get('kind','gun')
            mortar=kind=='mortar';weapon=self.config.get('weapons',{}).get('mortar',{})
            gravity=weapon.get('gravity',22.) if mortar else 0.
            radius=weapon.get('splash_radius',7.) if mortar else self.config.get('projectile',{}).get('npc_radius' if kind=='npc' else 'gun_radius',.3)
            times=[i*.05 for i in range(17)] if mortar else [0.,.25,.8]
            for lo,hi in zip(times,times[1:]):
                endpoints=[];world=[]
                for t in (lo,hi):
                    q=[sp[j]+sv[j]*t for j in range(3)];q[2]-=.5*gravity*t*t
                    own=[p[j]+velocity[j]*min(t,.25) for j in range(3)];own[2]+=height*.5
                    world.append(q);endpoints.append([q[j]-own[j] for j in range(3)])
                f=_swept_hit(endpoints[0],endpoints[1],body+radius+2.,height*.5+radius)
                if f is not None:
                    q=[world[0][j]+(world[1][j]-world[0][j])*f for j in range(3)]
                    # Do not dodge a projectile that is stopped by solid cover first.
                    if not mortar and not self.arena.shot_clear(sp,q):break
                    result.append({'id':shot.get('id'),'kind':kind,'pos':q,'vel':sv,
                                   'time_to_closest':lo+(hi-lo)*f,'radius':radius,'source':'projected'})
                    break
        return result

    def snapshot(self,route=None,goal=None,mode=None):
        actors=[]
        for memory in (self.tracks,self.npcs):
            for eid,t in memory.items():
                entry={k:t[k] for k in ('id','kind','pos','vel','seen','source','aggression','evidence')}
                entry['confidence']=max(0.,1-(self.now-t['seen'])/(8. if t['kind']=='npc' else self.memory_seconds()))
                entry['hypotheses']=self._branches.get(eid,[])
                actors.append(entry)
        value={'tick':self.tick,'t':self.now,'revision':self.revision,'self':self.position,
                'actors':actors,'activity':[{'cell':list(k),'weight':v[0]} for k,v in self.heat.items()],
                'resources':list(self.resources.values()),'zone':self.zone,
                'forecast_zone':dict(zip(('center','radius'),self.zone_at(5.))),
                'projectiles':self.projectiles,'hazards':self.hazards,
                'route':route or [],'goal':goal,'mode':mode,'metrics':dict(self.metrics),
                'legend':{'sensed':'present in official observation','inferred':'memory/prediction, not current truth',
                          'projected':'trajectory estimate','sound':'area-only evidence with no invented actor ID'}}

        return copy.deepcopy(value)

    def debug_draw(self,route,goal,mode):
        caps=self.config.get('debug',{});lines=[];points=[]
        def line(a,b,color):
            if len(lines)<min(64,int(caps.get('max_lines',64))):lines.append({'a':a,'b':b,'color':color})
        p=self.position
        previous=p
        for q in route[:12]:
            end=list(q) if len(q)==3 else [*q,p[2]]
            line(previous,end,'#40c0ff');previous=end
        for t in self.tracks.values():
            for branch in self._branches.get(t['id'],[])[:3]:
                line(t['pos'],branch['pos'],'#ffb347' if branch['source']=='inferred' else '#ff5050')
        for h in self.hazards:line(p,h['pos'],'#ff00ff')
        if goal and len(points)<min(64,int(caps.get('max_points',64))):
            points.append({'at':list(goal) if len(goal)==3 else [*goal,p[2]],'color':'#40c0ff','size':6})
        for t in list(self.tracks.values())+list(self.npcs.values()):
            if len(points)<min(64,int(caps.get('max_points',64))):
                points.append({'at':t['pos'],'color':'#ff5050' if t['kind']=='mech' else '#ffd060','size':4})
        label=f"{mode} | map {self.revision} | {len(self.tracks)} known enemies"
        draw={'lines':lines,'points':points,'label':label[:int(caps.get('max_text_chars',80))]}
        # Byte cap includes structure. Drop drawings before dropping the short label.
        import json
        while len(json.dumps(draw,separators=(',',':')).encode())>int(caps.get('max_bytes',8192)) and (lines or points):
            if lines:lines.pop()
            elif points:points.pop()
        if len(json.dumps(draw,separators=(',',':')).encode())>int(caps.get('max_bytes',8192)):return {}
        return draw
