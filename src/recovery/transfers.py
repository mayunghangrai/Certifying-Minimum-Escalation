"""Compile a fixed route/return skeleton into continuous affine constraints."""
from dataclasses import dataclass
import math

from env.plan import active_count, coordinates
from env.scenario import _thaw
from env.units import time_field
from .linear import LinearProblem, Row, rational
from .physics import flight_duration, UnsupportedArithmetic, InadmissiblePath


class BranchRejected(ValueError):
    def __init__(self, reason, *, exact):
        super().__init__(reason)
        self.exact = exact


@dataclass(frozen=True)
class _Expr:
    coefficients: tuple
    constant: object = 0

    def _coerce(self, value):
        return value if isinstance(value,_Expr) else _Expr((0,)*len(self.coefficients),value)

    def __add__(self, other):
        other = self._coerce(other)
        return _Expr(tuple(a+b for a,b in zip(self.coefficients,other.coefficients)),self.constant+other.constant)

    __radd__ = __add__

    def __mul__(self, scalar):
        return _Expr(tuple(v*scalar for v in self.coefficients),self.constant*scalar)

    __rmul__ = __mul__

    def __neg__(self):
        return self*-1

    def __sub__(self, other):
        return self+-self._coerce(other)

    def __rsub__(self, other):
        return self._coerce(other)+-self


@dataclass(frozen=True)
class TransferProblem:
    problem: LinearProblem
    plan: dict
    columns: tuple
    times: tuple


def materialize(compiled, values):
    if len(values) != len(compiled.columns):
        raise ValueError('transfer point has incorrect dimension')
    plan = _thaw(compiled.plan)
    for (uid,h,a),value in zip(compiled.columns,values):
        plan['routes'][uid]['deliveries' if a=='x' else 'loads'][h] = float(value)
    return plan


def build_transfer_problem(scenario, plan, reserve_paths, releases, *, exact=True, duration_provider=None,
                           interval_provider=None):
    """`interval_provider(uid, path, departure_lo, departure_hi)` returns (arrival_lo,
    arrival_hi) for time-dependent wind. Times then follow the upper chain, and
    flight energy uses arrival_hi minus the departure lower bound, which bounds
    the duration for every departure in the window."""
    if duration_provider is not None and interval_provider is not None:
        raise ValueError('use a duration provider or an interval provider, not both')
    plan = _thaw(scenario.validate_candidate(plan))
    reserve_paths = scenario.validate_reserve_paths(plan,reserve_paths)
    data = scenario.data
    old,new = coordinates(data),coordinates(data,plan)
    if any(new[a][k] != old[a][k] for a in old for k in old[a] if k not in releases[a]):
        raise ValueError('skeleton changes a coordinate fixed at this scope')
    mission,state,protocol = data['mission'],data['state'],data['operations']
    fleet = {u['id']:u for u in mission['vehicles']}
    tasks = {t['id']:t for t in mission['tasks']}
    depot = tuple(mission['depot_xy'])
    number = rational if exact else float
    T = lambda stem: time_field(data,stem)
    v3 = data['schema_version'] == 'wind-benchmark-v3'
    epoch,horizon,mass = map(number,(mission[T('epoch')],mission[T('horizon')],mission['commodity_unit_mass_kg']))
    columns = []
    for uid,route in sorted(plan['routes'].items()):
        initial = state['fleet'][uid]
        origin = tuple(initial['position_xy']) == depot and initial['mode'] in ('idle','preparing')
        n = active_count(route)
        for h in range(len(route['stops'])+1):
            for a in ('x','y'):
                eligible = (a=='x' and 0<h<=n and route['stops'][h-1]!='DEPOT') or (
                    a=='y' and h<n and (origin if h==0 else route['stops'][h-1]=='DEPOT'))
                if eligible and f'{uid}:{h}:{a}' in releases['L']:
                    columns.append((uid,h,a))
                elif f'{uid}:{h}:{a}' in releases['L']:
                    route['deliveries' if a=='x' else 'loads'][h] = 0
    count = len(columns)
    indices = {key:i for i,key in enumerate(columns)}
    constant = lambda value: _Expr((0,)*count,number(value))
    rows, times, intervals = [],[],[]

    def le(left,right,label):
        expr = left-right if isinstance(left,_Expr) else constant(left)-right
        if not exact and not all(math.isfinite(v) for v in (*expr.coefficients,expr.constant)):
            raise UnsupportedArithmetic('nonfinite transfer coefficient')
        rows.append(Row(expr.coefficients,-expr.constant,label))

    def transfer(uid,h,a):
        key = (uid,h,a)
        if key not in indices:
            return constant(plan['routes'][uid]['deliveries' if a=='x' else 'loads'][h])
        expr = _Expr(tuple(number(int(j==indices[key])) for j in range(count)))
        le(-expr,0,f'nonnegative:{uid}:{h}:{a}')
        return expr

    transfers = {(uid,h,a):transfer(uid,h,a) for uid,r in plan['routes'].items()
                 for h in range(len(r['stops'])+1) for a in ('x','y')}
    delivered = {i:constant(0) for i in tasks}
    stock = constant(0)

    def duration(uid,path,time,label):
        try:
            dt = (flight_duration(scenario,uid,path,time,exact=exact) if duration_provider is None
                  else duration_provider(uid,path,time))
        except InadmissiblePath:
            raise BranchRejected('admissibility:'+label,exact=exact)
        if dt is None:
            raise BranchRejected(label,exact=exact)
        if dt < 0:
            raise ValueError('flight duration must be nonnegative')
        if duration_provider is not None and time+dt > horizon:
            raise BranchRejected(label,exact=exact)
        return dt

    lag = {}    # interval mode: upper chain time minus a lower bound on the true time

    def flight(uid,path,time,label,*,advance):
        """(time increment, duration charged for energy)."""
        if interval_provider is None:
            dt = duration(uid,path,time,label)
            return dt,dt
        lo = time-lag[uid]
        try:
            arrival_lo,arrival_hi = interval_provider(uid,path,lo,time)
        except InadmissiblePath:
            raise BranchRejected('admissibility:'+label,exact=exact)
        if arrival_lo is None or arrival_hi is None or arrival_hi > horizon:
            raise BranchRejected(label,exact=exact)
        if advance:
            lag[uid] = arrival_hi-arrival_lo
        return arrival_hi-time,arrival_hi-lo

    def energy(vehicle,load,dt):
        if v3:      # (a + b*m) W over dt seconds, in Wh
            total = number(vehicle['empty_mass_kg'])+mass*load
            return (number(vehicle['power_a_w'])+number(vehicle['power_b_w_per_kg'])*total)*(dt/number(3600))
        factor = number(vehicle['energy_coefficient_wh_per_kg_km'])*number(vehicle['airspeed_kmh'])*dt
        return (number(vehicle['empty_mass_kg'])+mass*load)*factor

    def reserve(uid,label,time,battery,load):
        path = reserve_paths.get(uid,{}).get(label)
        if path is None:
            raise ValueError(f'missing selected reserve path: {uid}:{label}')
        dt = flight(uid,path,time,f'reserve_horizon:{uid}:{label}',advance=False)[1]
        le(energy(fleet[uid],load,dt)+number(fleet[uid]['reserve_wh']),battery,f'reserve:{uid}:{label}')

    for uid,route in sorted(plan['routes'].items()):
        u,initial = fleet[uid],state['fleet'][uid]
        n = active_count(route)
        time,load,battery = epoch,constant(initial['onboard']),constant(initial['battery_wh'])
        lag[uid] = number(0)
        cap,res = number(u['battery_capacity_wh']),number(u['reserve_wh'])
        payload = number(u['payload_capacity_kg'])
        origin = tuple(initial['position_xy']) == depot and initial['mode'] in ('idle','preparing')
        if not origin:
            reserve(uid,'initial',time,battery,load)
        for h in range(n+1):
            at_depot = origin if h==0 else route['stops'][h-1]=='DEPOT'
            if h:
                dt,charged = flight(uid,route['paths'][h-1],time,f'horizon:{uid}:{h}:flight',advance=True)
                time += dt
                battery -= energy(u,load,charged)
                if at_depot:
                    le(res,battery,f'depot_arrival_reserve:{uid}:{h}')
            le(0,battery,f'battery:{uid}:{h}:lower')
            le(battery,cap,f'battery:{uid}:{h}:upper')
            x,y = transfers[uid,h,'x'],transfers[uid,h,'y']
            le(x,load,f'availability:{uid}:{h}')
            le(0,load,f'payload_before:{uid}:{h}:lower')
            le(mass*load,payload,f'payload_before:{uid}:{h}:upper')
            service_time = service_energy = number(0)
            if h and not at_depot:
                residual = initial['residual_operation'] if h==1 and initial['mode']=='servicing' else None
                service_time = number(protocol[T('service_duration')] if residual is None else residual[T('duration')])
                service_energy = number(protocol['service_energy_wh'] if residual is None else residual['energy_wh'])
                if v3 and residual is None:
                    # v3: hovering through service at the power of the mass on arrival.
                    service_energy = energy(u,load,service_time)+service_energy
            delivery_time = time+service_time
            preparation = number(0)
            if at_depot and h<n:
                residual = initial['residual_operation'] if h==0 and initial['mode']=='preparing' else None
                preparation = number(protocol[T('preparation_duration')] if residual is None else residual[T('duration')])
                if preparation > 0:
                    intervals.append((time,time+preparation))
            departure = delivery_time+preparation
            if departure > horizon:
                raise BranchRejected(f'horizon:{uid}:{h}:ground',exact=exact)
            battery -= service_energy
            le(0,battery,f'battery_service:{uid}:{h}')
            load = load-x+y
            le(0,load,f'payload_after:{uid}:{h}:lower')
            le(mass*load,payload,f'payload_after:{uid}:{h}:upper')
            if at_depot and h<n:
                battery = constant(cap)
                stock += y
            if h and not at_depot:
                site = route['stops'][h-1]
                delivered[site] += x
                deadline = tasks[site][T('deadline')]
                if deadline is not None and delivery_time > number(deadline)+(0 if exact else 1e-9):
                    le(x,0,f'deadline:{uid}:{h}:{site}')
                reserve(uid,str(h),delivery_time,battery,load)
            if h==0 and origin and n:
                reserve(uid,'initial',departure,battery,load)
            times.append(dict(uav=uid,slot=h,arrival=time,delivery=delivery_time,departure=departure))
            time = departure
        le(res,battery,f'terminal_reserve:{uid}')
    le(stock,number(state['depot_stock']),'inventory')
    for i,task in tasks.items():
        previous = number(state['cumulative_delivered'][i])
        le(max(number(0),number(task['mandatory'])-previous),delivered[i],f'service:{i}:mandatory')
        le(delivered[i],number(task['demand'])-previous,f'service:{i}:demand')
    bays = protocol['depot_bays']
    if bays is not None:
        concurrent = 0
        for _,change in sorted([(a,1) for a,b in intervals]+[(b,-1) for a,b in intervals]):
            concurrent += change
            if concurrent>bays:
                raise BranchRejected('depot_bays',exact=exact)
    problem = LinearProblem(tuple(f'{u}:{h}:{a}' for u,h,a in columns),tuple(rows),exact)
    return TransferProblem(problem,plan,tuple(columns),tuple(times))
