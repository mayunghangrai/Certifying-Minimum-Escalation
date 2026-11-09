"""Immutable, explicitly finite nominal and reserve path representation."""
from dataclasses import dataclass
import hashlib
import json

from env.geometry import canonical_path, polygon, validate_path
from env.scenario import _json_copy


@dataclass(frozen=True)
class PathLibrary:
    scenario_hash: str
    nominal: tuple
    returns: tuple
    slot_bounds: tuple

    @classmethod
    def build(cls, scenario, *, nominal_paths=(), return_paths=(), direct=True):
        data = scenario.data
        region = polygon(data['mission']['operating_region_xy'])
        depot = tuple(data['mission']['depot_xy'])
        points = sorted({depot, *(tuple(t['position_xy']) for t in data['mission']['tasks']),
                         *(tuple(s['position_xy']) for s in data['state']['fleet'].values())})
        nominal = list(nominal_paths)
        nominal.append([depot])  # Canonical inactive padding belongs to every representation.
        returns = list(return_paths)
        for route in data['incumbent']['routes'].values():
            nominal.extend(route['paths'])
        for paths in data['reserve_paths'].values():
            returns.extend(paths.values())
        returns.append([depot])
        if direct:
            for start in points:
                for end in points:
                    try:
                        path = validate_path([start,end], region)
                    except ValueError:
                        continue  # The direct segment is outside a nonconvex region.
                    nominal.append(path)
                    if end == depot:
                        returns.append(path)
        def normalize(paths, reserve):
            result = set()
            for path in paths:
                try:
                    value = canonical_path(validate_path(_json_copy(path), region))
                except (TypeError,ValueError,OverflowError) as error:
                    raise ValueError('library path must contain finite XY points inside the region') from error
                value = tuple(tuple(int(v) if v == int(v) else v for v in p) for p in value)
                if value[0] not in points or value[-1] not in points:
                    raise ValueError('library endpoints must be task, depot or observed-origin coordinates')
                if reserve and value[-1] != depot:
                    raise ValueError('return path must terminate at depot')
                result.add(value)
            return tuple(sorted(result))
        return cls(scenario.content_hash(), normalize(nominal,False), normalize(returns,True),
                   tuple(sorted((u['id'],u['slot_bound']) for u in data['mission']['vehicles'])))

    @classmethod
    def from_dict(cls, scenario, payload):
        p = _json_copy(payload)
        if (not isinstance(p,dict)
            or set(p) != {'version','scenario_hash','slot_bounds','nominal_paths','return_paths'}
            or p['version'] != 'finite-paths-v1'
            or not isinstance(p['nominal_paths'],list) or not isinstance(p['return_paths'],list)):
            raise ValueError('invalid path manifest')
        if p['scenario_hash'] != scenario.content_hash():
            raise ValueError('path manifest belongs to a different scenario')
        result = cls.build(scenario, nominal_paths=p['nominal_paths'], return_paths=p['return_paths'], direct=False)
        supplied = {canonical_path(path) for path in p['nominal_paths']}
        if supplied != set(result.nominal):
            raise ValueError('manifest omits an incumbent nominal path')
        if {canonical_path(path) for path in p['return_paths']} != set(result.returns):
            raise ValueError('manifest omits a previous return witness or constant depot path')
        if p['slot_bounds'] != dict(result.slot_bounds):
            raise ValueError('manifest slot bounds differ from scenario')
        return result

    def paths(self, start, end, *, reserve=False):
        return tuple(p for p in (self.returns if reserve else self.nominal)
                     if p[0] == tuple(start) and p[-1] == tuple(end))

    def to_dict(self):
        return dict(version='finite-paths-v1', scenario_hash=self.scenario_hash,
                    slot_bounds=dict(self.slot_bounds),
                    nominal_paths=[[list(p) for p in path] for path in self.nominal],
                    return_paths=[[list(p) for p in path] for path in self.returns])

    def content_hash(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(',',':')).encode()).hexdigest()

    def validate(self, scenario):
        # Validate even manually constructed dataclass instances at the public boundary.
        checked = self.from_dict(scenario,self.to_dict())
        if checked != self:
            raise ValueError('path manifest must be canonical')

    def contains(self, plan, reserves):
        return (all(canonical_path(p) in self.nominal for r in plan['routes'].values() for p in r['paths'])
                and all(canonical_path(p) in self.returns for paths in reserves.values() for p in paths.values()))
