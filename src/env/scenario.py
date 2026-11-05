"""Strict immutable epoch snapshots for the 2026-09-17 formulation."""
from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

from jsonschema import Draft202012Validator
from shapely.geometry import Point
from shapely.ops import unary_union

from .geometry import polygon, validate_path
from .plan import validate_plan

SCHEMA_VERSION = 'wind-benchmark-v1'
SCHEMA_PATH = Path(__file__).resolve().parents[2] / 'schemas' / f'{SCHEMA_VERSION}.schema.json'
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
_VALIDATOR = Draft202012Validator(SCHEMA)
_V2_VALIDATOR = Draft202012Validator(json.loads(
    SCHEMA_PATH.with_name('wind-benchmark-v2.schema.json').read_text(encoding='utf-8')))
_V3_VALIDATOR = Draft202012Validator(json.loads(
    SCHEMA_PATH.with_name('wind-benchmark-v3.schema.json').read_text(encoding='utf-8')))
_EXACT_VERSIONS = ('wind-benchmark-v2', 'wind-benchmark-v3')
# Unit-carrying field names; v1 and v2 share km and h, v3 uses m and s.
_HOURS_NAMES = dict(epoch='epoch_h', horizon='horizon_h', deadline='deadline_h', knots='time_knots_h',
                    bound='speed_bound_kmh', airspeed='airspeed_kmh', issued='issued_at_h')
_SI_NAMES = dict(epoch='epoch_s', horizon='horizon_s', deadline='deadline_s', knots='time_knots_s',
                 bound='speed_bound_mps', airspeed='airspeed_mps', issued='issued_at_s')


def _names(data):
    return _SI_NAMES if data.get('schema_version') == 'wind-benchmark-v3' else _HOURS_NAMES
_PLAN_VALIDATOR = Draft202012Validator(SCHEMA['properties']['incumbent'])
_RESERVE_VALIDATOR = Draft202012Validator(SCHEMA['properties']['reserve_paths'])


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    if isinstance(value, (int,float)) and not math.isfinite(value):
        raise ValueError('numbers must be finite in the floating-point evaluator')
    return value


def _json_copy(value):
    try:
        return json.loads(json.dumps(_thaw(value), allow_nan=False))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('input must contain finite JSON values representable by the floating-point evaluator') from error


def _validate_shape(validator, value):
    errors = sorted(validator.iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        raise ValueError(f"invalid schema at {'.'.join(map(str,error.path))}: {error.message}")


def _unique(items, name):
    ids = [item['id'] for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError(f'{name} IDs must be unique')
    return set(ids)


def _validate(data):
    mission, state, wind = data['mission'], data['state'], data['wind']
    N = _names(data)
    epoch, horizon = mission[N['epoch']], mission[N['horizon']]
    if epoch >= horizon:
        raise ValueError('epoch must precede mission horizon')
    region = polygon(mission['operating_region_xy'])
    task_ids = _unique(mission['tasks'], 'task')
    uav_ids = _unique(mission['vehicles'], 'UAV')
    if 'DEPOT' in task_ids:
        raise ValueError('DEPOT is reserved')
    if set(state['cumulative_delivered']) != task_ids or set(state['fleet']) != uav_ids:
        raise ValueError('observed state must contain exactly the mission task and UAV IDs')
    for task in mission['tasks']:
        if task['mandatory'] > task['demand'] or state['cumulative_delivered'][task['id']] > task['demand']:
            raise ValueError('mandatory and delivered quantities must not exceed demand')
        if task[N['deadline']] is not None and task[N['deadline']] > horizon:
            raise ValueError('deadline must lie within mission horizon')
        if data['schema_version'] == 'wind-benchmark-v3':
            # Rule 1: whole packages, all mandatory, each demand fits in one load.
            if task['mandatory'] != task['demand'] or task['demand'] != int(task['demand']):
                raise ValueError('v3 demand must be a whole number of packages, all mandatory')
            if all(mission['commodity_unit_mass_kg']*task['demand'] > u['payload_capacity_kg'] for u in mission['vehicles']):
                raise ValueError('v3 demand must fit in one load')
    if data['schema_version'] == 'wind-benchmark-v3':
        # P(m) = a + b*m with b >= 0 is positive on every flying mass iff it is at the empty mass.
        if any(u['power_a_w'] + u['power_b_w_per_kg']*u['empty_mass_kg'] <= 0 for u in mission['vehicles']):
            raise ValueError('v3 power must be positive at the empty mass')
    for point in [mission['depot_xy'], *(i['position_xy'] for i in mission['tasks']), *(s['position_xy'] for s in state['fleet'].values())]:
        if not region.covers(Point(point)):
            raise ValueError('site or observed position is outside operating region')
    for u in mission['vehicles']:
        # JSON Schema integers include integral floats such as 5.0.
        u['slot_bound'] = int(u['slot_bound'])
        s = state['fleet'][u['id']]
        if u['reserve_wh'] > u['battery_capacity_wh'] or s['battery_wh'] > u['battery_capacity_wh']:
            raise ValueError('reserve and observed battery must not exceed capacity')
        if mission['commodity_unit_mass_kg'] * s['onboard'] > u['payload_capacity_kg']:
            raise ValueError('observed payload exceeds mass capacity')
        if (s['mode'] in ('servicing', 'preparing')) != (s['residual_operation'] is not None):
            raise ValueError('unfinished ground mode requires exactly one residual operation')
    cell_ids = _unique(wind['cells'], 'wind cell')
    cells = [polygon(c['polygon_xy']) for c in wind['cells']]
    if any(not region.covers(cell) for cell in cells):
        raise ValueError('wind cell is outside operating region')
    if not unary_union(cells).equals(region) or any(cells[r].intersection(cells[s]).area > 0 for r in range(len(cells)) for s in range(r)):
        raise ValueError('wind cells must cover the region without interior overlap')
    knots = wind[N['knots']]
    if knots[0] != epoch or knots[-1] != horizon or any(b <= a for a,b in zip(knots, knots[1:])):
        raise ValueError('time bins must partition the full remaining horizon')
    bound = wind[N['bound']]
    if bound >= min(u[N['airspeed']] for u in mission['vehicles']):
        raise ValueError('wind bound must be strictly below every airspeed')
    for projection in ('previous', 'received'):
        packet = wind[projection]
        if packet[N['issued']] > epoch or (projection == 'received' and packet[N['issued']] != epoch):
            raise ValueError('only wind received at or before the epoch may be evaluated')
        if len(packet['values']) != len(cells) or any(len(row) != len(knots)-1 for row in packet['values']):
            raise ValueError('wind table must cover every cell-time entry')
        exceeds = (lambda w: sum(Fraction(str(v))**2 for v in w) > Fraction(str(bound))**2
                   ) if data['schema_version'] in _EXACT_VERSIONS else (lambda w: math.hypot(*w)>bound)
        if any(exceeds(w) for row in packet['values'] for w in row):
            raise ValueError('wind vector exceeds the declared bound')
    support = {tuple(entry) for entry in wind['update_support']}
    if len(support) != len(wind['update_support']) or len(support) >= len(cells)*(len(knots)-1):
        raise ValueError('update support must be a proper subset with unique entries')
    if any(cell not in cell_ids or j >= len(knots)-1 for cell,j in support):
        raise ValueError('unknown cell-time update entry')
    for r,cell in enumerate(wind['cells']):
        for j,(before,after) in enumerate(zip(wind['previous']['values'][r],wind['received']['values'][r])):
            if data['schema_version'] in _EXACT_VERSIONS:
                before,after = (tuple(Fraction(str(v)) for v in vector) for vector in (before,after))
            if before != after and (cell['id'],j) not in support:
                raise ValueError('wind changed outside the declared local support')
    validate_plan(data, data['incumbent'])
    if set(data['reserve_paths']) != uav_ids:
        raise ValueError('reserve paths must name exactly the fleet')
    for u, paths in data['reserve_paths'].items():
        route = data['incumbent']['routes'][u]
        for label,path in paths.items():
            if label == 'initial':
                start = state['fleet'][u]['position_xy']
            else:
                if not label.isdigit() or str(int(label)) != label or not 1 <= int(label) <= len(route['stops']):
                    raise ValueError('invalid reserve state label')
                stop = route['stops'][int(label)-1]
                matches = [i for i in mission['tasks'] if i['id'] == stop]
                if not matches:
                    raise ValueError('reserve state must identify an active relief visit')
                start = matches[0]['position_xy']
            validate_path(path, region, start, mission['depot_xy'])


class Scenario:
    """Validated immutable input; both wind projections share this same object."""
    __slots__ = ('_data',)

    def __init__(self, payload):
        data = _json_copy(payload)
        validator = {'wind-benchmark-v2': _V2_VALIDATOR, 'wind-benchmark-v3': _V3_VALIDATOR
                     }.get(data.get('schema_version'), _VALIDATOR)
        _validate_shape(validator, data)
        _validate(data)
        if data['schema_version'] in _EXACT_VERSIONS:
            wind = data['wind']
            for projection in ('previous', 'received'):
                packet = wind[projection]
                n = len(wind[_names(data)['knots']])-1
                if (len(packet['coverage']) != n or len(packet['admissible']) != len(wind['cells'])
                        or any(len(row) != n for row in packet['admissible'])):
                    raise ValueError('admissibility and coverage must match the cell-time partition')
                retained = [j for j,v in enumerate(packet['coverage']) if v == 'retained']
                if retained:
                    source = wind['previous']
                    source_hash = hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                    if projection != 'received' or packet.get('retained_from') != source_hash:
                        raise ValueError('retained tail requires the previous packet hash')
                    if any(source['coverage'][j] == 'missing' or any(
                            packet[a][r][j] != source[a][r][j]
                            for a in ('values','admissible') for r in range(len(wind['cells']))) for j in retained):
                        raise ValueError('retained tail must preserve the identified previous entries')
            support = {tuple(v) for v in wind['update_support']}
            if any(wind['previous']['admissible'][r][j] != wind['received']['admissible'][r][j]
                   and (c['id'],j) not in support
                   for r,c in enumerate(wind['cells']) for j in range(n)):
                raise ValueError('admissibility changed outside the declared local support')
            data['hierarchy']['helper_budget'] = int(data['hierarchy']['helper_budget'])
        object.__setattr__(self, '_data', _freeze(data))

    def __setattr__(self, name, value):
        raise AttributeError('Scenario is immutable')

    @property
    def data(self):
        return self._data

    @classmethod
    def from_dict(cls, payload):
        return cls(payload)

    @classmethod
    def from_json(cls, path):
        def no_duplicates(pairs):
            result = {}
            for key,value in pairs:
                if key in result:
                    raise ValueError(f'duplicate JSON key: {key}')
                result[key] = value
            return result
        return cls(json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=no_duplicates))

    def to_dict(self):
        return _thaw(self._data)

    def to_json(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, allow_nan=False)+'\n', encoding='utf-8')

    def content_hash(self):
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    def validate_candidate(self, plan, *, enforce_commitments=True):
        candidate = _json_copy(plan)
        _validate_shape(_PLAN_VALIDATOR, candidate)
        validate_plan(self._data, candidate, enforce_commitments=enforce_commitments)
        return _freeze(candidate)

    def validate_reserve_paths(self, plan, paths):
        """Validate supplied geometry/labels; missing witnesses remain unresolved."""
        paths = _json_copy(paths)
        _validate_shape(_RESERVE_VALIDATOR, paths)
        if set(paths)-set(self.data['state']['fleet']):
            raise ValueError('reserve witnesses must be keyed by known UAV')
        region = polygon(self.data['mission']['operating_region_xy'])
        tasks = {t['id']:t['position_xy'] for t in self.data['mission']['tasks']}
        for uid,entries in paths.items():
            for label,path in entries.items():
                if label == 'initial':
                    start = self.data['state']['fleet'][uid]['position_xy']
                else:
                    stops = plan['routes'][uid]['stops']
                    if not label.isdigit() or str(int(label)) != label or not 1 <= int(label) <= len(stops) or stops[int(label)-1] not in tasks:
                        raise ValueError(f'invalid reserve state label: {uid}:{label}')
                    start = tasks[stops[int(label)-1]]
                validate_path(path,region,start,self.data['mission']['depot_xy'])
        return _freeze(paths)
