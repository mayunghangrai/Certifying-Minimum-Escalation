"""Paired, typed dependency DAG for a fixed incumbent and diagnostic returns.

Path nodes summarize exact integration, including its internal bin selections
and horizon guards. Their wind parents are the union of inputs queried by both
evaluations. When evaluation is unavailable, every bin along the fixed path is
a declared conservative query support. No tolerance removes dependencies.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from fractions import Fraction

from .fixed_plan import evaluate_pair
from .intervention_scope import constraint_task_supports, task_closure
from .plan import remaining_tasks
from .units import time_field
from .wind import WindField


@dataclass(frozen=True)
class DependencyNode:
    kind: str
    name: str
    leg: str | None
    role: str
    parents: tuple[str, ...]
    previous: object
    received: object
    unit: str | None = None


class DependencyGraph:
    def __init__(self):
        self.nodes = {}

    def add(self, key, kind, name, values, parents=(), *, leg=None, role='nominal', unit=None):
        parents = tuple(sorted(set(parents)))
        if key in self.nodes or any(p not in self.nodes for p in parents):
            raise ValueError('dependency nodes must be unique and topologically ordered')
        self.nodes[key] = DependencyNode(kind, name, leg, role, parents, *values, unit)
        return key

    @property
    def edges(self):
        return tuple((p,key) for key,n in self.nodes.items() for p in n.parents)

    def reach(self, seeds):
        reached = set(seeds)
        for key,n in self.nodes.items():
            if reached.intersection(n.parents): reached.add(key)
        return frozenset(reached)


def _unit(name):
    if name.endswith('_h'): return 'time_h'
    if name.endswith('_wh') or name.startswith('battery_'): return 'energy_wh'
    if name.startswith('onboard'): return 'quantity'
    if name.endswith('_km'): return 'distance_km'
    if name.endswith('_kmh'): return 'speed_kmh'
    return None


def _changed(a, b, tolerances, unit=None):
    # Definedness and categorical changes always have zero reporting tolerance.
    if a is None or b is None: return (a is None) != (b is None)
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) != set(b) or any(_changed(a[k], b[k], tolerances, _unit(k)) for k in a)
    if isinstance(a, (tuple,list)) and isinstance(b, (tuple,list)):
        return len(a) != len(b) or any(_changed(x,y,tolerances,unit) for x,y in zip(a,b))
    if isinstance(a, (int,float)) and not isinstance(a,bool) and isinstance(b, (int,float)) and not isinstance(b,bool):
        return abs(a-b) > tolerances.get(unit, 0.)
    return a != b


@dataclass(frozen=True)
class WindDiagnostic:
    previous: object
    received: object
    graph: DependencyGraph
    changed_atoms: frozenset[str]
    relevant_atoms: frozenset[str]
    seed_support: frozenset[str]
    structural_closure: frozenset[str]
    material_support: frozenset[str]
    operational_support: frozenset[str]
    reportable_support: frozenset[str]
    legs: dict
    affected_tasks: frozenset[str]
    structural_tasks: frozenset[str]
    material_tasks: frozenset[str]
    task_supports: dict
    task_closure: frozenset[str]
    neighborhood: frozenset[str]
    tolerances: dict

    def to_dict(self):
        result = {name: sorted(getattr(self,name)) for name in (
            'changed_atoms','relevant_atoms','seed_support','structural_closure',
            'material_support','operational_support','reportable_support',
            'affected_tasks','structural_tasks','material_tasks','task_closure','neighborhood')}
        result.update(graph={key:asdict(n) for key,n in self.graph.nodes.items()},
                      legs=self.legs, task_supports={g:sorted(s) for g,s in self.task_supports.items()},
                      tolerances=self.tolerances, input_hash=self.previous.input_hash)
        return result


def diagnose_wind_update(scenario, *, tolerances=None):
    """Diagnose the fixed incumbent; never search for a repair or a minimum level."""
    tolerance = dict(time_h=1e-9, energy_wh=1e-9, quantity=1e-9,
                     distance_km=1e-9, speed_kmh=1e-9)
    if scenario.data['schema_version'] == 'wind-benchmark-v3':
        # Unit labels are historical; v3 values are s and m, about 1e4 in size.
        tolerance.update(time_h=1e-6, distance_km=1e-6)
    if tolerances is not None:
        if set(tolerances)-set(tolerance) or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v < 0 for v in tolerances.values()):
            raise ValueError('reporting tolerances must be finite nonnegative values in declared units')
        tolerance.update(tolerances)
    previous, received = evaluate_pair(scenario)
    projections = (previous, received)
    data, graph = scenario.data, DependencyGraph()
    wind = data['wind']
    atoms = {}
    def entry(projection, r, j):
        packet = wind[projection]
        if data['schema_version'] in ('wind-benchmark-v2', 'wind-benchmark-v3'):
            # Physical values and definedness affect evaluation. Provenance labels
            # and equivalent numeric encodings must not inflate the affected set.
            vector = tuple(str(Fraction(str(v))) for v in packet['values'][r][j])
            return (vector, packet['admissible'][r][j], packet['coverage'][j] != 'missing')
        return packet['values'][r][j]
    for r,cell in enumerate(wind['cells']):
        for j in range(len(wind[time_field(data, 'time_knots')])-1):
            a,b = entry('previous',r,j),entry('received',r,j)
            if a != b:
                atoms[cell['id'],j] = graph.add(f'change:{cell["id"]}:{j}', 'change', 'wind_entry', (a,b), unit='speed_kmh')
    fields = (WindField(scenario,'previous'), WindField(scenario,'received'))
    cell_rows = {c['id']:r for r,c in enumerate(wind['cells'])}
    leg_queries, query_details, entering_nodes = {}, {}, {}

    def node(key, kind, name, values, parents=(), leg=None, role='nominal', unit=None):
        return graph.add(key,kind,name,values,parents,leg=leg,role=role,unit=unit)

    def path_graph(prefix, leg, role, path, states, results, parent):
        queries, conservative = [], []
        for field,result in zip(fields,results):
            unavailable = result is None or result.get('status') == 'unavailable'
            support = {(q['cell_id'],q['bin_index']) for q in result.get('slices',())} if result else set()
            if unavailable and path is not None:
                support.update((wind['cells'][r]['id'],j) for _,_,r in field.split_path(path)
                               for j in range(len(field.knots)-1))
            queries.append(support)
            conservative.append(unavailable)
        union = queries[0] | queries[1]
        leg_queries.setdefault(leg,set()).update(union)
        query_details[prefix] = dict(previous=sorted(queries[0]), received=sorted(queries[1]), conservative=conservative)
        inputs = []
        for cell,j in sorted(union):
            r = cell_rows[cell]
            atom = atoms.get((cell,j))
            inputs.append(node(f'{prefix}:wind:{cell}:{j}', 'wind', 'wind_query',
                (entry('previous',r,j), entry('received',r,j)),
                () if atom is None else (atom,), leg, role, 'speed_kmh'))
        args = [parent,*inputs]
        # These summarize all internal loop guards, not just the departure bin.
        bins = [None if r is None else [(q['cell_id'],q['bin_index']) for q in r.get('slices',())] for r in results]
        selector = node(prefix+':bins','stat','time_bin_selection',bins,args,leg,role)
        status = [None if r is None else r['status'] for r in results]
        guard = node(prefix+':horizon','stat','horizon_guard',status,args,leg,role)
        evaluation = node(prefix+':evaluation','eval','path_integration',results,[*args,selector,guard],leg,role)
        quantities = {}
        for name in ('arrival_h','duration_h','energy_wh'):
            quantities[name] = node(prefix+':'+name,'qty',name,
                [None if r is None else r[name] for r in results],[evaluation],leg,role,_unit(name))
        return [guard,evaluation,*quantities.values()]

    def reserve_graph(uid,label,leg,parent):
        checks = [p.reserve_checks.get(f'reserve:{uid}:{label}') for p in projections]
        states = [None if c is None else c['state'] for c in checks]
        prefix = f'{leg}:reserve:{label}'
        role = 'initial_reserve' if label == 'initial' else 'reserve'
        state = node(prefix+':state','state','reserve_state',states,[parent],leg,role)
        results = [None if c is None or c['flight_status'] == 'unavailable' else dict(
            status=c['flight_status'], arrival_h=c['arrival_h'], duration_h=c['duration_h'],
            energy_wh=c['energy_wh'], slices=c['wind_queries']) for c in checks]
        parents = path_graph(prefix,leg,role,data['reserve_paths'][uid].get(str(label)),states,results,state)
        margin = node(prefix+':margin','qty','margin_wh',[None if c is None else c['margin_wh'] for c in checks],
                      [state,*parents],leg,role,'energy_wh')
        node(prefix+':status','stat','reserve_status',[None if c is None else c['status'] for c in checks],
             [margin,*parents],leg,role)

    for uid,route in data['incumbent']['routes'].items():
        records = [p.records[uid] for p in projections]
        origin = node(uid+':observed','state','observed_state',[r[0]['entering_state'] for r in records])
        parent = node(uid+':origin','eval','initial_ground_operation',[r[0] for r in records],[origin])
        n = len(records[0])-1
        if n:
            reserve_graph(uid,'initial',f'{uid}:1',parent)
        for h in range(1,n+1):
            leg = f'{uid}:{h}'
            recs = [r[h] for r in records]
            states = [r['entering_state'] for r in recs]
            entering = node(leg+':entering','state','entering_state',states,[parent],leg)
            entering_nodes[leg] = entering
            parents = path_graph(leg+':nominal',leg,'nominal',route['paths'][h-1],states,[r['flight'] for r in recs],entering)
            guard = node(leg+':ground_guard','stat','ground_horizon_guard',
                         [None if r['arrival_h'] is None else r['status'] for r in recs],
                         [entering,*parents],leg)
            quantities = []
            for name in ('arrival_h','delivery_h','departure_h','onboard_before','onboard_after',
                         'battery_before','battery_after','service_energy_wh'):
                quantities.append(node(leg+':'+name,'qty',name,[r[name] for r in recs],[entering,guard,*parents],leg,unit=_unit(name)))
            local = []
            site = route['stops'][h-1]
            for p,r in zip(projections,recs):
                available = {
                    f'battery:{uid}:{h}:arrival': r['arrival_h'] is not None,
                    f'battery:{uid}:{h}:service': r['service_energy_wh'] is not None,
                    f'payload:{uid}:{h}': r['arrival_h'] is not None,
                    f'delivery_availability:{uid}:{h}': r['arrival_h'] is not None,
                    f'depot_arrival_reserve:{uid}:{h}': r['arrival_h'] is not None}
                local.append({k:('inactive' if k.startswith('depot_arrival_reserve:') and site != 'DEPOT' else
                                  'failed' if k in p.violations else 'passed' if defined else 'unavailable')
                              for k,defined in available.items()})
            node(leg+':resources','stat','resource_checks',local,quantities,leg)
            if site != 'DEPOT':
                task = next(t for t in data['mission']['tasks'] if t['id'] == site)
                due = task[time_field(data, 'deadline')]
                active = route['deliveries'][h] > 0 and due is not None
                deadline = [None if active and r['delivery_h'] is None else
                            due-r['delivery_h'] if active else None for r in recs]
                slack = node(leg+':deadline_slack','qty','deadline_slack_h',deadline,quantities,leg,unit='time_h')
                label = f'deadline:{uid}:{h}:{site}'
                node(leg+':deadline','stat','deadline_status',[
                    'inactive' if not active else 'failed' if label in p.violations else
                    'unavailable' if r['delivery_h'] is None else 'passed' for p,r in zip(projections,recs)], [slack],leg)
            # A reserve check is diagnostic only: no reserve node is a parent
            # of the nominal transition, including the first departure state.
            parent = node(leg+':post','state','post_stop_state',[
                None if r['status'] != 'complete' else dict(
                    time_h=r['departure_h'] if h<n else r['delivery_h'],
                    battery_wh=r['battery_after'], onboard=r['onboard_after'], site=site)
                for r in recs], quantities+[guard],leg)
            if site != 'DEPOT': reserve_graph(uid,str(h),leg,parent)
        node(uid+':terminal','stat','terminal_check',[
            dict(state=p.final_states[uid], status='failed' if f'terminal:{uid}' in p.violations else
                 'unavailable' if p.final_states[uid] is None else 'passed') for p in projections],[parent])

    relevant = frozenset(p for n in graph.nodes.values() if n.kind == 'wind' for p in n.parents)
    seeds = relevant | frozenset(key for key,n in graph.nodes.items() if n.kind == 'wind' and relevant.intersection(n.parents))
    closure = graph.reach(seeds)
    material = frozenset(key for key in closure if graph.nodes[key].kind != 'change' and
        _changed(graph.nodes[key].previous,graph.nodes[key].received,tolerance,
                 None if graph.nodes[key].kind == 'stat' else graph.nodes[key].unit))
    operational = frozenset(key for key in material if graph.nodes[key].kind != 'wind')
    reportable = seeds | material
    legs, affected_tasks, structural_tasks, material_tasks = {}, set(), set(), set()
    tasks = remaining_tasks(data)
    for uid,route in data['incumbent']['routes'].items():
        for h,site in enumerate(route['stops'],1):
            if site is None: break
            leg = f'{uid}:{h}'
            vertices = {key for key,n in graph.nodes.items() if n.leg == leg}
            entry = graph.nodes[entering_nodes[leg]]
            incidence = {site, route['stops'][h-2]} if h>1 else {site} | {
                t['id'] for t in data['mission']['tasks'] if tuple(t['position_xy']) == tuple(data['state']['fleet'][uid]['position_xy'])}
            incidence &= tasks
            details = query_details[leg+':nominal']
            legs[leg] = dict(direct=bool(vertices & seeds), propagated=h>1 and _changed(entry.previous,entry.received,tolerance),
                material=bool(vertices & operational), affected=bool(vertices & reportable),
                structural=bool(vertices & closure), incident_tasks=sorted(incidence),
                query_support=[list(q) for q in sorted(leg_queries[leg])],
                nominal_queries_previous=[list(q) for q in details['previous']],
                nominal_queries_received=[list(q) for q in details['received']],
                conservative_queries_previous=details['conservative'][0], conservative_queries_received=details['conservative'][1])
            for target,support in ((affected_tasks,reportable),(structural_tasks,closure),(material_tasks,operational)):
                if vertices & support: target.update(incidence)
    supports = constraint_task_supports(scenario)
    task_reached = task_closure(tasks,affected_tasks,supports)
    neighborhood = task_reached - set(data['commitments']['A'])
    return WindDiagnostic(previous,received,graph,frozenset(atoms.values()),relevant,seeds,closure,material,
        operational,reportable,legs,frozenset(affected_tasks),frozenset(structural_tasks),frozenset(material_tasks),
        supports,task_reached,frozenset(neighborhood),tolerance)
