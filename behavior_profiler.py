"""Recency-weighted observed tendencies. None means unknown, never a hidden fact."""
import math


class BehaviorProfiler:
    NAMES=('aggression','chase','retreat','ambush','isolation')

    def __init__(self,policy):
        self.policy=policy;self.profiles={}

    def update(self,world,obs):
        now=world.now;own=world.position;ownv=world.velocity
        for eid in list(self.profiles):
            if now-self.profiles[eid]['seen']>45:del self.profiles[eid]
        seen={eid:t for eid,t in world.tracks.items() if t['source']=='sensed'}
        attacks={}
        for event in obs.get('events',[]):
            if event.get('type')=='damaged' and event.get('by') in world.tracks:
                attacks[event['by']]=attacks.get(event['by'],0)+1
        for beam in obs.get('beams',[]):
            if beam.get('by') in world.tracks:attacks[beam['by']]=attacks.get(beam['by'],0)+1
        for eid,t in seen.items():
            p=self.profiles.get(eid)
            if p is None:
                p={'seen':now,'updated':now,'previous_pos':t['pos'][:],'stationary_s':0.,'samples':0,
                   'rates':{key:[0.,0.] for key in self.NAMES},'encounters':0,'wins':0,'losses_after_contact':0,'escapes':0,
                   'damage_dealt':0.,'damage_received':0.,'confidence':0.}
                self.profiles[eid]=p
            dt=max(0.,min(1.,now-p['updated']))
            decay=math.exp(-math.log(2)*max(0.,now-p['updated'])/self.policy.behavior_half_life_s)
            for pair in p['rates'].values():pair[0]*=decay;pair[1]*=decay
            d=max(1.,math.dist(t['pos'][:2],own[:2]));toward=[(own[j]-t['pos'][j])/d for j in range(2)]
            approach=sum(t['vel'][j]*toward[j] for j in range(2))
            fleeing=sum(ownv[j]*toward[j] for j in range(2))>2
            speed=math.hypot(*t['vel'][:2]);p['stationary_s']=p['stationary_s']+dt if speed<1 else 0.
            def evidence(key,positive,weight):
                if weight>0:
                    rate=p['rates'][key];rate[0]+=float(positive)*weight;rate[1]+=weight
            if dt>0:
                evidence('chase',approach>2 and fleeing,dt)
                evidence('retreat',approach<-2,dt)
                neighbors=sum(1 for other,x in seen.items() if other!=eid and math.dist(t['pos'][:2],x['pos'][:2])<self.policy.support_radius)
                evidence('isolation',neighbors==0,dt) # Only observed isolation.
                p['samples']+=1
            if eid in attacks:
                evidence('aggression',True,float(attacks[eid]))
                # A stationary attributed attack is an ambush proxy, not proof
                # of hidden intent or a previously unseen opponent's location.
                evidence('ambush',p['stationary_s']>=1.,1.)
            elif dt>0:evidence('aggression',False,dt*.15)
            p.update(seen=now,updated=now,previous_pos=t['pos'][:])
            p['confidence']=min(1.,sum(pair[1] for pair in p['rates'].values())/12.)
        for eid,t in world.tracks.items():
            profile=self.describe(eid,now)
            t['behavior']=profile;t['aggression']=profile['aggression'];t['evidence']=profile['samples']

    def describe(self,eid,now=None):
        p=self.profiles.get(eid)
        if p is None:return {**{name:None for name in self.NAMES},'confidence':0.,'samples':0,'status':'unknown','threat_multiplier':1.}
        age=max(0.,(p['updated'] if now is None else now)-p['seen'])
        confidence=p['confidence']*math.exp(-age/12.)
        rates={name:(pair[0]/pair[1] if pair[1]>=.5 else None) for name,pair in p['rates'].items()}
        trade=(p['damage_received']+50)/(p['damage_dealt']+50)
        learned=max(.8,min(1.35,trade**.15)) if p['encounters'] else 1.
        return {**rates,'confidence':confidence,'samples':p['samples'],'status':'observed' if confidence>=.2 else 'uncertain',
                'threat_multiplier':learned,'encounters':p['encounters'],'wins':p['wins'],
                'losses_after_contact':p['losses_after_contact'],'escapes':p['escapes']}

    def feedback(self,episode):
        p=self.profiles.get(episode['id'])
        if p is None:return
        p['encounters']+=1;p['wins']+=episode['outcome']=='kill';p['escapes']+=episode['outcome']=='contact_escaped'
        p['losses_after_contact']+=episode['outcome']=='self_eliminated_after_contact'
        p['damage_dealt']+=episode['damage_dealt'];p['damage_received']+=episode['damage_received']
