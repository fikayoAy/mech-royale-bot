"""Mode entry/exit rules. Emergencies override the short normal mode hold."""


class DecisionEngine:
    def __init__(self,policy):
        self.policy=policy;self.mode='observe';self.until=0.;self.transitions=0

    def choose(self,now,urgent,hazard,weak,recovering,risk,pursued,fight,has_target,has_loot=False):
        if urgent:wanted='zone_move'
        elif hazard:wanted='evade'
        elif weak or (pursued and fight<self.policy.engage_advantage):wanted='disengage'
        elif recovering:wanted='recover'
        elif risk>self.policy.danger_enter or (self.mode=='disengage' and risk>self.policy.danger_exit):wanted='disengage'
        elif has_target and fight>=self.policy.engage_advantage:wanted='engage'
        elif has_loot:wanted='gather'
        elif has_target:wanted='reposition'
        else:wanted='observe'
        emergency=wanted in ('zone_move','evade','disengage','recover')
        valid=(self.mode!='engage' or has_target and fight>=self.policy.engage_advantage*.8) and (self.mode!='gather' or has_loot)
        if wanted!=self.mode and (emergency or now>=self.until or not valid):
            self.mode=wanted;self.until=now+self.policy.mode_hold_s;self.transitions+=1
        return self.mode
