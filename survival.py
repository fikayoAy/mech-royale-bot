"""Health recovery, pursuit escape and resource choices with energy reserves."""
import math


class Survival:
    def __init__(self,policy):
        self.policy=policy;self.recovering=False;self.boosting=False;self.last_combat=-100.

    def update(self,obs,world):
        me=obs.get('self',{});now=world.now
        if any(e.get('type') in ('hit','damaged') and e.get('weapon')!='zone' for e in obs.get('events',[])):
            self.last_combat=now
        fraction=me.get('hp',1400.)/max(1.,me.get('max_hp',1400.))
        if fraction<self.policy.weak_enter:self.recovering=True
        elif fraction>=self.policy.recovery_exit:self.recovering=False
        return fraction<self.policy.weak_enter

    def pursuit(self,world):
        threats=[]
        for eid,t in world.tracks.items():
            age=world.now-t['seen'];distance=math.dist(world.position[:2],t['pos'][:2])
            if age>1.5 or distance>self.policy.pursuit_radius:continue
            toward=[(world.position[j]-t['pos'][j])/max(1.,distance) for j in range(2)]
            approach=sum(t['vel'][j]*toward[j] for j in range(2))
            if approach>2 or world.now-t.get('damaged_us',-100.)<2:threats.append((eid,distance,approach))
        return threats

    def boost(self,me,emergency,pursued,escaping):
        energy=me.get('energy',0.);maximum=max(1.,me.get('max_energy',100.))
        if emergency:return energy>self.policy.escape_reserve
        if not (pursued and escaping):self.boosting=False;return False
        if self.boosting and energy<=maximum*self.policy.boost_stop_fraction:self.boosting=False
        elif not self.boosting and energy>=maximum*self.policy.boost_start_fraction:self.boosting=True
        return self.boosting

    def reload(self,me,quiet):
        for w in me.get('weapons',[]):
            if not isinstance(w,dict) or w.get('kind')!='gun' or w.get('reload',0)>0:continue
            magazine=w.get('stats',{}).get('magazine',w.get('stats',{}).get('mag',12))
            if w.get('ammo',0)==0 or (quiet and w.get('ammo',magazine)<=magazine*self.policy.reload_fraction):return True
        return False

    def pickup(self,me,pickups,config):
        weapons=me.get('weapons',[]);held=[w.get('kind') for w in weapons if isinstance(w,dict)]
        if any(isinstance(w,dict) and w.get('charge',0)>0 for w in weapons):return {}
        ranks={'gun':1,'mortar':2,'laser':3,'lightning':4 if self.recovering else 3}
        for item in pickups:
            q=item.get('pos',[0,0,0]);p=me.get('pos',[0,0,0]);kind=item.get('kind')
            if kind in held or math.dist(p[:2],q[:2])>=config.get('loot',{}).get('pickup_radius',4.) or abs(p[2]-q[2])>=4:continue
            if len(held)<2:return {'take':item['id']}
            swappable=[i for i,w in enumerate(weapons) if isinstance(w,dict) and w.get('kind')!='gun']
            if not swappable:continue
            slot=min(swappable,key=lambda i:ranks.get(weapons[i].get('kind'),0))
            if ranks.get(kind,0)>ranks.get(weapons[slot].get('kind'),0):
                return {'take':item['id'],'drop':slot}
        return {}

    def upgrade(self,choices,me,config):
        # Effects, rather than an assumed offer order, guide the choice.
        weights={'hp':5. if self.recovering else 3.,'armor':8.,'max_hp':5. if self.recovering else 3.,'regen':4.,'walk_speed':3.,'boost_speed':3.,
                 'energy_regen':2.5,'max_energy':2.,'damage':2.,'cooldown':-2.,'reload':-1.,'radius':-1.}
        fallback={'armor':10,'plating':9,'nanites':8,'servos':7,'reactor':6,'jets':5,'capacitor':4,'sensors':3}
        def value(choice):
            total=0.
            definition=next((x for x in config.get('upgrades',[]) if x.get('id')==choice.get('id')),{})
            for effect in definition.get('effects',[]):
                path=effect.get('path','');key=path.split('.')[-1] if isinstance(path,str) else ''
                weight=weights.get(key,0.)
                total+=weight*(effect.get('mul',1.)-1.)*10+weight*effect.get('add',0.)/max(1.,abs(me.get('stats',{}).get(key,1.)))
            return total+fallback.get(choice.get('id'),1)*.01
        return max(range(min(3,len(choices))),key=lambda i:value(choices[i]))
