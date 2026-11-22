"""Pressure combat regressions: escape movement and self-defense can coexist."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot import Bot
from combat import aim_and_fire
from test_navigation import observation,actor,SCHEMA


def aligned_observation(distance=50.):
    o=observation();p=o['self']['pos']
    e=actor(1,[p[0]+distance,p[1],p[2]]);e['vel']=[0.,0.,0.]
    o['mechs']=[e];o['self']['aim']=[0.,math.atan2(-2.5,distance)]
    return o


class DefensiveCombatTests(unittest.TestCase):
    def test_fire_while_dodging_fast_bullet(self):
        o=aligned_observation();o['projectiles']=[{'id':7,'kind':'gun','pos':[12.6,0.,4.5],'vel':[-252.,0.,0.]}]
        b=Bot();a=b.decide(o)
        self.assertEqual(b.mode,'evade');self.assertTrue(a['fire'][0])
        self.assertTrue(a['jump']);self.assertTrue(a['boost'])
        self.assertGreater(abs(a['move'][1]),.5)
        self.assertEqual(SCHEMA.errors(a,'Action'),[])

    def test_gun_trigger_stays_held_during_cooldown(self):
        o=aligned_observation();o['self']['weapons'][0]['cooldown']=.14
        o['self']['hp']=250.
        a=Bot().decide(o)
        self.assertTrue(a['fire'][0])
        self.assertEqual(SCHEMA.errors(a,'Action'),[])

    def test_low_hp_retreat_can_return_fire(self):
        o=aligned_observation(20.);o['self']['hp']=250.;o['mechs'][0]['vel']=[-8.,0.,0.]
        b=Bot();a=b.decide(o)
        self.assertEqual(b.mode,'disengage');self.assertLess(a['move'][0],0)
        self.assertTrue(a['fire'][0]);self.assertNotIn('take',a)

    def test_outside_zone_moves_inward_while_firing(self):
        o=aligned_observation();o['self'].update(pos=[100.,0.,0.],in_zone=False)
        o['mechs'][0]['pos']=[150.,0.,0.]
        o['zone'].update(radius=60.,next_radius=30.,shrink_start=.2)
        b=Bot();a=b.decide(o)
        self.assertEqual(b.mode,'zone_move');self.assertLess(a['move'][0],0)
        self.assertTrue(a['boost']);self.assertTrue(a['fire'][0])

    def test_pressure_does_not_begin_slow_laser_charge(self):
        o=aligned_observation();o['self']['weapons'].append({'kind':'laser','cooldown':0.,'charge':0.,
                                                          'stats':{'range':280.,'charge':.75}})
        # Keep the two official weapon slots, replacing the initial null slot.
        o['self']['weapons']=[o['self']['weapons'][0],o['self']['weapons'][-1]]
        b=Bot();b.decide(o)
        e=o['mechs'][0];target=(e,e['pos'],e['vel'],1.)
        _,fire=aim_and_fire(b,o,[0,0,0],target,True)
        self.assertTrue(fire[0]);self.assertFalse(fire[1])

    def test_lightning_preserves_escape_energy(self):
        o=aligned_observation(30.);o['self']['energy']=10.
        o['self']['weapons'][1]={'kind':'lightning','cooldown':0.,'stats':{'range':45.,'cone_deg':30.,'energy':3.}}
        b=Bot();b.decide(o);e=o['mechs'][0]
        _,fire=aim_and_fire(b,o,[0,0,0],(e,e['pos'],e['vel'],1.),True)
        self.assertTrue(fire[0]);self.assertFalse(fire[1])

    def test_current_sensor_target_beats_own_inferred_target(self):
        b=Bot();o=aligned_observation(10.);b.decide(o)
        o=aligned_observation(80.);o.update(t=.1,tick=2);o['mechs'][0]['id']=2
        b.decide(o)
        self.assertEqual(b.target_id,2)

    def test_no_defensive_fire_at_only_inferred_target(self):
        b=Bot();o=aligned_observation();b.decide(o)
        o.update(t=.1,tick=2,mechs=[])
        self.assertFalse(any(b.decide(o)['fire']))

    def test_pressure_does_not_start_mortar_attack(self):
        o=aligned_observation(100.)
        o['self']['weapons'][1]={'kind':'mortar','cooldown':0.,'stats':{'speed':72.,'gravity':22.,'splash_radius':7.}}
        b=Bot();b.decide(o);e=o['mechs'][0]
        _,fire=aim_and_fire(b,o,[0,0,0],(e,e['pos'],e['vel'],1.),True)
        self.assertTrue(fire[0]);self.assertFalse(fire[1])


if __name__=='__main__':unittest.main()
