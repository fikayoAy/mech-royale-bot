"""Weapon-specific aiming and 3D obstruction checks; no shots at guessed tracks."""
import math


def _angle(a,b):
    return (a-b+math.pi)%math.tau-math.pi


def intercept(origin,target,velocity,speed):
    r=[target[i]-origin[i] for i in range(3)]
    aa=sum(x*x for x in velocity)-speed*speed
    bb=2*sum(r[i]*velocity[i] for i in range(3));cc=sum(x*x for x in r)
    roots=[]
    if abs(aa)<1e-8:
        if abs(bb)>1e-8:roots=[-cc/bb]
    else:
        disc=bb*bb-4*aa*cc
        if disc>=0:roots=[(-bb-math.sqrt(disc))/(2*aa),(-bb+math.sqrt(disc))/(2*aa)]
    times=[t for t in roots if 0<t<4.]
    t=min(times) if times else 0.
    return [target[i]+velocity[i]*t for i in range(3)]


def mortar(origin,target,velocity,speed,gravity):
    q=target[:]
    for _ in range(3):
        d=math.dist(origin[:2],q[:2]);dz=q[2]-origin[2]
        if d<1:return None
        disc=speed**4-gravity*(gravity*d*d+2*dz*speed*speed)
        if disc<0:return None
        pitch=math.atan((speed*speed-math.sqrt(disc))/(gravity*d))
        t=d/max(.01,speed*math.cos(pitch))
        q=[target[i]+velocity[i]*t for i in range(3)]
    return q,pitch,t


def aim_and_fire(bot,o,p,target,unsafe):
    me=o.get('self',{});stats=bot.stats
    current=me.get('aim',[0.,0.]);aim=list(current);fire=[False,False]
    if not target:
        # Quiet scan toward travel; no guessed targets from the global alive count.
        if math.hypot(*bot.last_move)>.1:aim=[math.atan2(bot.last_move[1],bot.last_move[0]),0.]
        return aim,fire
    actor,q,velocity,confidence=target
    cubes=actor.get('cubes',0);scale=1+bot.config.get('cubes',{}).get('size_per_cube',.05)*cubes
    center=[q[0],q[1],q[2]+bot.config.get('mech',{}).get('height',9.)*scale*.5]
    origin=[p[0],p[1],p[2]+stats['muzzle_height']]
    ws=me.get('weapons',[]);options=[]
    for slot,w in enumerate(ws[:2]):
        if not isinstance(w,dict) or w.get('cooldown',0)>.05:continue
        kind=w.get('kind');st=dict(bot.config.get('weapons',{}).get(kind,{}));st.update(w.get('stats',{}))
        distance=math.dist(origin,center);pitch=None;flight=None
        if kind=='gun':
            if w.get('ammo',0)<=0 or w.get('reload',0)>0 or distance>st.get('range',230.):continue
            point=intercept(origin,center,velocity,st.get('speed',252.));priority=3
        elif kind=='lightning':
            if distance>st.get('range',45.) or me.get('energy',0)<st.get('energy',3.)+12:continue
            point=center;priority=4
        elif kind=='laser':
            if distance>st.get('range',280.):continue
            point=center;priority=2
        elif kind=='mortar':
            # No guess at a blind target; avoid self splash and unusable arcs.
            if distance<st.get('splash_radius',7.)*3:continue
            solution=mortar([p[0],p[1],p[2]+stats['height']+.5],center,velocity,st.get('speed',72.),st.get('gravity',22.))
            if not solution:continue
            point,pitch,flight=solution;priority=1
        else:continue
        yaw=math.atan2(point[1]-origin[1],point[0]-origin[0])
        if pitch is None:pitch=math.atan2(point[2]-origin[2],math.dist(origin[:2],point[:2]))
        if not stats['min_pitch']<=pitch<=stats['max_pitch']:continue
        options.append((priority,slot,w,st,point,yaw,pitch,flight))
    if options:
        _,_,_,_,_,yaw,pitch,_=max(options,key=lambda x:x[0]);aim=[yaw,pitch]
    else:aim=[math.atan2(center[1]-origin[1],center[0]-origin[0]),math.atan2(center[2]-origin[2],max(1.,math.dist(origin[:2],center[:2])))]
    aim=[max(-math.pi,min(math.pi,aim[0])),max(stats['min_pitch'],min(stats['max_pitch'],aim[1]))]
    if unsafe or actor.get('inferred') or confidence<.99:return aim,fire
    # An actor can remain in official sensor memory behind a wall or canopy.
    eye=[p[0],p[1],p[2]+stats['eye_height']]
    if bot.arena.visibility(eye,center,bot.config.get('vision',{}).get('near_range',45.)+stats.get('near_range_bonus',0.),bot.config.get('vision',{}).get('canopy_blocks',True))<bot.arena.rules.get('canopyBlockT',.25):return aim,fire
    for _,slot,w,st,point,yaw,pitch,flight in options:
        distance=max(1.,math.dist(origin,point))
        tolerance=max(.015,min(.12,math.atan2(bot.config.get('mech',{}).get('radius',2.5)*scale*.8,distance)))
        if w['kind']=='lightning':tolerance=math.radians(st.get('cone_deg',30.))/2
        aligned=abs(_angle(yaw,current[0]))<tolerance and abs(pitch-current[1])<max(tolerance,.04)
        if w['kind']=='mortar':
            if not aligned:continue
            start=[p[0],p[1],p[2]+stats['height']+.5];previous=start
            clear=True;speed=st.get('speed',72.);gravity=st.get('gravity',22.)
            for i in range(1,17):
                t=flight*i/16
                end=[start[0]+math.cos(yaw)*math.cos(pitch)*speed*t,start[1]+math.sin(yaw)*math.cos(pitch)*speed*t,
                     start[2]+math.sin(pitch)*speed*t-.5*gravity*t*t]
                if not bot.arena.shot_clear(previous,end):clear=False;break
                previous=end
            fire[slot]=clear
        elif bot.arena.shot_clear(origin,point):
            if w['kind']=='laser':
                # True charges; false releases. The old policy never began a charge.
                charge=w.get('charge',0.)
                fire[slot]=aligned and charge<st.get('charge',.75)
            elif aligned:fire[slot]=True
    return aim,fire
