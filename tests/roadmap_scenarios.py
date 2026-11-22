"""Behavior probes. Scripted observations do not simulate match outcomes."""
import copy
import math
from bot import Bot
from arena_map import ArenaMap
from navigation import Navigator
from test_navigation import observation,actor,prism,SCHEMA,HELLO
from target_selector import assess


def checks(level):
    results=[]
    def record(name,condition):results.append({'scenario':name,'passed':bool(condition)})
    def action(bot,obs):
        errors=SCHEMA.errors(obs,'Observation')
        if errors:raise AssertionError(errors)
        result=bot.decide(obs)
        if SCHEMA.errors(result,'Action'):raise AssertionError(SCHEMA.errors(result,'Action'))
        return result
    if level==1:
        b=Bot();o=observation();a=action(b,o)
        record('quiet observation scans without firing',b.mode=='observe' and not any(a['fire']))
        record('fallback has current tick and no fire',b.fallback(o)['tick']==o['tick'] and not any(b.fallback(o)['fire']))
    if level==2:
        b=Bot();o=observation();e=actor()
        for field in ('hp','max_hp','weapons','charging','cubes'):e.pop(field,None)
        o['mechs']=[e];action(b,o)
        record('first sighting leaves aggression unknown',b.profiler.describe(1)['aggression'] is None)
        o=observation(20);o['sounds']=[{'kind':'gun','bearing':angle,'dist':'far','age':.1} for angle in (-math.pi,0.,math.pi)]
        a=action(b,o);record('conflicting sounds do not invent identities',set(b.tracks)=={1} and not any(a['fire']))
        early=b.predict(b.tracks[1],1.);late=b.predict(b.tracks[1],4.)
        record('lost sight increases uncertainty',late[1]<early[1] and late[2]>early[2])
    if level==3:
        b=Bot();o=observation();o['self']['hp']=250.;e=actor(1,[20.,0.,0.]);e['vel']=[-19.5,0.,0.];o['mechs']=[e]
        a=action(b,o);record('weak mech boosts away from pursuit',a['boost'] and a['move'][0]<0 and b.mode=='disengage')
        o['self']['energy']=20.;o.update(t=.1,tick=2);a=action(b,o)
        record('pursuit boost stops before empty tank',not a['boost'])
        o=observation(40);o['self']['hp']=700.;a=action(b,o)
        record('health recovery persists above weak threshold',b.mode=='recover' and not any(a['fire']))
        o=observation(80);o['self']['hp']=1200.;action(b,o)
        record('health recovery exits after healing',not b.survival.recovering)
        o=observation();o['self']['weapons'][0]['ammo']=2;a=action(Bot(),o)
        record('quiet low magazine reloads early',a['reload'])
        o['self'].update(pos=[100.,0.,0.],in_zone=False);o['pickups']=[{'id':40,'kind':'laser','pos':[100.,0.,0.]}]
        o['zone'].update(radius=50.,next_radius=40.);b=Bot();a=action(b,o)
        record('zone escape overrides pickup',b.mode=='zone_move' and 'take' not in a and a['move'][0]<0)
    if level==4:
        b=Bot();o=observation();e=actor(1,[40.,0.,0.]);e['hp']=1400.;e['vel']=[0.,0.,0.];o['mechs']=[e];action(b,o)
        isolated=assess(b,o,(e,e['pos'],e['vel'],1.))
        o['mechs'] += [actor(i,[40.+i,5.,0.]) for i in range(2,8)];o.update(t=.1,tick=2);action(b,o)
        crowded=assess(b,o,(e,e['pos'],e['vel'],1.))
        record('coordinated support lowers fight advantage',crowded['advantage']<isolated['advantage'] and b.mode!='engage')
        # A still opponent fires after being observed: stationary attack proxy.
        b=Bot();o=observation();o['mechs']=[e];action(b,o)
        for i in range(1,14):o.update(t=i*.1,tick=i*2);action(b,o)
        for i in range(14,19):
            o.update(t=i*.1,tick=i*2);o['events']=[{'type':'damaged','amount':45.,'weapon':'gun','bearing':0.,'by':1}];action(b,o)
        record('attributed stationary attack records ambush evidence',b.profiler.describe(1)['ambush']>.5)
        # Fresh adverse damage must outweigh a previously quiet observation history.
        record('new damage is evidence despite quiet history',b.profiler.describe(1)['aggression']>.8)
        o=observation(40);o['mechs']=[actor(1,[30.,0.,0.])];o['events']=[{'type':'hit','target':1,'amount':45.,'weapon':'gun'}];action(b,o)
        o=observation(200);action(b,o)
        record('lost contact records an encounter outcome',b.encounters.counts['contacts_escaped']>=1 and b.profiler.describe(1)['encounters']>=1)
        b=Bot();b.arena=ArenaMap({'prisms':[prism(4,-20,16,20)]});b.nav=Navigator(b.arena)
        o=observation();o['self']['pos']=[0.,0.,0.];o['zone'].update(center=[50.,0.],next_center=[50.,0.],radius=25.,next_radius=25.)
        for i in range(35):o.update(t=i*.1,tick=i*2);a=action(b,o)
        record('blocked escape replans repeatedly',b.metrics['stuck_replans']>=2)
        step=[o['self']['pos'][j]+a['move'][j]*2 for j in range(2)]
        record('stuck recovery still checks solid clearance',b.arena.walk_segment(o['self']['pos'],step,b.stats) is not None)
        b=Bot();o=observation();modes=[]
        for i in range(20):
            o.update(t=i*.1,tick=i*2);o['mechs']=[actor(1,[60.,0.,0.])] if i%2 else []
            action(b,o);modes.append(b.mode)
        record('small information changes do not flip mode every tick',sum(x!=y for x,y in zip(modes,modes[1:]))<10)
    if level==5:
        b=Bot();o=observation();action(b,o)
        for i in range(20):
            o.update(t=i*10.+1,tick=i*200+20);o['mechs']=[actor()];action(b,o)
            o.update(t=i*10.+8,tick=i*200+160,mechs=[]);action(b,o)
        record('encounter and latency histories stay bounded',len(b.encounters.recent)<=b.policy.max_encounters_kept and len(b.telemetry.latencies)<=1024)
        summary=b.telemetry.summary(b)
        record('telemetry includes measured outcomes',summary['actions']==41 and 'prediction_metrics' in summary and summary['encounters']['closed']>0)
    return results
