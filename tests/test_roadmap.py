"""Roadmap regressions: observed learning, recovery, lifecycle and policy limits."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr
from bot import Bot
from config import load_policy
from decision_engine import DecisionEngine
from test_navigation import HELLO,observation,actor,SCHEMA,ROOT
from roadmap_scenarios import checks


class RoadmapTests(unittest.TestCase):
    def test_all_named_behavior_scenarios(self):
        for level in range(1,6):
            for result in checks(level):
                with self.subTest(level=level,scenario=result['scenario']):self.assertTrue(result['passed'])

    def test_policy_bounds_reject_invalid_values(self):
        for values in ({'max_tracks':16},{'cover_rays':100},{'decision_budget_ms':50},
                       {'weak_enter':.9,'recovery_exit':.5},{'heat_decay':float('nan')},{'unknown':1}):
            with self.subTest(values=values),self.assertRaises(ValueError):load_policy(values)

    def test_policy_is_independent_of_test_level(self):
        with patch.dict(os.environ,{'MECH_POLICY':'cautious'}):
            b=Bot();self.assertEqual(b.policy.name,'cautious');self.assertEqual(b.policy.engage_advantage,1.35)

    def test_direction_and_outcome_evidence(self):
        b=Bot();o=observation();o['self']['vel']=[-10.,0.,0.];e=actor(1,[30.,0.,0.]);e['vel']=[-15.,0.,0.];o['mechs']=[e]
        for i in range(12):o.update(t=i*.1,tick=i*2);b.decide(o)
        self.assertGreater(b.profiler.describe(1)['chase'],.9)
        e['vel']=[15.,0.,0.]
        for i in range(12,40):o.update(t=i*.1,tick=i*2);b.decide(o)
        self.assertGreater(b.profiler.describe(1)['retreat'],.5)
        o['events']=[{'type':'kill','target':1}];o.update(t=4.,tick=80);o['mechs']=[];b.decide(o)
        self.assertEqual(b.encounters.counts['kills'],1)
        self.assertEqual(b.profiler.describe(1)['wins'],1)

    def test_missing_damage_identity_never_creates_track(self):
        b=Bot();o=observation();o['events']=[{'type':'damaged','amount':45.,'weapon':'gun','bearing':1.,'by':None}]
        b.decide(o);self.assertFalse(b.tracks);self.assertTrue(b.heat);self.assertFalse(b.profiler.profiles)

    def test_defeat_after_contact_has_no_false_killer_claim(self):
        b=Bot();o=observation();o['mechs']=[actor()];b.decide(o)
        with redirect_stderr(io.StringIO()):summary=b.end({'type':'end','place':15,'kills':0})
        self.assertEqual(b.profiler.describe(1)['losses_after_contact'],1)
        self.assertEqual(summary['encounters']['eliminated_after_contact'],1)
        self.assertIn('does not identify',summary['encounters']['loss_definition'])

    def test_recovery_mode_holds_until_health_restored(self):
        b=Bot();o=observation();o['self']['hp']=250.;b.decide(o)
        o.update(t=2.,tick=40);o['self']['hp']=700.;b.decide(o);self.assertEqual(b.mode,'recover')
        o.update(t=4.,tick=80);o['self']['hp']=1200.;b.decide(o);self.assertFalse(b.survival.recovering)

    def test_upgrade_uses_actual_config_effects(self):
        b=Bot(copy.deepcopy(HELLO));o=observation();o['self']['hp']=250.
        b.config['upgrades']=[{'id':'new_healing','effects':[{'path':'mech.hp','mul':2.}]},
                              {'id':'armor','effects':[{'path':'mech.damage','mul':1.01}]}]
        o['offer']={'id':1,'expires':10.,'choices':[{'id':k,'name':k,'desc':''} for k in ('new_healing','armor')]}
        self.assertFalse(SCHEMA.errors(o,'Observation'));self.assertEqual(b.decide(o)['pick'],0)

    def test_safe_weapon_swap_and_charging_rejection(self):
        b=Bot();o=observation();o['self']['weapons'][1]={'kind':'mortar','cooldown':0.,'stats':{}}
        pickup=[{'id':4,'kind':'laser','pos':[0.,0.,0.]}]
        result=b.survival.pickup(o['self'],pickup,{})
        self.assertEqual(result,{'take':4,'drop':1});self.assertFalse(SCHEMA.errors({'tick':0,**result},'Action'))
        o['self']['weapons'][1]={'kind':'laser','charge':.5};pickup[0]['kind']='lightning'
        self.assertEqual(b.survival.pickup(o['self'],pickup,{}),{})

    def test_match_summary_score_and_zone_damage(self):
        b=Bot();o=observation();o['self']['in_zone']=False
        o['events']=[{'type':'damaged','amount':20.,'weapon':'zone','bearing':0.,'by':None}];b.decide(o)
        with redirect_stderr(io.StringIO()) as log:summary=b.end({'type':'end','place':7,'kills':0})
        self.assertEqual(summary['score'],9);self.assertEqual(summary['zone_damage'],20.)
        self.assertEqual(json.loads(log.getvalue())['schema'],'mech-match-summary/1')

    def test_telemetry_rejects_writes_outside_tmp(self):
        b=Bot()
        with patch.dict(os.environ,{'MECH_TELEMETRY_FILE':str(ROOT/'forbidden.json')}),self.assertRaises(ValueError):
            b.end({'type':'end','place':16,'kills':0})

    def test_protocol_handshake_action_end_summary(self):
        proc=subprocess.Popen([sys.executable,'-B','-u','bot.py'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            hello=copy.deepcopy(HELLO);hello['map']={}
            proc.stdin.write(json.dumps(hello)+'\n');proc.stdin.flush()
            self.assertEqual(json.loads(proc.stdout.readline())['type'],'ready')
            obs=observation(42);proc.stdin.write(json.dumps(obs)+'\n');proc.stdin.flush()
            action=json.loads(proc.stdout.readline());self.assertEqual(action['tick'],42);self.assertFalse(SCHEMA.errors(action,'Action'))
            proc.stdin.write(json.dumps({'type':'end','place':10,'kills':0})+'\n');proc.stdin.flush()
            out,err=proc.communicate(timeout=10)
            self.assertEqual(proc.returncode,0);self.assertEqual(out,'');self.assertEqual(json.loads(err)['score'],6)
        finally:
            if proc.poll() is None:proc.kill();proc.communicate()

    def test_protocol_uses_custom_fallback_after_error(self):
        program='''import mechfight as m
class Broken:
 def __init__(self,h):pass
 def act(self,o):raise ValueError("test failure")
 def fallback(self,o):return {"move":[0,1],"fire":[False,False]}
m.run(Broken)
'''
        proc=subprocess.Popen([sys.executable,'-B','-u','-c',program],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            proc.stdin.write(json.dumps(HELLO)+'\n');proc.stdin.flush();json.loads(proc.stdout.readline())
            proc.stdin.write(json.dumps(observation(4))+'\n');proc.stdin.flush()
            a=json.loads(proc.stdout.readline());self.assertEqual(a['move'],[0,1]);self.assertEqual(a['tick'],4)
            proc.stdin.write('{"type":"end","place":16,"kills":0}\n');proc.stdin.flush();proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:proc.kill();proc.communicate()


if __name__=='__main__':unittest.main()
