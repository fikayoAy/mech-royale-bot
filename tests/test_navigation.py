import os
"""Map/navigation and survival regressions. These are not match simulations."""
from array import array
import copy
import gzip
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from arena_map import ArenaMap
from navigation import Navigator
from bot import Bot
from combat import aim_and_fire,intercept

KIT=Path(os.environ.get('MECHFIGHT_KIT',str(ROOT/'work/official-kit/mechfight-kit')))
with gzip.open(KIT/'check/stream.jsonl.gz','rt') as f:
    HELLO=json.loads(next(f))
    BASE=json.loads(next(f))
spec=importlib.util.spec_from_file_location('official_check',KIT/'check/check.py')
official=importlib.util.module_from_spec(spec);spec.loader.exec_module(official)
SCHEMA=official.Schema(str(KIT/'mechfight.schema.json'))


def observation(tick=0):
    o=copy.deepcopy(BASE)
    o.update(tick=tick,t=tick/20,alive=16,mechs=[],projectiles=[],sounds=[],beams=[],events=[],
             crates=[],cubes=[],pickups=[],drops=[],offer=None)
    o['self'].update(id=0,pos=[0.,0.,0.],vel=[0.,0.,0.],aim=[0.,0.],hp=1400.,max_hp=1400.,
                     energy=100.,max_energy=100.,grounded=True,in_zone=True,cubes=0,upgrades=[])
    o['zone'].update(center=[0.,0.],radius=500.,next_center=[20.,10.],next_radius=300.,shrink_start=100.,shrink_end=150.)
    return o


def actor(eid=1,p=None,kind='mech'):
    return {'id':eid,'kind':kind,'pos':p or [55.,5.,0.],'vel':[-1.,0.,0.],'aim':[math.pi,0.],
            'hp':500. if kind=='mech' else 350.,'max_hp':1400. if kind=='mech' else 350.,'weapons':['gun']}


def prism(x0,y0,x1,y1,base=-1.,top=20.,kind='building',holes=None):
    return {'kind':kind,'base':base,'top':top,'ring':[x0,y0,x1,y0,x1,y1,x0,y1],'holes':holes or []}


def bot_map(world):
    bot=Bot(copy.deepcopy(HELLO))
    bot.arena=ArenaMap(world);bot.nav=Navigator(bot.arena)
    return bot


class MapTests(unittest.TestCase):
    def test_official_full_map_loaded(self):
        arena=ArenaMap.load(KIT/'arena')
        self.assertIsNone(arena.load_error)
        world=arena.world
        self.assertEqual(len(arena.obstacles),len(world['prisms']))
        self.assertEqual(len(arena.trees),len(world['trees']['data'])//len(world['trees']['fields']))
        self.assertEqual(len(arena.heights),world['terrain']['nx']*world['terrain']['ny'])
        self.assertTrue(any(x['kind']=='stadium' for x in arena.obstacles))
        for name in ('water','cars','barriers','parking','blocks','stats'):self.assertIn(name,world)

    def test_bilinear_signed_centimeters_and_y_axis(self):
        a=ArenaMap({'terrain':{'minX':10.,'minY':20.,'nx':2,'ny':2,'step':1.,'scale':.01}},array('h',[-100,100,300,500]))
        self.assertEqual(a.ground(10.5,20.5),2.)
        self.assertEqual(a.ground(10,21),3.)
        self.assertEqual(a.ground(11,20),1.)

    def test_slope_uses_live_rule(self):
        a=ArenaMap({'terrain':{'minX':0.,'minY':0.,'nx':6,'ny':2,'step':1.,'scale':.01}},array('h',[0,200,400,600,800,1000]*2))
        self.assertIsNone(a.walk_segment([0,0,0],[4,0],{'max_slope_deg':50}))
        self.assertIsNotNone(a.walk_segment([0,0,0],[4,0],{'max_slope_deg':70}))

    def test_bridge_underpass_and_scaled_mech_clearance(self):
        a=ArenaMap({'prisms':[prism(0,-8,15,8,base=10,top=12,kind='bridge')]})
        self.assertIsNotNone(a.walk_segment([-4,0,0],[20,0],{'radius':1,'height':9}))
        self.assertIsNone(a.walk_segment([-4,0,0],[20,0],{'radius':1,'height':11}))
        self.assertIsNotNone(a.walk_segment([1,0,12],[12,0],{'radius':1}))
        self.assertTrue(a.shot_clear([-5,0,7],[20,0,7]))
        self.assertFalse(a.shot_clear([-5,0,11],[20,0,11]))

    def test_courtyard_holes_and_cylinder_radius(self):
        a=ArenaMap({'prisms':[prism(-20,-20,20,20,holes=[[-10,-10,10,-10,10,10,-10,10]])]})
        self.assertIsNone(a.solid_at([0,0,0],2.5,9))
        self.assertIsNotNone(a.solid_at([9,0,0],2.5,9))
        self.assertTrue(a.shot_clear([-5,0,5],[5,0,5]))
        self.assertFalse(a.shot_clear([-5,0,5],[30,0,5]))

    def test_roof_drop_and_map_boundary(self):
        a=ArenaMap({'bounds':{'minX':-30,'maxX':30,'minY':-30,'maxY':30},
                    'prisms':[prism(-10,-10,10,10,top=20)]})
        self.assertIsNotNone(a.walk_segment([0,0,20],[5,0],{'radius':1}))
        self.assertIsNone(a.walk_segment([0,0,20],[20,0],{'radius':1}))
        self.assertIsNone(a.walk_segment([28,0,0],[29,0],{'radius':2.5}))

    def test_trees_only_affect_vision_and_scenery_is_not_solid(self):
        a=ArenaMap({'trees':{'fields':['x','y','z','height','crownR','crownBase','trunkR'],
                            'data':[0,0,0,30,8,10,.7]},'water':[{}],'barriers':[{}]})
        self.assertIsNotNone(a.walk_segment([-10,0,0],[10,0]))
        self.assertTrue(a.shot_clear([-10,0,5],[10,0,5]))
        self.assertEqual(a.visibility([-10,0,5],[10,0,5]),0.)
        self.assertLess(a.visibility([-30,0,15],[30,0,15]),.25)
        self.assertEqual(a.visibility([-10,2,15],[10,2,15]),1.)

    def test_airborne_sweep_and_live_canopy_switch(self):
        a=ArenaMap({'prisms':[prism(5,-5,10,5,base=10,top=20)]})
        self.assertFalse(a.flight_segment([0,0,5],[15,0,5],{'radius':1,'height':9}))
        self.assertTrue(a.flight_segment([0,0,0],[15,0,0],{'radius':1,'height':9}))
        tree=ArenaMap({'trees':{'fields':['x','y','z','height','crownR','crownBase','trunkR'],
                               'data':[0,0,0,30,8,10,.7]}})
        self.assertEqual(tree.visibility([-30,2,15],[30,2,15],canopy=False),1.)

    def test_air_steering_respects_inertia_and_wall(self):
        a=ArenaMap({'prisms':[prism(5,-8,12,8,base=-1,top=30)]})
        nav=Navigator(a)
        stats={'radius':1.,'height':9.,'walk_speed':11.7,'air_accel':12.,'gravity':22.}
        # With large existing velocity toward a wall no steering choice can stop
        # before contact; the planner must not call that a clear dodge.
        move=nav.steer_air([0,0,10],[1,0],{'vel':[30,0,0],'energy':100},stats)
        self.assertEqual(move,[0.,0.])
        clear=Navigator(ArenaMap()).steer_air([0,0,10],[0,1],{'vel':[0,0,0],'energy':100},stats)
        self.assertAlmostEqual(clear[1],1.)

    def test_route_around_multiple_obstacles(self):
        a=ArenaMap({'bounds':{'minX':-15,'maxX':100,'minY':-45,'maxY':45},
                    'prisms':[prism(12,-20,24,8),prism(38,-8,50,25),prism(65,-25,75,5,kind='stadium')]})
        nav=Navigator(a);nav.configure({'radius':2.5,'height':9})
        start=[0.,0.,0.];goal=[90.,0.]
        for i in range(200):
            nav.waypoint(start,goal,now=i*.1,budget_ms=10)
            if nav.search is None and nav.route:break
        self.assertTrue(nav.route,nav.status)
        previous=start
        for q in nav.route:
            self.assertIsNotNone(a.walk_segment(previous,q,nav.stats),(previous,q))
            previous=q
        self.assertEqual(previous[:2],goal)
        self.assertGreater(len(nav.route),3)

    def test_dodge_and_strafe_cannot_bypass_clearance(self):
        a=ArenaMap({'prisms':[prism(4,-20,15,20)]})
        nav=Navigator(a);nav.configure({'radius':2.5})
        move=nav.steer([0,0,0],[1,0],[0,0,0],nav.stats)
        self.assertLess(move[0],.9)
        self.assertIsNotNone(a.walk_segment([0,0,0],[v*3 for v in move],nav.stats))

    def test_jet_energy_and_overhang(self):
        a=ArenaMap({'prisms':[prism(4,-6,20,6,top=8)]});nav=Navigator(a)
        bot=Bot();bot.decide(observation())
        self.assertIsNotNone(nav.jet_plan([0,0,0],[1,0],{'energy':100,'grounded':True},bot.stats))
        self.assertIsNone(nav.jet_plan([0,0,0],[1,0],{'energy':20,'grounded':True},bot.stats))
        a=ArenaMap({'prisms':[prism(4,-6,20,6,top=8),prism(-3,-3,3,3,base=10,top=12,kind='bridge')]})
        self.assertIsNone(Navigator(a).jet_plan([0,0,0],[1,0],{'energy':100,'grounded':True},bot.stats))


class PolicyTests(unittest.TestCase):
    def test_schema_valid_fixture_and_action(self):
        o=observation()
        self.assertEqual(SCHEMA.errors(o,'Observation'),[])
        bot=Bot();a=bot.decide(o)
        self.assertEqual(SCHEMA.errors(a,'Action'),[])
        self.assertEqual(a['tick'],o['tick'])

    def test_npc_danger_changes_movement_without_inventing_home(self):
        bot=Bot();o=observation();o['mechs']=[actor(104,[10,0,0],'npc')]
        bot.decide(o)
        self.assertIn(104,bot.npcs);self.assertNotIn(104,bot.tracks)
        self.assertGreater(bot.risk([10,0]),bot.risk([-100,0]))
        self.assertNotIn('home',bot.npcs[104])
        self.assertNotEqual(bot.mode,'engage')

    def test_prediction_stops_at_wall_and_uncertainty_grows(self):
        bot=bot_map({'prisms':[prism(10,-10,20,10)]});o=observation()
        e=actor(1,[0,0,0]);e['vel']=[20,0,0];o['mechs']=[e];bot.decide(o)
        a=bot.predict(bot.tracks[1],.1);b=bot.predict(bot.tracks[1],2.)
        self.assertGreater(b[2],a[2]);self.assertLess(b[1],a[1]);self.assertEqual(b[0],[0,0,0])

    def test_zone_overrides_loot_while_retreating(self):
        bot=Bot();o=observation()
        o['self'].update(pos=[100,0,0],hp=150,in_zone=False)
        o['zone'].update(radius=60,next_radius=30,shrink_start=.2)
        o['pickups']=[{'id':8001,'kind':'mortar','pos':[100,0,0]}]
        o['mechs']=[actor()]
        a=bot.decide(o)
        self.assertEqual(bot.mode,'zone_move');self.assertNotIn('take',a)
        self.assertTrue(a['boost'])
        self.assertLess(a['move'][0],0)

    def test_wall_blocks_firing_at_official_memory_actor(self):
        bot=bot_map({'prisms':[prism(10,-15,20,15)]})
        o=observation();o['mechs']=[actor(1,[50,0,0])]
        a=bot.decide(o);self.assertFalse(any(a['fire']))

    def test_gun_lead_is_applied_once(self):
        q=intercept([0,0,7],[100,0,7],[0,10,0],100)
        self.assertAlmostEqual(q[1],10.05038,places=4)

    def test_laser_charges_then_releases(self):
        bot=Bot();o=observation();bot.decide(o)
        w={'kind':'laser','cooldown':0,'charge':0,'stats':{'charge':.75,'range':280}}
        o['self']['weapons']=[None,w]
        q=[100.,0.,0.];o['self']['aim']=[0,math.atan2(-2.5,100)]
        target=(actor(1,q),q,[0,0,0],1.)
        aim,fire=aim_and_fire(bot,o,[0,0,0],target,False)
        self.assertTrue(fire[1])
        w['charge']=.75
        self.assertFalse(aim_and_fire(bot,o,[0,0,0],target,False)[1][1])

    def test_unknown_optional_fields_and_no_hidden_tracks(self):
        o=observation();o['self'].pop('energy');o['unknown']={'future':123}
        bot=Bot();a=bot.decide(o)
        self.assertEqual(SCHEMA.errors(a,'Action'),[])
        self.assertFalse(bot.tracks);self.assertFalse(bot.npcs);self.assertFalse(any(a['fire']))


if __name__=='__main__':
    unittest.main()
