"""Bounded incremental routing, local steering and energy-limited jet escapes."""
import heapq
import math
import time


class Navigator:
    def __init__(self,arena,cell=6.):
        self.arena=arena;self.cell=cell
        self.route=[];self.search=None;self.signature=None;self.edges={}
        self.stats={};self.stats_key=None;self.last_expansions=0;self.status='idle'

    def invalidate(self):
        self.route=[];self.search=None;self.signature=None

    def configure(self,stats):
        key=tuple(stats.get(k,d) for k,d in [('radius',2.5),('height',9.),('step_up',1.2),('max_slope_deg',50.)])
        self.stats=stats
        if key!=self.stats_key:
            self.edges.clear();self.invalidate();self.stats_key=key

    def _point(self,node):
        return [node[0]*self.cell,node[1]*self.cell,node[2]]

    def _node(self,p):
        return round(p[0]/self.cell),round(p[1]/self.cell),round(p[2],2)

    def _anchor(self,p):
        center=self._node(p);choices=[]
        for i in range(-2,3):
            for j in range(-2,3):
                q=[(center[0]+i)*self.cell,(center[1]+j)*self.cell]
                choices.append((math.dist(p[:2],q),q))
        for _,q in sorted(choices):
            end=self.arena.walk_segment(p,q,self.stats)
            if end:return self._node(end)
        return None

    def _neighbors(self,node):
        if node in self.edges:return self.edges[node]
        p=self._point(node);result=[]
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            q=[p[0]+dx*self.cell,p[1]+dy*self.cell]
            end=self.arena.walk_segment(p,q,self.stats)
            if end:
                result.append((self._node(end),math.dist(p[:2],end[:2])+abs(end[2]-p[2])*.5))
        if len(self.edges)>=12000:self.edges.clear()
        self.edges[node]=result
        return result

    def waypoint(self,start,goal,risk=None,now=0.,budget_ms=.8):
        risk=risk or (lambda p:0.)
        self.last_expansions=0
        deadline=time.perf_counter()+budget_ms/1000
        goal=list(goal)
        if math.dist(start[:2],goal[:2])<18:
            direct=self.arena.walk_segment(start,goal,self.stats)
            if direct:
                self.route=[];self.status='direct';return direct
        sig=(round(goal[0]/self.cell),round(goal[1]/self.cell))
        if sig!=self.signature:
            self.route=[];self.search=None;self.signature=sig
        while self.route and math.dist(start[:2],self.route[0][:2])<3.:self.route.pop(0)
        if self.route:
            if self.arena.walk_segment(start,self.route[0],self.stats):
                self.status='route';return self.route[0]
            self.route=[];self.search=None
        if self.search is None:
            anchor=self._anchor(start)
            if anchor is None:
                self.status='no_anchor';return list(start)
            self.search={'open':[(0.,anchor)],'g':{anchor:0.},'parent':{},'closed':set(),
                         'root':anchor,'started':now,'best':anchor,'best_h':float('inf')}
        s=self.search
        while s['open'] and self.last_expansions<96 and time.perf_counter()<deadline:
            _,node=heapq.heappop(s['open'])
            if node in s['closed']:continue
            s['closed'].add(node);self.last_expansions+=1
            p=self._point(node);h=math.dist(p[:2],goal[:2])
            if h<s['best_h']:s['best'],s['best_h']=node,h
            if h<self.cell*1.6 and self.arena.walk_segment(p,goal,self.stats):
                end=self.arena.walk_segment(p,goal,self.stats)
                route=[end]
                while node!=s['root']:
                    route.append(self._point(node));node=s['parent'][node]
                route.append(self._point(s['root']));route.reverse()
                self.route=route;self.search=None;self.status='route_found'
                while self.route and math.dist(start[:2],self.route[0][:2])<3.:self.route.pop(0)
                return self.route[0] if self.route else list(start)
            if len(s['closed'])>=12000:
                s['open'].clear();break
            for other,length in self._neighbors(node):
                if other in s['closed']:continue
                cost=s['g'][node]+length*(1+min(4.,max(0.,risk(self._point(other)))))
                if cost<s['g'].get(other,float('inf')):
                    s['g'][other]=cost;s['parent'][other]=node
                    heapq.heappush(s['open'],(cost+math.dist(self._point(other)[:2],goal[:2])*1.05,other))
        self.status='searching' if s['open'] else 'no_route'
        node=s['best'];prefix=[]
        while node!=s['root']:
            prefix.append(self._point(node));node=s['parent'][node]
        prefix.append(self._point(s['root']));prefix.reverse()
        for q in prefix[:4]:
            if math.dist(start[:2],q[:2])>2. and self.arena.walk_segment(start,q,self.stats):return q
        return list(start)

    def steer(self,p,desired,velocity,stats,risk=None,stuck=False):
        """Validate every tactical direction, including a short momentum horizon."""
        risk=risk or (lambda q:0.)
        n=math.hypot(*desired)
        if n<1e-6:return [0.,0.]
        yaw=math.atan2(desired[1],desired[0]);best=None
        accel=max(1.,stats.get('ground_accel',58.5))
        horizon=max(3.,min(9.,math.hypot(*velocity[:2])**2/(2*accel)+stats.get('walk_speed',11.7)*.25))
        for angle in (0.,.4,-.4,.8,-.8,1.3,-1.3,math.pi/2,-math.pi/2,math.pi):
            direction=[math.cos(yaw+angle),math.sin(yaw+angle)]
            q=[p[0]+direction[0]*horizon,p[1]+direction[1]*horizon]
            if not self.arena.walk_segment(p,q,stats):continue
            drift=[p[0]+velocity[0]*.12+direction[0]*horizon*.5,
                   p[1]+velocity[1]*.12+direction[1]*horizon*.5]
            if math.hypot(*velocity[:2])>1 and not self.arena.walk_segment(p,drift,stats):continue
            danger=risk(q)
            if angle==0. and danger<.35:return direction
            score=math.cos(angle)*2.5-min(5.,danger)
            if stuck:score-=max(0.,math.cos(angle))*.9
            if best is None or score>best[0]:best=(score,direction)
        return best[1] if best else [0.,0.]

    def steer_air(self,p,desired,me,stats,boost=False,risk=None):
        """Short 3D prediction using air acceleration, gravity, rise cap and landing."""
        risk=risk or (lambda q:0.)
        yaw=math.atan2(desired[1],desired[0]) if math.hypot(*desired)>.01 else 0.
        best=None
        for angle in (0.,.65,-.65,1.3,-1.3,math.pi):
            move=[math.cos(yaw+angle),math.sin(yaw+angle)] if math.hypot(*desired)>.01 else [0.,0.]
            q=list(p);velocity=list(me.get('vel',[0.,0.,0.]));clear=True
            fuel=me.get('energy',0.)
            for _ in range(5):
                dt=.05
                delta=[move[j]*stats.get('walk_speed',11.7)-velocity[j] for j in range(2)]
                norm=max(1e-9,math.hypot(*delta));factor=min(1.,stats.get('air_accel',12.)*dt/norm)
                for j in range(2):velocity[j]+=delta[j]*factor
                jet=boost and fuel>stats.get('jet_drain',15.)*dt
                velocity[2]+=((stats.get('jet_accel',34.) if jet else 0.)-stats.get('gravity',22.))*dt
                if jet:
                    velocity[2]=min(stats.get('max_rise_speed',10.),velocity[2]);fuel-=stats.get('jet_drain',15.)*dt
                next_q=[q[j]+velocity[j]*dt for j in range(3)]
                support=self.arena.surface(next_q[0],next_q[1],q[2]+.02)
                landed=velocity[2]<=0 and q[2]>=support-.03 and next_q[2]<=support
                if landed:next_q[2]=support
                if not self.arena.flight_segment(q,next_q,stats):clear=False;break
                q=next_q
                if landed:break
            if not clear:continue
            danger=risk(q);score=math.cos(angle)*2.-danger
            if angle==0. and danger<.35:return move
            if best is None or score>best[0]:best=score,move
        return best[1] if best else [0.,0.]

    def jet_plan(self,p,desired,me,stats):
        """A guarded vertical climb, using live acceleration and a fuel reserve."""
        n=math.hypot(*desired)
        if n<1e-6:return None
        direction=[v/n for v in desired]
        radius,height=stats.get('radius',2.5),stats.get('height',9.)
        q=[p[0]+direction[0]*(radius+3),p[1]+direction[1]*(radius+3)]
        hit=self.arena.solid_at([*q,p[2]],radius,height)
        if not hit:return None
        top=hit['top']+.15
        if top<=p[2] or hit['base']>p[2]+.1 or not self.arena.in_bounds(q,radius):return None
        fuel=max(0.,me.get('energy',0.)-20.)
        duration=fuel/max(1.,stats.get('jet_drain',15.))
        v=stats.get('jump_speed',11.) if me.get('grounded') else me.get('vel',[0,0,0])[2]
        rise=elapsed=0.;needed=top-p[2]
        while elapsed<min(duration,6.) and rise<needed:
            v=min(stats.get('max_rise_speed',10.),v+(stats.get('jet_accel',34.)-stats.get('gravity',22.))*.1)
            rise+=v*.1;elapsed+=.1
        if rise<needed:return None
        steps=max(2,math.ceil(needed))
        for i in range(1,steps+1):
            if self.arena.solid_at([p[0],p[1],p[2]+needed*i/steps],radius,height):return None
        if not self.arena.flight_segment([p[0],p[1],top],[*q,top],stats):return None
        return {'top':top,'goal':q,'needed_seconds':elapsed}
