"""Report source identity and the map sections loaded by the bot (no match run)."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import os

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from arena_map import ArenaMap


def main():
    kit=Path(os.environ.get('MECHFIGHT_KIT',str(ROOT/'work/official-kit/mechfight-kit')))
    arena=ArenaMap.load(kit/'arena')
    report={'captured_utc':datetime.now(timezone.utc).isoformat(),'host_architecture':platform.machine(),
            'map':arena.summary(),'solid_kinds':{kind:sum(x['kind']==kind for x in arena.obstacles) for kind in ('building','bridge','stadium')},
            'prisms_with_holes':sum(bool(x['holes']) for x in arena.obstacles),
            'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                             [p.name for p in sorted(ROOT.glob('*.py'))]+['Dockerfile']},
            'kit_sha256':hashlib.sha256((ROOT/'work/mechfight-kit.tar.gz').read_bytes()).hexdigest() if (ROOT/'work/mechfight-kit.tar.gz').exists() else None,
            'virtual_map_layers':['sensed actors','inferred movement branches','NPCs','activity evidence','resources','zone forecasts','swept projectile threats','cover-aware route cost'],
            'notes':['All world.json sections retained in ArenaMap.world.',
                     'Only terrain and prisms block movement/shots. Trees affect vision.',
                     'Dynamic spawns, loot and NPC homes are not in the static map.',
                     'Routes, rays and jet checks approximate physics; the server is authoritative.']}
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
