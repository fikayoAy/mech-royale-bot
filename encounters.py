"""Bounded encounter evidence and outcomes, limited to already-known mech IDs."""
from collections import deque
import math


class EncounterTracker:
    def __init__(self,policy,profiler):
        self.policy=policy;self.profiler=profiler;self.active={}
        self.recent=deque(maxlen=policy.max_encounters_kept)
        self.counts={'closed':0,'kills':0,'contacts_escaped':0,'eliminated_after_contact':0,'damage_dealt':0.,'damage_received':0.}

    def _open(self,eid,now):
        if eid not in self.active:
            self.active[eid]={'id':eid,'started':now,'last_contact':now,'damage_dealt':0.,'damage_received':0.,'outcome':None}
        return self.active[eid]

    def _close(self,eid,now,outcome):
        episode=self.active.pop(eid);episode.update(ended=now,outcome=outcome,duration=now-episode['started'])
        self.recent.append(episode);self.profiler.feedback(episode);self.counts['closed']+=1
        self.counts['kills']+=outcome=='kill';self.counts['contacts_escaped']+=outcome=='contact_escaped'
        self.counts['eliminated_after_contact']+=outcome=='self_eliminated_after_contact'

    def update(self,world,obs):
        now=world.now
        for eid,t in world.tracks.items():
            if t['source']=='sensed' and math.dist(t['pos'][:2],world.position[:2])<150:
                self._open(eid,now)['last_contact']=now
        for event in obs.get('events',[]):
            kind=event.get('type');eid=event.get('target') if kind in ('hit','kill') else event.get('by')
            if eid not in world.tracks and eid not in self.profiler.profiles:continue
            episode=self._open(eid,now);episode['last_contact']=now
            amount=max(0.,event.get('amount',0.))
            if kind=='hit':episode['damage_dealt']+=amount;self.counts['damage_dealt']+=amount
            if kind=='damaged':episode['damage_received']+=amount;self.counts['damage_received']+=amount
            if kind=='kill':self._close(eid,now,'kill')
        for eid,episode in list(self.active.items()):
            if now-episode['last_contact']>=self.policy.encounter_gap_s:
                self._close(eid,now,'contact_escaped' if world.hp>0 else 'ended')

    def end(self,now,message=None):
        outcome='self_eliminated_after_contact' if message and message.get('place',1)>1 else 'match_ended'
        for eid in list(self.active):self._close(eid,now,outcome)

    def summary(self):
        return {**self.counts,'active':len(self.active),'recent':list(self.recent),
                'escape_definition':'No sensed or attributed contact for the configured gap while still alive; not proof the enemy stopped chasing.',
                'loss_definition':'Non-winning end while contact remained active; does not identify who killed us.'}
