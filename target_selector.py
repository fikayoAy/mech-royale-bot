"""Bounded fight estimates from known health, weapons and nearby support."""
import math


def weapon_dps(config,kind,stats=None):
    rules=dict(config.get('weapons',{}).get(kind,{}));rules.update(stats or {})
    defaults={'gun':(45.,.24,230.),'mortar':(200.,2.,180.),'laser':(260.,2.4,280.),'lightning':(60.,.25,45.)}
    damage,cooldown,reach=defaults.get(kind,(0.,1.,0.))
    damage=rules.get('damage',damage);cooldown=max(.1,rules.get('cooldown',cooldown))
    if kind=='laser':cooldown+=rules.get('charge',.75)
    if kind=='gun':
        magazine=rules.get('magazine',rules.get('mag',12))
        cooldown+=rules.get('reload',2.4)/max(1,magazine)
    return damage/cooldown,rules.get('range',reach)


def assess(bot,obs,target):
    if not target:return {'advantage':0.,'support':0,'reason':'no known target'}
    actor,q,_,confidence=target;me=obs.get('self',{});p=me.get('pos',[0,0,0])
    distance=math.dist(p[:2],q[:2]);own=0.;enemy=0.
    for weapon in me.get('weapons',[])[:2]:
        if not isinstance(weapon,dict):continue
        dps,reach=weapon_dps(bot.config,weapon.get('kind'),weapon.get('stats'))
        if weapon.get('kind')=='gun' and weapon.get('ammo',0)==0:dps*=.25
        if weapon.get('kind')=='lightning' and me.get('energy',0)<15:dps=0.
        own+=dps*min(1.,reach/max(1.,distance))*(.55 if weapon.get('kind')=='mortar' else 1.)
    kinds=actor.get('weapons') or ['gun']
    for kind in kinds[:2]:
        if isinstance(kind,dict):kind=kind.get('kind','gun')
        dps,reach=weapon_dps(bot.config,kind)
        enemy+=dps*min(1.,reach/max(1.,distance))
    # Weapon interactions are known rules, never inferred hidden inventories.
    ownkinds=[w.get('kind') for w in me.get('weapons',[]) if isinstance(w,dict)]
    cookoff=1+bot.config.get('weapons',{}).get('laser',{}).get('cookoff',.6)
    if 'laser' in ownkinds and 'mortar' in kinds:own*=cookoff
    if 'laser' in kinds and 'mortar' in ownkinds:enemy*=cookoff
    if distance<45 and 'lightning' in ownkinds and 'laser' in kinds:enemy*=.65
    support=sum(1 for eid,t in bot.tracks.items() if eid!=actor.get('id') and
                bot.world.now-t['seen']<bot.world.memory_seconds() and math.dist(q[:2],t['pos'][:2])<bot.policy.support_radius)
    behavior=bot.profiler.describe(actor.get('id'),bot.last_now)
    enemy*=1+support*bot.policy.support_weight
    enemy*=behavior['threat_multiplier']
    hp=actor.get('hp');enemyhp=hp if isinstance(hp,(int,float)) else actor.get('max_hp') or 1400.
    own_ttk=max(1.,enemyhp)/max(1.,own);enemy_ttk=max(1.,me.get('hp',1400.))/max(1.,enemy)
    return {'advantage':enemy_ttk/max(.05,own_ttk)*confidence,'support':support,
            'own_ttk_s':own_ttk,'enemy_ttk_s':enemy_ttk,'reason':'known-state estimate; not a win probability'}


def score(bot,obs,choice):
    actor,q,_,confidence=choice
    estimate=assess(bot,obs,choice)
    distance=math.dist(obs['self']['pos'][:2],q[:2])
    behavior=bot.profiler.describe(actor.get('id'),bot.last_now)
    tendency=1+behavior['confidence']*(.1*(behavior.get('retreat') or 0.)+.05*(behavior.get('isolation') or 0.))
    return confidence*tendency*(.5+min(3.,estimate['advantage']))/(1+distance/90+estimate['support']*.7)
