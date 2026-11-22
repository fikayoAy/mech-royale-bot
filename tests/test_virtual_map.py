"""Virtual battlefield regressions: evidence, uncertainty, cover and live routes."""
import copy
import json
import math
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arena_map import ArenaMap
from bot import Bot,DEFAULTS
from navigation import Navigator
from virtual_map import VirtualMap
from test_navigation import observation,actor,prism,SCHEMA,HELLO


def world(obs=None,arena=None,config=None):
    m=VirtualMap(arena or ArenaMap(),config or {})
    m.update(obs or observation(),dict(DEFAULTS))
    return m


class VirtualMapTests(unittest.TestCase):
    def test_fast_bullet_between_old_samples(self):
        o=observation()
        o['projectiles']=[{'id':7,'kind':'gun','pos':[12.6,0.,4.5],'vel':[-252.,0.,0.]}]
        m=world(o)
        self.assertEqual(len(m.hazards),1)
        self.assertAlmostEqual(m.hazards[0]['time_to_closest'],.05)
        b=Bot();a=b.decide(o)
        self.assertEqual(b.mode,'evade')
        self.assertFalse(any(a['fire']))
        self.assertEqual(SCHEMA.errors(a,'Action'),[])

    def test_fast_bullet_behind_cover_and_high_bullet(self):
        a=ArenaMap({'prisms':[prism(4,-5,8,5)]})
        o=observation();o['projectiles']=[{'id':7,'kind':'gun','pos':[12.6,0.,4.5],'vel':[-252.,0.,0.]}]
        self.assertFalse(world(o,a).hazards)
        o['projectiles'][0]['pos'][2]=30
        self.assertFalse(world(o).hazards)

    def test_vertical_projectile_and_moving_self(self):
        o=observation();o['projectiles']=[{'id':7,'kind':'gun','pos':[0.,0.,25.],'vel':[0.,0.,-252.]}]
        self.assertTrue(world(o).hazards)
        o['self']['vel']=[0.,30.,0.]
        o['projectiles']=[{'id':8,'kind':'gun','pos':[12.6,1.5,4.5],'vel':[-252.,0.,0.]}]
        self.assertTrue(world(o).hazards)

    def test_sound_is_area_evidence_without_fake_actor(self):
        o=observation();o['alive']=16
        o['sounds']=[{'kind':'gun','bearing':0.,'dist':'mid','age':0.}]
        m=world(o);snapshot=m.snapshot()
        self.assertFalse(snapshot['actors']);self.assertTrue(snapshot['activity'])
        self.assertEqual(m.tracks,{})
        self.assertIn('no invented actor',snapshot['legend']['sound'])

    def test_confidence_and_multiple_map_checked_hypotheses(self):
        o=observation();e=actor(1,[0.,0.,0.]);e['vel']=[10.,0.,0.];o['mechs']=[e]
        m=world(o);o['mechs']=[];o.update(t=1.,tick=20);m.update(o,dict(DEFAULTS))
        h=m.snapshot()['actors'][0]
        self.assertEqual(h['source'],'inferred');self.assertEqual(len(h['hypotheses']),4)
        self.assertAlmostEqual(sum(x['weight'] for x in h['hypotheses']),1.)
        self.assertTrue(all(x['source']=='inferred' for x in h['hypotheses']))
        self.assertGreater(len({tuple(x['pos']) for x in h['hypotheses']}),2)
        earlier=h['confidence'];uncertainty=h['hypotheses'][0]['uncertainty']
        o.update(t=2.,tick=40);m.update(o,dict(DEFAULTS));h=m.snapshot()['actors'][0]
        self.assertLess(h['confidence'],earlier);self.assertGreater(h['hypotheses'][0]['uncertainty'],uncertainty)

    def test_prediction_branches_stay_out_of_wall(self):
        a=ArenaMap({'prisms':[prism(5,-20,15,20)]})
        o=observation();e=actor(1,[0.,0.,0.]);e['vel']=[10.,0.,0.];o['mechs']=[e]
        m=world(o,a);o.update(t=1.,tick=20,mechs=[]);m.update(o,dict(DEFAULTS))
        for h in m.snapshot()['actors'][0]['hypotheses']:
            self.assertIsNone(a.solid_at(h['pos'],2.5,9.))
            self.assertIsNotNone(a.walk_segment([0,0,0],h['pos'],DEFAULTS))

    def test_live_memory_setting_and_expiry(self):
        o=observation();o['mechs']=[actor()]
        m=world(o,config={'vision':{'memory_s':2.}})
        o.update(t=2.1,tick=42,mechs=[]);m.update(o,dict(DEFAULTS))
        self.assertFalse(m.predictions)
        o.update(t=40.,tick=800);m.update(o,dict(DEFAULTS))
        self.assertFalse(m.tracks)

    def test_cover_reduces_weapon_risk_without_erasing_threat(self):
        o=observation();o['mechs']=[actor(1,[50.,0.,0.])]
        a=ArenaMap({'prisms':[prism(20,-6,30,6)]})
        m=world(o,a)
        covered=m.risk_details([0,0,0],eta=0)['enemies']
        exposed=m.risk_details([0,30,0],eta=0)['enemies']
        self.assertGreater(covered,0);self.assertLess(covered,exposed)
        trees=ArenaMap({'trees':{'fields':['x','y','z','height','crownR','crownBase','trunkR'],
                                'data':[25,0,0,30,8,0,.7]}})
        leafy=world(o,trees).risk_details([0,0,0],eta=0)['enemies']
        clear=world(o).risk_details([0,0,0],eta=0)['enemies']
        self.assertAlmostEqual(leafy,clear)

    def test_exhausted_cover_budget_is_conservative(self):
        o=observation();o['mechs']=[actor(1,[50.,0.,0.])]
        m=world(o,ArenaMap({'prisms':[prism(20,-6,30,6)]}))
        m._rays_left=0
        unknown=m.risk_details([0,0,0],eta=0)['enemies']
        clear=world(o).risk_details([0,0,0],eta=0)['enemies']
        self.assertAlmostEqual(unknown,clear)

    def test_zone_forecast_and_arrival_risk(self):
        o=observation();o['zone'].update(center=[0.,0.],radius=100.,next_center=[20.,0.],
                                        next_radius=20.,shrink_start=10.,shrink_end=20.)
        m=world(o);center,radius=m.zone_at(15.)
        self.assertEqual(center,[10.,0.]);self.assertEqual(radius,60.)
        self.assertEqual(m.risk_details([80,0,0],eta=0)['zone'],0.)
        self.assertGreater(m.risk_details([80,0,0],eta=20)['zone'],0.)

    def test_resource_memory_is_labeled_and_expires(self):
        o=observation();o['pickups']=[{'id':8001,'kind':'laser','pos':[3.,0.,0.]}]
        o['drops']=[{'id':20000,'pos':[50.,0.,0.],'radius':8,'lands_in':0,'capture_s':4,'progress':0,'holder':None}]
        m=world(o)
        o.update(t=1.,tick=20,pickups=[],drops=[]);m.update(o,dict(DEFAULTS))
        self.assertEqual(len(m.resources),1)
        self.assertEqual(next(iter(m.resources.values()))['source'],'inferred')
        o.update(t=22.,tick=440);m.update(o,dict(DEFAULTS));self.assertFalse(m.resources)

    def test_memory_caps_under_large_inputs(self):
        o=observation()
        o['mechs']=[actor(i) for i in range(1,100)]
        o['mechs'] += [actor(100+i,kind='npc') for i in range(100)]
        o['pickups']=[{'id':8000+i,'kind':'laser','pos':[float(i),0.,0.]} for i in range(500)]
        o['sounds']=[{'kind':'gun','bearing':i*.03,'dist':'far','age':0.} for i in range(1000)]
        m=world(o)
        self.assertLessEqual(len(m.tracks),15);self.assertLessEqual(len(m.npcs),32)
        self.assertLessEqual(len(m.heat),256);self.assertLessEqual(len(m.resources),384)
        self.assertLessEqual(len(m.projectiles),128)

    def test_debug_draw_obeys_schema_and_caps(self):
        o=observation();o['mechs']=[actor(i) for i in range(1,16)]
        m=world(o,config={'debug':{'max_lines':3,'max_points':2,'max_text_chars':20,'max_bytes':512}})
        draw=m.debug_draw([[i,0,0] for i in range(20)],[100,0],'reposition')
        self.assertLessEqual(len(draw['lines']),3);self.assertLessEqual(len(draw['points']),2)
        self.assertLessEqual(len(json.dumps(draw,separators=(',',':')).encode()),512)
        self.assertEqual(SCHEMA.errors({'tick':0,'debug':draw},'Action'),[])

    def test_snapshot_does_not_change_when_memory_or_route_changes(self):
        o=observation();o['pickups']=[{'id':8001,'kind':'laser','pos':[3.,0.,0.]}]
        m=world(o);route=[[1.,0.,0.],[2.,0.,0.]]
        saved=m.snapshot(route)
        route.pop(0)
        o.update(t=1.,tick=20,pickups=[]);m.update(o,dict(DEFAULTS))
        self.assertEqual(len(saved['route']),2)
        self.assertEqual(saved['resources'][0]['source'],'sensed')

    def test_bot_uses_one_shared_model(self):
        b=Bot();o=observation();o['mechs']=[actor()]
        b.decide(o)
        self.assertIs(b.tracks,b.world.tracks);self.assertIs(b.npcs,b.world.npcs)
        self.assertEqual(b.risk([0,0,0]),b.world.risk([0,0,0]))
        self.assertEqual(b.world.metrics['map_updates'],1)


class LiveRouteTests(unittest.TestCase):
    def test_cached_route_replans_when_threat_changes(self):
        n=Navigator(ArenaMap());n.configure(DEFAULTS)
        n.route=[[12,0,0],[24,0,0],[36,0,0]]
        n.signature=(6,0,None);n._route_costs(lambda q:0.)
        n.checked_revision=1;n.checked_at=0.
        def danger(q):return 3. if 8<q[0]<28 and abs(q[1])<6 else 0.
        n.waypoint([0,0,0],[36,0],danger,now=1.,revision=2,budget_ms=10)
        self.assertGreater(n.replans,0)
        for _ in range(100):
            n.waypoint([0,0,0],[36,0],danger,now=1.,revision=2,budget_ms=10)
            if n.search is None and n.route:break
        self.assertTrue(n.route)
        self.assertTrue(any(abs(q[1])>=6 for q in n.route))

    def test_short_direct_route_does_not_ignore_danger(self):
        n=Navigator(ArenaMap(),cell=3);n.configure(DEFAULTS)
        def danger(q):return 5. if 4<q[0]<8 and abs(q[1])<3 else 0.
        q=n.waypoint([0,0,0],[12,0],danger,budget_ms=10)
        self.assertNotEqual(n.status,'direct')
        self.assertNotEqual(q,[12,0,0])

    def test_direct_path_respects_destination_height(self):
        n=Navigator(ArenaMap());n.configure(DEFAULTS)
        n.waypoint([0,0,0],[12,0,20],budget_ms=1)
        self.assertNotEqual(n.status,'direct')

    def test_finer_grid_retry_preserves_collision_checks(self):
        n=Navigator(ArenaMap());n.configure(DEFAULTS)
        root=(0,0,0)
        n.signature=(16,0,None)
        n.search={'open':[],'g':{root:0.},'parent':{},'closed':set(),'root':root,
                  'started':0.,'revision':None,'best':root,'best_h':100.}
        n.waypoint([0,0,0],[96,0],budget_ms=1)
        self.assertEqual(n.cell,3.);self.assertEqual(n.status,'refining')


if __name__=='__main__':unittest.main()
