"""Read-only official map: terrain, solid prisms/holes and vision-only trees.

Scenery stays available in world. Geometry queries are planning approximations;
the server remains authoritative for collision and physics.
"""
from array import array
from collections import defaultdict
import json
import math
from pathlib import Path
import sys


def _inside(p, ring):
    result = False
    for a, b in zip(ring, ring[1:]+ring[:1]):
        if (a[1]>p[1]) != (b[1]>p[1]) and p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:
            result = not result
    return result


def _distance2(p, a, b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(1e-12,dx*dx+dy*dy)))
    return (p[0]-a[0]-t*dx)**2+(p[1]-a[1]-t*dy)**2


def _ring(raw):
    return [(float(raw[i]),float(raw[i+1])) for i in range(0,len(raw)-1,2)]


class ArenaMap:
    CELL=32.

    def __init__(self,world=None,terrain=None):
        self.world=world if isinstance(world,dict) else {}
        self.bounds=self.world.get('bounds',{})
        self.terrain=self.world.get('terrain',{})
        self.rules=self.world.get('rules',{})
        self.heights=terrain
        self.obstacles=[];self.trees=[]
        self._solids=defaultdict(list);self._foliage=defaultdict(list)
        self.load_error=None;self._ground_cache={}
        for item in self.world.get('prisms',[]):
            if item.get('kind') not in ('building','bridge','stadium'):continue
            ring=_ring(item.get('ring',[]))
            if len(ring)<3:continue
            holes=[_ring(h) for h in item.get('holes',[]) if len(h)>=6]
            ob=dict(item,ring=ring,holes=holes,
                    edges=[(a,b) for loop in [ring]+holes for a,b in zip(loop,loop[1:]+loop[:1])],
                    minx=min(p[0] for p in ring),maxx=max(p[0] for p in ring),
                    miny=min(p[1] for p in ring),maxy=max(p[1] for p in ring))
            ob['edge_grid']=defaultdict(list)
            for a,b in ob['edges']:
                for i in range(math.floor(min(a[0],b[0])/8),math.floor(max(a[0],b[0])/8)+1):
                    for j in range(math.floor(min(a[1],b[1])/8),math.floor(max(a[1],b[1])/8)+1):
                        ob['edge_grid'][i,j].append((a,b))
            self.obstacles.append(ob)
            self._index(self._solids,ob,ob['minx'],ob['miny'],ob['maxx'],ob['maxy'])
        source=self.world.get('trees',{})
        fields,data=source.get('fields',[]),source.get('data',[])
        if fields:
            for i in range(0,len(data)-len(fields)+1,len(fields)):
                tree=dict(zip(fields,data[i:i+len(fields)]))
                self.trees.append(tree)
                r=max(tree.get('crownR',0),tree.get('trunkR',0))
                x,y=tree.get('crownX',tree['x']),tree.get('crownY',tree['y'])
                self._index(self._foliage,tree,min(x,tree['x'])-r,min(y,tree['y'])-r,
                            max(x,tree['x'])+r,max(y,tree['y'])+r)

    def _index(self,index,item,x0,y0,x1,y1):
        for i in range(math.floor(x0/self.CELL),math.floor(x1/self.CELL)+1):
            for j in range(math.floor(y0/self.CELL),math.floor(y1/self.CELL)+1):
                index[i,j].append(item)

    def _near(self,index,a,b=None,margin=0.):
        b=a if b is None else b
        seen=set()
        for i in range(math.floor((min(a[0],b[0])-margin)/self.CELL),math.floor((max(a[0],b[0])+margin)/self.CELL)+1):
            for j in range(math.floor((min(a[1],b[1])-margin)/self.CELL),math.floor((max(a[1],b[1])+margin)/self.CELL)+1):
                for item in index.get((i,j),()):
                    if id(item) not in seen:
                        seen.add(id(item));yield item

    @classmethod
    def load(cls,directory):
        try:
            root=Path(directory)/'v2'
            world=json.loads((root/'world.json').read_text(encoding='utf-8'))
            spec=world['terrain'];raw=(root/'terrain.i16').read_bytes()
            if len(raw)!=int(spec['nx'])*int(spec['ny'])*2:raise ValueError('terrain size mismatch')
            heights=array('h');heights.frombytes(raw)
            if sys.byteorder!='little':heights.byteswap()
            return cls(world,heights)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            result=cls();result.load_error=type(exc).__name__;return result

    def summary(self):
        return {'prisms':len(self.obstacles),'trees':len(self.trees),
                'terrain_samples':len(self.heights) if self.heights is not None else 0,
                'bounds':self.bounds,'load_error':self.load_error,
                'scenery_sections':[k for k in ('blocks','stadium','cars','parking','water','barriers','stats') if k in self.world]}

    def in_bounds(self,p,radius=0.):
        b=self.bounds
        return not b or (b['minX']+radius<=p[0]<=b['maxX']-radius and b['minY']+radius<=p[1]<=b['maxY']-radius)

    def ground(self,x,y):
        if self.heights is None:return 0.
        key=(x,y)
        cached=self._ground_cache.get(key)
        if cached is not None:return cached
        t=self.terrain
        u=max(0.,min(t['nx']-1.,(x-t['minX'])/t['step']))
        v=max(0.,min(t['ny']-1.,(y-t['minY'])/t['step']))
        i,j=min(t['nx']-2,int(u)),min(t['ny']-2,int(v));fx,fy=u-i,v-j
        k=j*t['nx']+i
        a,b,c,d=self.heights[k],self.heights[k+1],self.heights[k+t['nx']],self.heights[k+t['nx']+1]
        value=((a*(1-fx)+b*fx)*(1-fy)+(c*(1-fx)+d*fx)*fy)*t.get('scale',.01)
        if len(self._ground_cache)>32768:self._ground_cache.clear()
        self._ground_cache[key]=value
        return value

    def contains(self,ob,p):
        return _inside(p,ob['ring']) and not any(_inside(p,h) for h in ob['holes'])

    def overlaps(self,ob,p,radius):
        if p[0]+radius<ob['minx'] or p[0]-radius>ob['maxx'] or p[1]+radius<ob['miny'] or p[1]-radius>ob['maxy']:return False
        if self.contains(ob,p):return True
        for i in range(math.floor((p[0]-radius)/8),math.floor((p[0]+radius)/8)+1):
            for j in range(math.floor((p[1]-radius)/8),math.floor((p[1]+radius)/8)+1):
                for a,b in ob['edge_grid'].get((i,j),()):
                    if _distance2(p,a,b)<=radius*radius:return True
        return False

    def solid_at(self,p,radius=2.5,height=9.):
        for ob in self._near(self._solids,p,margin=radius):
            if ob['top']>p[2]+.03 and ob['base']<p[2]+height-.03 and self.overlaps(ob,p,radius):return ob
        return None

    def surface(self,x,y,ceiling):
        z=self.ground(x,y)
        for ob in self._near(self._solids,(x,y)):
            if z<ob['top']<=ceiling+.03 and self.contains(ob,(x,y)):z=ob['top']
        return z

    def walk_segment(self,start,goal,stats=None,max_drop=4.):
        """Cylinder clearance over surfaces. Live step/slope limits, guarded drops."""
        stats=stats or {}
        radius,height=stats.get('radius',2.5),stats.get('height',9.)
        step=stats.get('step_up',1.2)
        slope=math.tan(math.radians(stats.get('max_slope_deg',50.)))
        distance=math.hypot(goal[0]-start[0],goal[1]-start[1])
        count=max(1,math.ceil(distance))
        z=start[2];old_ground=self.ground(start[0],start[1])
        solids=list(self._near(self._solids,start,goal,margin=radius))
        for i in range(1,count+1):
            f=i/count;x,y=start[0]+(goal[0]-start[0])*f,start[1]+(goal[1]-start[1])*f
            if not self.in_bounds((x,y),radius):return None
            ground=self.ground(x,y);nz=ground
            for ob in solids:
                if nz<ob['top']<=z+step+.03 and self.contains(ob,(x,y)):nz=ob['top']
            if ground>old_ground and ground-old_ground>slope*max(distance/count,.01)+.02 and z<=old_ground+.2:return None
            if z-nz>max_drop:return None
            for ob in solids:
                if ob['top']>nz+.03 and ob['base']<nz+height-.03 and self.overlaps(ob,(x,y),radius):return None
            z,old_ground=nz,ground
        return [goal[0],goal[1],z]

    def flight_segment(self,start,goal,stats=None):
        """Sample airborne cylinder clearance without snapping onto ground."""
        stats=stats or {};radius=stats.get('radius',2.5);height=stats.get('height',9.)
        count=max(1,math.ceil(math.dist(start,goal)))
        for i in range(count+1):
            q=[start[j]+(goal[j]-start[j])*i/count for j in range(3)]
            if not self.in_bounds(q,radius) or q[2]<self.ground(q[0],q[1])-.05 or self.solid_at(q,radius,height):return False
        return True

    def _blocks(self,a,b,z):
        steps=max(1,math.ceil(math.dist(a[:2],b[:2])))
        for i in range(steps+1):
            t=i/steps
            hit=self.solid_at((a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,z),0.,9.)
            if hit:return hit
        return None

    def shot_clear(self,a,b,max_terrain_samples=None):
        """3D ray through solids and terrain. Trees never stop shots."""
        dx,dy,dz=b[0]-a[0],b[1]-a[1],b[2]-a[2]
        for ob in self._near(self._solids,a,b):
            if max(a[2],b[2])<ob['base'] or min(a[2],b[2])>ob['top']:continue
            ts=[0.,1.]
            if abs(dz)>1e-9:ts += [(ob['base']-a[2])/dz,(ob['top']-a[2])/dz]
            for c,d in ob['edges']:
                ex,ey=d[0]-c[0],d[1]-c[1];denom=dx*ey-dy*ex
                if abs(denom)>1e-9:
                    t=((c[0]-a[0])*ey-(c[1]-a[1])*ex)/denom
                    u=((c[0]-a[0])*dy-(c[1]-a[1])*dx)/denom
                    if 0<=t<=1 and 0<=u<=1:ts.append(t)
            ts=sorted(t for t in ts if 0<=t<=1)
            for lo,hi in zip(ts,ts[1:]):
                t=(lo+hi)/2
                if ob['base']-.001<=a[2]+dz*t<=ob['top']+.001 and self.contains(ob,(a[0]+dx*t,a[1]+dy*t)):return False
        steps=max(1,math.ceil(math.hypot(dx,dy)/1.5))
        if max_terrain_samples is not None:steps=min(steps,max_terrain_samples)
        for i in range(1,steps):
            t=i/steps
            if a[2]+dz*t<self.ground(a[0]+dx*t,a[1]+dy*t)+.05:return False
        return True

    def visibility(self,a,b,near_range=45.,canopy=True):
        """Tree transmission approximation, separate from shot clearance."""
        if not self.shot_clear(a,b):return 0.
        length=math.dist(a,b);near=math.dist(a[:2],b[:2])<=near_range;depth=0.
        for tree in self._near(self._foliage,a,b):
            for crown in (False,True):
                if crown and (near or not canopy):continue
                x=tree.get('crownX',tree['x']) if crown else tree['x']
                y=tree.get('crownY',tree['y']) if crown else tree['y']
                radius=tree.get('crownR' if crown else 'trunkR',0.)
                z0=tree['z']+(tree.get('crownBase',0.) if crown else 0.);z1=tree['z']+tree['height']
                dx,dy,dz=b[0]-a[0],b[1]-a[1],b[2]-a[2]
                qa=dx*dx+dy*dy;qb=2*((a[0]-x)*dx+(a[1]-y)*dy)
                qc=(a[0]-x)**2+(a[1]-y)**2-radius*radius;disc=qb*qb-4*qa*qc
                if qa<1e-9:
                    if qc>0:continue
                    lo,hi=0.,1.
                elif disc<0:continue
                else:
                    lo=max(0.,(-qb-math.sqrt(disc))/(2*qa));hi=min(1.,(-qb+math.sqrt(disc))/(2*qa))
                if abs(dz)>1e-9:
                    za,zb=sorted(((z0-a[2])/dz,(z1-a[2])/dz));lo=max(lo,za);hi=min(hi,zb)
                elif not z0<=a[2]<=z1:continue
                if hi>lo:
                    if not crown:return 0.
                    depth+=(hi-lo)*length*self.rules.get('canopyDensity',.35)
        return math.exp(-depth)

    def waypoint(self,start,goal):
        from navigation import Navigator
        nav=Navigator(self)
        return nav.waypoint(start,goal,budget_ms=12.)[:2]
