"""Build an offline map viewer from recorded official observations. No game simulation."""
import argparse
import gzip
import json
import math
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot import Bot

HTML=r"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mech Royale virtual map</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101922;color:#e1eaf2;font:14px system-ui,sans-serif}
header{padding:16px 20px;border-bottom:1px solid #334352;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:20px;margin:0}p{margin:5px 0;color:#afc2d1}button{background:#273d4d;color:white;border:1px solid #658195;border-radius:5px;padding:8px 14px;cursor:pointer}
main{display:grid;grid-template-columns:minmax(0,1fr) 280px;height:calc(100vh - 88px)}#map{width:100%;height:100%;touch-action:none;outline:none}
aside{padding:16px;border-left:1px solid #334352;overflow:auto}label{display:block;margin:8px 0}input[type=range]{width:100%;accent-color:#40c0ff}
small{color:#afc2d1}#details{white-space:pre-wrap;line-height:1.6}.legend{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px}.key{padding:10px 0;border-top:1px solid #334352}
@media(max-width:700px){main{grid-template-columns:1fr;height:auto}#map{height:65vh}aside{border-left:0}header{padding:12px}}
</style>
<header><div><h1>Virtual battlefield</h1><p>Recorded observations. Bot actions did not change this world.</p></div><button id="fit">Fit map</button><button id="follow">Follow mech</button></header>
<main><canvas id="map" tabindex="0" aria-label="Interactive top-down battlefield map; drag to pan and scroll to zoom"></canvas>
<aside><b id="frameTitle">Observation</b><input id="frame" type="range" min="0" max="0" value="0" aria-label="Recorded observation"><button id="play">Play</button>
<div id="details"></div><div class="legend"><span><i class="dot" style="background:#40c0ff"></i>Own mech</span><span><i class="dot" style="background:#ff6666"></i>Enemy</span><span><i class="dot" style="background:#ffd060"></i>NPC</span></div>
<div class="key"><b>Layers</b><div id="layers"></div></div><div class="key"><small>Solid marker: sensed in the official observation.<br>Dashed marker: fading memory.<br>Amber fans: possible movement, never exact truth.<br>Red cells: estimated danger, including zone forecasts.<br>Blue line: planned route.<br>Terrain and collision checks are estimates; the server owns physics.</small></div></aside></main>
<script id="data" type="application/json">__DATA__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('data').textContent),canvas=document.getElementById('map'),ctx=canvas.getContext('2d');
const controls={}, names={terrain:'Terrain height',solids:'Buildings, stadium and bridges',trees:'Trees (sight only)',zone:'Current and next zone',danger:'Estimated danger',actors:'Known actors and predictions',loot:'Known resources',route:'Route and target',projectiles:'Projectiles and close threats'};
for(const [key,name] of Object.entries(names)){const label=document.createElement('label'),box=document.createElement('input');box.type='checkbox';box.checked=true;box.addEventListener('change',draw);label.append(box,document.createTextNode(' '+name));document.getElementById('layers').append(label);controls[key]=box;}
const slider=document.getElementById('frame');slider.max=data.frames.length-1;slider.value=data.initial;
let center=[0,0],scale=1,drag=null,playing=null;
const terrainCanvas=document.createElement('canvas');terrainCanvas.width=data.terrain.nx;terrainCanvas.height=data.terrain.ny;
const tc=terrainCanvas.getContext('2d'),pixels=tc.createImageData(data.terrain.nx,data.terrain.ny);
const lo=Math.min(...data.terrain.heights),hi=Math.max(...data.terrain.heights);
for(let i=0;i<data.terrain.heights.length;i++){const f=(data.terrain.heights[i]-lo)/Math.max(1,hi-lo);pixels.data.set([26+f*38,42+f*52,48+f*58,255],i*4);}tc.putImageData(pixels,0,0);
function size(){return [canvas.clientWidth,canvas.clientHeight];}
function fit(){const [w,h]=size(),b=data.bounds;center=[(b.minX+b.maxX)/2,(b.minY+b.maxY)/2];scale=Math.min(w/(b.maxX-b.minX+30),h/(b.maxY-b.minY+30));draw();}
function line(points,color,width=1,dashed=false){if(!points.length)return;ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=width/scale;ctx.setLineDash(dashed?[5/scale,4/scale]:[]);ctx.moveTo(points[0][0],points[0][1]);for(const p of points.slice(1))ctx.lineTo(p[0],p[1]);ctx.stroke();ctx.setLineDash([]);}
function circle(p,r,color,fill=false,dashed=false){ctx.beginPath();ctx.arc(p[0],p[1],Math.max(0,r),0,Math.PI*2);ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1.2/scale;ctx.setLineDash(dashed?[5/scale,4/scale]:[]);if(fill)ctx.fill();else ctx.stroke();ctx.setLineDash([]);}
function loop(raw){if(raw.length<4)return;ctx.moveTo(raw[0],raw[1]);for(let i=2;i<raw.length;i+=2)ctx.lineTo(raw[i],raw[i+1]);ctx.closePath();}
function draw(){
 const [w,h]=size(),dpr=Math.min(2,window.devicePixelRatio||1);if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=w*dpr;canvas.height=h*dpr;}
 ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle='#101922';ctx.fillRect(0,0,w,h);ctx.translate(w/2,h/2);ctx.scale(scale,-scale);ctx.translate(-center[0],-center[1]);
 const f=data.frames[Number(slider.value)],b=data.bounds;
 if(controls.terrain.checked){ctx.save();ctx.translate(data.terrain.minX,data.terrain.minY);ctx.drawImage(terrainCanvas,0,0,data.terrain.nx*data.terrain.step,data.terrain.ny*data.terrain.step);ctx.restore();}
 if(controls.danger.checked)for(const cell of f.danger){const a=Math.min(.65,cell.value*.18);ctx.fillStyle='rgba(255,65,60,'+a+')';ctx.fillRect(cell.x-6,cell.y-6,12,12);}
 if(controls.solids.checked)for(const ob of data.prisms){ctx.beginPath();loop(ob.ring);for(const h of ob.holes||[])loop(h);ctx.fillStyle=ob.kind==='bridge'?'#7691a3':ob.kind==='stadium'?'#928075':'#566a79';ctx.fill('evenodd');ctx.strokeStyle='#a6b9c4';ctx.lineWidth=.7/scale;ctx.stroke();}
 if(controls.trees.checked)for(const t of data.trees){circle(t,t[2],'rgba(65,133,92,.24)',true);circle(t,Math.min(.7,1/scale),'#72ab79',true);}
 line([[b.minX,b.minY],[b.maxX,b.minY],[b.maxX,b.maxY],[b.minX,b.maxY],[b.minX,b.minY]],'#a6b9c4',1,true);
 if(controls.zone.checked&&f.zone.center){circle(f.zone.center,f.zone.radius,'#85e5a3');circle(f.zone.next_center||f.zone.center,f.zone.next_radius||0,'#85e5a3',false,true);circle(f.forecast_zone.center,f.forecast_zone.radius,'#3ca766',false,true);}
 if(controls.loot.checked)for(const item of f.resources){ctx.globalAlpha=item.source==='inferred'?.4:1;circle(item.pos,3/scale,item.category==='drops'?'#cc99ff':'#9be9db',true);}ctx.globalAlpha=1;
 if(controls.route.checked){line([f.self,...f.route],'#40c0ff',2);if(f.goal)circle(f.goal,6/scale,'#40c0ff');}
 if(controls.actors.checked)for(const a of f.actors){
   const col=a.kind==='npc'?'#ffd060':'#ff6666';ctx.globalAlpha=Math.max(.15,a.confidence);
   for(const h of a.hypotheses||[]){if(h.source==='inferred'){line([a.pos,h.pos],'#ffb347',1,true);circle(h.pos,h.uncertainty,'rgba(255,179,71,.14)',true);}}
   circle(a.pos,5/scale,col,a.source==='sensed',a.source!=='sensed');ctx.globalAlpha=1;
 }
 if(controls.projectiles.checked){for(const p of f.projectiles)line([p.pos,[p.pos[0]+p.vel[0]*.15,p.pos[1]+p.vel[1]*.15]],'#f9c0ff',1);for(const p of f.hazards){circle(p.pos,(p.radius||1)+3,'#ff6bd6');line([f.self,p.pos],'#ff6bd6',1,true);}}
 circle(f.self,5/scale,'#40c0ff',true);
 ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle='#dbe9f4';ctx.font='13px system-ui';ctx.fillText('N ↑   E →  |  drag to pan · scroll to zoom',16,h-18);
 document.getElementById('frameTitle').textContent='Tick '+f.tick+' · '+f.t.toFixed(1)+' s';
 document.getElementById('details').textContent='Mode: '+f.mode+'\nMap revision: '+f.revision+'\nSensed actors: '+f.actors.filter(a=>a.source==='sensed').length+'\nRemembered actors: '+f.actors.filter(a=>a.source==='inferred').length+'\nClose projectile threats: '+f.hazards.length+'\nRoute replans: '+f.route_replans;
}
slider.addEventListener('input',draw);document.getElementById('fit').onclick=fit;document.getElementById('follow').onclick=()=>{center=data.frames[Number(slider.value)].self.slice(0,2);scale=Math.max(scale,3);draw();};
document.getElementById('play').onclick=()=>{if(playing){clearInterval(playing);playing=null;document.getElementById('play').textContent='Play';}else{document.getElementById('play').textContent='Pause';playing=setInterval(()=>{slider.value=(Number(slider.value)+1)%data.frames.length;draw();},250);}};
canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY,...center];canvas.setPointerCapture(e.pointerId);});canvas.addEventListener('pointermove',e=>{if(drag){center=[drag[2]-(e.clientX-drag[0])/scale,drag[3]+(e.clientY-drag[1])/scale];draw();}});canvas.addEventListener('pointerup',()=>drag=null);
canvas.addEventListener('wheel',e=>{e.preventDefault();scale=Math.max(.2,Math.min(25,scale*Math.exp(-e.deltaY*.001)));draw();},{passive:false});
window.addEventListener('resize',draw);fit();
window.mapViewer={data,draw,fit,controls};
</script></html>
"""


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'reports/virtual_map.html')
    parser.add_argument('--stride',type=int,default=10);parser.add_argument('--max-frames',type=int,default=120)
    parser.add_argument('--stream',type=Path)
    args=parser.parse_args()
    if args.stride<1 or not 1<=args.max_frames<=500:parser.error('stride >=1; max-frames 1..500')
    kit=Path(os.environ.get('MECHFIGHT_KIT',str(ROOT/'work/official-kit/mechfight-kit')))
    source=args.stream or kit/'check/stream.jsonl.gz'
    opener=gzip.open if source.suffix=='.gz' else open
    frames=[];bot=None;index=0
    with opener(source,'rt',encoding='utf-8') as stream:
        for line in stream:
            obs=json.loads(line)
            if obs.get('type')=='hello':
                obs['map']['dir']=str(kit/'arena');bot=Bot(obs)
            elif obs.get('type')=='obs' and bot:
                bot.decide(obs)
                if index%args.stride==0 and len(frames)<args.max_frames:
                    frame=bot.world.snapshot(bot.nav.route or [getattr(bot.nav,'last_waypoint',bot.last_pos)],getattr(bot,'current_goal',bot.goal),bot.mode);frame['route_replans']=bot.nav.replans
                    # Offline diagnostic sampling. Restore runtime counters/cache so
                    # the replay's next decision is not changed by visualization.
                    rays,cache,metrics=bot.world._rays_left,dict(bot.world._risk_cache),dict(bot.world.metrics)
                    bot.world._rays_left=96;bot.world._risk_cache.clear();danger=[]
                    for dx in range(-6,7):
                        for dy in range(-6,7):
                            q=[bot.last_pos[0]+dx*12,bot.last_pos[1]+dy*12]
                            value=bot.world.risk(q)
                            if value>.08:danger.append({'x':q[0],'y':q[1],'value':round(value,3)})
                    bot.world._rays_left=rays;bot.world._risk_cache=cache
                    bot.world.metrics.clear();bot.world.metrics.update(metrics)
                    frame['danger']=danger;frames.append(frame)
                index+=1
    if not bot or not frames or bot.arena.load_error:raise SystemExit('A valid map and observation stream are required.')
    world=bot.arena.world;b=bot.arena.bounds;step=4.
    nx=math.ceil((b['maxX']-b['minX'])/step);ny=math.ceil((b['maxY']-b['minY'])/step)
    terrain={'minX':b['minX'],'minY':b['minY'],'step':step,'nx':nx,'ny':ny,
             'heights':[round(bot.arena.ground(b['minX']+i*step,b['minY']+j*step),2) for j in range(ny) for i in range(nx)]}
    initial=max(range(len(frames)),key=lambda i:len(frames[i]['actors'])+len(frames[i]['hazards'])*2)
    data={'bounds':b,'prisms':world['prisms'],'trees':[[t['x'],t['y'],t.get('crownR',2.)] for t in bot.arena.trees],
          'terrain':terrain,'frames':frames,'initial':initial,'map_summary':bot.arena.summary()}
    encoded=json.dumps(data,separators=(',',':')).replace('<','\\u003c')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(HTML.replace('__DATA__',encoded),encoding='utf-8')
    print(json.dumps({'viewer':str(args.output),'frames':len(frames),'bytes':args.output.stat().st_size,'initial_frame':initial}))


if __name__=='__main__':main()
