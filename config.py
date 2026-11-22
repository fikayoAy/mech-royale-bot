"""Policy knobs, independent of test strictness and live game balance values."""
from dataclasses import dataclass, asdict, fields
import json
import math
import os


@dataclass(frozen=True)
class Policy:
    name: str = 'survival'
    weak_enter: float = .42
    recovery_exit: float = .72
    danger_enter: float = .9
    danger_exit: float = .55
    engage_advantage: float = 1.15
    mode_hold_s: float = .8
    target_hold_s: float = 1.
    target_switch_ratio: float = .8
    goal_hold_s: float = 2.
    goal_risk_weight: float = 65.
    support_radius: float = 70.
    support_weight: float = .55
    behavior_half_life_s: float = 12.
    encounter_gap_s: float = 6.
    boost_start_fraction: float = .55
    boost_stop_fraction: float = .25
    escape_reserve: float = 8.
    pursuit_radius: float = 120.
    preferred_range: float = 70.
    reload_fraction: float = .4
    loot_radius: float = 45.
    scan_period_s: float = 4.
    navigation_budget_ms: float = .6
    decision_budget_ms: float = 35.
    heat_decay: float = .4
    cover_rays: int = 4
    max_tracks: int = 15
    max_heat_cells: int = 256
    max_encounters_kept: int = 16

    def export(self):
        return asdict(self)


def load_policy(overrides=None):
    name=os.environ.get('MECH_POLICY','survival')
    presets={'survival':{},'balanced':{'engage_advantage':1.,'preferred_range':60.},
             'cautious':{'engage_advantage':1.35,'danger_enter':.75,'preferred_range':85.}}
    if name not in presets:raise ValueError('Unknown MECH_POLICY')
    values={'name':name,**presets[name]}
    filename=os.environ.get('MECH_POLICY_FILE')
    if filename:
        with open(filename,encoding='utf-8') as source:values.update(json.load(source))
    values.update(overrides or {})
    allowed={f.name for f in fields(Policy)}
    if set(values)-allowed:raise ValueError('Unknown policy field')
    defaults=Policy()
    for key,value in values.items():
        if key=='name':continue
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError('Policy values must be finite and positive: '+key)
        if isinstance(getattr(defaults,key),int) and (not isinstance(value,int) or value>4096):
            raise ValueError('Invalid bounded policy count: '+key)
    result=Policy(**values)
    if not (result.weak_enter<result.recovery_exit<=1 and result.boost_stop_fraction<result.boost_start_fraction<=1
            and result.danger_exit<result.danger_enter and result.decision_budget_ms<45
            and result.max_tracks<=15 and result.cover_rays<=16 and result.max_heat_cells<=1024):
        raise ValueError('Invalid policy safety limits')
    return result
