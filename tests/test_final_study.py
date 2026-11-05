"""Final study: generator admission and conservation, LS quotas, arena fairness rules."""
from fractions import Fraction
import json

from certify_v2.accounting import Clock
from certify_v2.levels import Instance
from env.local_scope import affected_uavs
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from escalation_study.snapshots import build_snapshot, conservation
from final_study.arena import run_instance
from final_study.generator import REFERENCE, factorial_mission, level0_screen, variant_id
from final_study.levelsuite import CLASS_NAMES, ls_draw, select


def _mission():
    return factorial_mission(4, 2, 'medium', 'medium', 'uniform', 75001)


def test_fs_mission_is_admitted_disrupted_and_conserves_stock():
    variants, ledger = _mission()
    assert ledger['status'] == 'accepted' and ledger['selection_uses_recovery_labels'] is False
    assert len(variants) == 9
    reference = Scenario(variants[variant_id(ledger['mission'], *REFERENCE)])
    u0 = affected_uavs(reference, diagnose_wind_update(reference))['uavs']
    assert 1 <= len(u0) <= 2 and u0 == ledger['affected']
    assert level0_screen(reference) == 'disrupted'
    base = variants[variant_id(ledger['mission'], 1, 0)]
    for ti in (1, 2):
        snap = variants[variant_id(ledger['mission'], 1, ti)]
        assert conservation(base, snap)
        assert snap['commitments'] == {a: [] for a in 'ASPL'}          # D1' adds no commitment
        assert Fraction(str(snap['mission']['epoch_h'])) > 0
    # Deadlines follow the urgency classes: u_i + max(1 min, c_i sigma tau).
    tau = Fraction(ledger['tau'])
    for t, (lo, hi) in ledger['previous_delivery'].items():
        margin = Fraction(ledger['deadlines'][t])-Fraction(hi)
        expected = max(Fraction(1, 60), ledger['classes'][t]*Fraction(ledger['sigma_value'])*tau)
        assert expected <= margin < expected+Fraction(1, 10**9)


def test_d1_snapshot_commits_the_destination():
    variants, ledger = _mission()
    base = variants[variant_id(ledger['mission'], 1, 0)]
    cell = ledger['cell_index']
    wind = base['wind']['received']['values'][cell][0]
    snap, _ = build_snapshot(base, '1/4', received_wind=(cell, wind), rule='D1')
    airborne = [u for u, s in snap['state']['fleet'].items() if s['mode'] == 'airborne']
    assert airborne and all(f'{u}:1' in snap['commitments']['S'] for u in airborne)


def test_ls_selection_fills_quotas_in_draw_order_and_never_reads_recipes():
    config = dict(quota_per_fleet=3, fleets=[4], residue=1, residue_seed=0)
    draws = []
    for i, cls in enumerate(['1', '1', '2', '1', '1', None, 'infinity', '1']):
        bounds = dict(minimum=None if cls is None else 'infinity' if cls == 'infinity' else int(cls),
                      lower=1, upper=None)
        label = dict(result=dict(bounds=bounds), audit=dict(ok=True))
        ledger = dict(status='admitted', fleet=4, time=['0', '1/4', '1/2'][i % 3], recipe='helper')
        draws.append((f'd{i}', ledger, label))
    result = select(draws, config)
    # Quota 3 per fleet means at most one per update time: d3 (t = 0) and d4, d7 (t = 1/4) wait.
    assert result['selected']['1'] == ['d0', 'd1']
    assert result['counts']['1|4|0'] == 1 and result['counts']['1|4|1/2'] == 0
    assert result['selected']['2'] == ['d2'] and result['selected']['infinity'] == ['d6']
    assert result['hard'] == ['d5']
    assert set(result['selected']) == set(CLASS_NAMES)


def test_arena_runs_every_arm_cold_on_identical_inputs_within_cpu_budget():
    variants, ledger = _mission()
    vid = variant_id(ledger['mission'], 1, 0)
    record = json.loads(json.dumps(run_instance(vid, variants[vid], 3, ('LR', 'CMI', 'PH'))))
    assert sorted(record['order']) == ['CMI', 'LR', 'PH']
    hashes = {entry['input_hash'] for entry in record['arms'].values()}
    assert hashes == {record['input_hash']}
    for arm, entry in record['arms'].items():
        assert entry['audit']['ok'], (arm, entry['audit'])
        clock = entry['result']['clock']
        assert clock['cpu_s'] <= 3+max(2., clock['overrun_s'])
        if entry['result']['plan']:
            assert entry['decisions'] is not None
    # Cold starts: the same instance gives the same answer whatever ran before it.
    first = json.loads(json.dumps(run_instance(vid, variants[vid], 60, ('CMI',))))
    again = json.loads(json.dumps(run_instance(vid, variants[vid], 60, ('CMI',))))
    assert first['arms']['CMI']['result']['bounds'] == again['arms']['CMI']['result']['bounds']
    assert first['arms']['CMI']['result']['bounds']['minimum'] is not None


def test_level_searches_stay_in_their_level_and_noaf_is_scored_with_the_true_u0():
    """Regression (pilot, 14 Oct): a noAF plan from its Level-3 mask (reassignment over the
    whole fleet) is a true Level-4 plan; the ladder used to reject it. And a level search
    never accepts a plan through a higher level's patch."""
    variants, ledger = factorial_mission(4, 3, 'medium', 'medium', 'uniform', 77103)
    vid = variant_id(ledger['mission'], 1, 2)
    record = json.loads(json.dumps(run_instance(vid, variants[vid], 20, ('CMI', 'noAF'))))
    for arm, entry in record['arms'].items():
        assert entry['audit']['ok'], (arm, entry['audit'])
        plan = entry['result']['plan']
        if plan:
            assert plan['witness']['patch']['level'] <= plan['found_by']
    cmi = record['arms']['CMI']['result']
    assert cmi['bounds']['excluded_levels'] == [0, 1, 2] and cmi['plan']['level'] == 3
    witness = cmi['plan']['witness']
    instance = Instance(Scenario(variants[vid]), Clock())
    assert instance.exact(witness['plan'], witness['reserve_paths'], start=1, stop=2) == (None, None)
    assert instance.exact(witness['plan'], witness['reserve_paths'], start=1)[1] == 3


def test_ls_draw_that_fails_the_previous_premise_is_rejected_not_raised():
    """Regression (pilot, 14 Oct): after this in-flight snapshot the reserve check of U2 is
    unresolved under the previous wind; the U0 diagnosis used to raise before the premise check."""
    payload, ledger = ls_draw('1', 4, 4, base_seed=77901)
    assert payload is None and ledger['status'] == 'rejected'
    assert ledger['reason'] == 'previous_premise_failed'


def test_d1_units_rebuild_in_flight_variants_in_the_worker_and_failures_are_noted(tmp_path):
    from final_study.stages import _fs_d1, _note, d1_units
    from final_study.store import Store
    variants, ledger = _mission()
    config = dict(label_budget_s=5, settings={})
    store = Store(tmp_path/'run', config)
    store.save(dict(version='final-study-fs-mission-v1', mission=ledger['mission'], ledger=ledger, variants=variants),
               'fs', 'missions', ledger['mission'])
    units = d1_units(store, config)
    assert len(units) == 6 and all(name.endswith('_D1') and '_t0' not in name for name, _, _ in units)
    name, _ = _fs_d1(str(store.path), config, units[0])
    record = store.load('fs_d1', 'labels', name)
    assert record['audit']['ok'] and record['instance'] == name
    assert len(d1_units(store, config)) == 5
    _note(store.path, 'fs-d1', name, 'FAILED: ValueError: example')
    assert (store.path/'failures'/'fs-d1'/(name+'.txt')).exists()
    _note(store.path, 'fs-d1', name, None)
    assert not (store.path/'failures'/'fs-d1'/(name+'.txt')).exists()


def test_saved_labels_and_arena_results_keep_their_proofs_for_a_later_replay(tmp_path):
    """Review (15 Oct): the evidence and records go to a proof file the record cites; the saved
    result alone does not replay, the result with its proof file does."""
    from final_study.arena import replay_saved
    from final_study.stages import _arena, _label
    from final_study.store import Store
    variants, ledger = _mission()
    vid = variant_id(ledger['mission'], 1, 0)
    config = dict(label_budget_s=20, settings={})
    store = Store(tmp_path/'run', config)
    _label(str(store.path), config, ('fs', vid, variants[vid]))
    _arena(str(store.path), config, ('fs', 'arena_5s', vid, variants[vid], 5, ('CMI', 'LR')))
    label = store.load('fs', 'labels', vid)
    assert label['result']['bounds']['minimum'] is not None and 'evidence' not in label['result']
    assert label['proofs']['keys'] == ['CMI'] and (store.path/label['proofs']['file']).exists()
    assert replay_saved(variants[vid], label, None)['CMI']['ok'] is False
    assert replay_saved(variants[vid], label, store.load_proofs(label))['CMI']['ok']
    arena = store.load('fs', 'arena_5s', vid)
    audits = replay_saved(variants[vid], arena, store.load_proofs(arena))
    assert all(a['ok'] for a in audits.values()), audits
    assert store.all('fs', 'labels') == [store.unit('fs', 'labels', vid)]      # proof files are not units


def test_level0_screen_records_timeouts_and_errors_instead_of_not_disrupted(monkeypatch):
    """Review (15 Oct): only a Level-0 plan means "not disrupted"."""
    import final_study.generator as generator
    variants, ledger = _mission()
    reference = Scenario(variants[variant_id(ledger['mission'], *REFERENCE)])
    assert level0_screen(reference, seconds=0) == 'screening_unresolved'

    def broken(self):
        raise ValueError('example')
        yield
    monkeypatch.setattr(generator.Instance, 'level0', broken)
    assert level0_screen(reference) == 'screening_error: ValueError: example'


def test_lr_repairs_an_energy_shortfall_when_no_delivery_is_late(monkeypatch):
    """Review (15 Oct): without the energy trigger LR stopped once nothing was late and the exact
    checker rejected its plan on this recharge draw; with it, LR returns a plan that replays."""
    from fractions import Fraction
    from certify_v2.baselines import Routes, run_lr
    from certify_v2.replay import verify_run
    payload, ledger = ls_draw('2', 4, 59, base_seed=77901)
    assert ledger['recipe'] == 'recharge'
    result = run_lr(Scenario(payload), 10)
    assert result['level_status'] == 'repaired' and result['plan_level'] is not None
    verify_run(Scenario(payload), result)
    monkeypatch.setattr(Routes, 'energy_short', lambda self, uid, stops: Fraction(0))
    assert run_lr(Scenario(payload), 10)['level_status'] == 'exact_check_failed'


def test_analysis_recoverable_h3_pairing_and_interaction_tests():
    """Review (15 Oct): recoverable means a verified plan at Level 4 or below; H3 compares CMI and
    PH on the same instances; the regression tests mission x strength interactions."""
    import math
    import random
    from final_study.analysis import _certificate_vs_first_plan, _five_metrics, ordinal_regression, pooled
    instances = {'a': dict(label_lower=1, label_upper=None, label_audit=True),
                 'b': dict(label_lower=2, label_upper=None, label_audit=True),
                 'c': dict(label_lower=3, label_upper=3, label_audit=False)}
    arenas = {('fs', 10.): [dict(instance='a', plan_level=3, audit_ok=True),
                            dict(instance='b', plan_level=2, audit_ok=False),
                            dict(instance='c', plan_level=4, audit_ok=True)]}
    ref = pooled(instances, arenas)
    assert ref['a'] == dict(lower=1, upper=3, minimum=None)          # unresolved but recoverable
    assert ref['b'] == dict(lower=2, upper=None, minimum=None)       # the plan did not replay
    assert ref['c'] == dict(lower=0, upper=4, minimum=None)          # the label did not replay
    rows = [dict(instances[n], ref_lower=ref[n]['lower'], ref_upper=ref[n]['upper'], ref_min=ref[n]['minimum'],
                 label_plan_level=None, label_certificate_cpu=None) for n in 'abc']
    assert _five_metrics(rows)['recovery_recoverable'] == 0          # a and c are recoverable, no label plan

    cmi = [dict(instance=f'i{j}', mission=f'm{j}', certified=j % 4 != 0, certificate_cpu=2. if j % 2 else 1.)
           for j in range(40)]
    ph = [dict(instance=f'i{j}', first_plan_cpu=None if j % 5 == 0 else 1.) for j in range(40)]
    h3 = _certificate_vs_first_plan(cmi, ph)
    paired = [j for j in range(40) if j % 4 and j % 5]
    assert h3['n'] == len(paired) and h3['instances'] == 40
    assert h3['cmi_uncertified'] == 10 and h3['ph_no_plan'] == 8
    assert h3['point'] == 2. and h3['lo'] is not None

    rng = random.Random(3)
    data = []
    for mission in range(300):
        m = ('4', '6', '8')[mission % 3]
        for strength in ('2/5', '3/5', '4/5'):
            eta = 1.5*(m == '8' and strength == '4/5')+.5*(strength != '2/5')
            u = rng.random()
            y = sum(u > 1/(1+math.exp(-(c-eta))) for c in (-1., 0., 1., 2., 3.))
            data.append(dict(mission=mission, m=m, strength=strength, y_lower=y, y_upper=y))
    factors = [('m', ['4', '6', '8']), ('strength', ['2/5', '3/5', '4/5'])]
    reference = dict(m='4', strength='2/5')
    main = ordinal_regression(data, factors, reference)
    assert [c['factor'] for c in main['coefficients']] == ['m', 'm', 'strength', 'strength']
    inter = ordinal_regression(data, factors, reference, interactions=[('m', 'strength')])
    # With the exact gradient both fits converge (19 Oct: with finite differences BFGS stopped at the
    # optimum on a precision-loss warning and the report said "converged: False").
    assert main['converged'] and inter['converged'] and max(main['max_gradient'], inter['max_gradient']) < 1e-4
    (test,) = inter['interaction_tests']
    assert test['df'] == 4 and test['p'] < .01
    assert any(c['factor'] == 'm x strength' and c['level'] == '8 x 4/5' and c['coef'] > .5
               for c in inter['coefficients'])


def test_level4_chain_construction_gives_a_certified_level4_draw(tmp_path):
    """Review (15 Oct): the chain construction (exploration seed 77921, not a study seed) builds a
    Level-4 witness, passes the screen, and the certified minimum is 4: a Level-4 plan replays and
    every Level-3 patch is excluded. Pooling (16 Oct): the draw keeps its witness, the LS stage
    checks it next to the label, and a label that only excludes Levels 0-3 pools to minimum 4."""
    from final_study.arena import replay_saved
    from final_study.level4 import pool
    from final_study.levelsuite import draw_id, label_class
    from final_study.stages import _ls_draw
    from final_study.store import Store
    from recovery.local_search import bounds
    config = dict(ls=dict(seed=77921), fs=dict(sigma=None, beta=None, rule='D1p'), label_budget_s=60, settings={})
    store = Store(tmp_path/'run', config)
    name = draw_id('4', 6, 15)
    _ls_draw(str(store.path), config, ('4', 6, 15, name))
    item, label = store.load('ls', 'draws', name), store.load('ls', 'labels', name)
    payload, ledger = item['payload'], item['ledger']
    assert ledger['status'] == 'admitted' and ledger['recipe'] == 'chain'
    # Level-4 draws use the generator's largest depot stock, 1.5 x total demand (17 Oct; t = 0 here).
    demand = sum(Fraction(str(t['demand'])) for t in payload['mission']['tasks'])
    assert ledger['time'] == '0' and Fraction(str(payload['state']['depot_stock'])) == demand*Fraction(3, 2)
    construction = ledger['construction']
    assert construction['witness_level'] == 4 and len(construction['helpers']) == 2
    assert set(construction['helpers']).isdisjoint(ledger['affected'])
    assert label['result']['bounds']['minimum'] == 4 and label['result']['bounds']['excluded_levels'] == [0, 1, 2, 3]
    assert replay_saved(payload, label, store.load_proofs(label))['CMI']['ok']
    assert label['pooled']['witness_ok'] and label['pooled']['bounds'] == label['result']['bounds']
    # A label that excludes Levels 0-3 without finding a plan pools to minimum 4 with the witness.
    open_label = dict(result=dict(bounds=bounds({0, 1, 2, 3}, None)), audit=dict(ok=True))
    pooled = pool(payload, open_label, construction['witness'])
    assert pooled['witness_ok'] and pooled['witness_level'] == 4 and pooled['bounds']['minimum'] == 4
    assert label_class(open_label) is None and label_class(dict(open_label, pooled=pooled)) == '4'
    # Without its exclusions the witness only bounds from above; a tampered witness adds nothing.
    assert pool(payload, dict(open_label, audit=dict(ok=False)), construction['witness'])['bounds']['minimum'] is None
    bad = json.loads(json.dumps(construction['witness']))
    bad['values'][0] = '1000'
    assert pool(payload, open_label, bad) == dict(witness_ok=False, witness_level=None,
                                                  bounds=open_label['result']['bounds'])


def test_level4_deficit_draw_uses_a_two_by_two_block_and_a_level4_witness():
    """Deficit recipe (16 Oct): the update covers a 2 x 2 block of cells with one wind blowing
    toward the depot; the construction moves one task from each of two affected UAVs to two
    different helpers. (At 600 s this draw certifies minimum 4; too slow for a test.)"""
    payload, ledger = ls_draw('4', 8, 26, base_seed=77941, screen_seconds=5)
    assert ledger['status'] == 'admitted' and ledger['recipe'] == 'deficit'
    assert len(ledger['cell']) == 4 and len(payload['wind']['update_support']) == 4
    construction = ledger['construction']
    assert construction['witness_level'] == 4 and len(set(construction['helpers'])) == 2
    assert set(construction['helpers']).isdisjoint(ledger['affected'])
    winds = {tuple(payload['wind']['received']['values'][i][0]) for i, c in enumerate(payload['wind']['cells'])
             if c['id'] in ledger['cell']}
    assert len(winds) == 1


def test_path_through_a_cell_corner_is_evaluated():
    """Level-4 pilot (16 Oct): a leg through the corner (-0.5, -0.5) of four cells split into an
    empty piece and the route evaluator divided by its zero length."""
    import math
    import random
    from escalation_study.missions import _geometry
    from env.route_evaluator import evaluate_path
    scenario = Scenario(_geometry(12, 4, 'uniform', 5, random.Random(1)))
    straight = evaluate_path(scenario, 'U1', [[-0.6, -0.3], [-0.3, -0.9]], 0, 0, 'previous')
    assert straight.status == 'complete'
    assert abs(sum(s.distance_km for s in straight.slices) - math.dist((-0.6, -0.3), (-0.3, -0.9))) < 1e-9


def test_tightening_excludes_the_lower_level_plan_and_keeps_the_witness():
    """Level-4 tightening (16 Oct): a task the lower-level plan P delivers later than the
    witness W gets W's time as deadline (never below the previous plan's time); tasks where P
    is not later, or where the floor would not exclude P, keep their deadlines."""
    from fractions import Fraction as F
    from final_study.level4 import MARGIN, tighten
    payload = dict(mission=dict(tasks=[dict(id='A', deadline_h=2.0), dict(id='B', deadline_h=2.0),
                                       dict(id='C', deadline_h=2.0), dict(id='D', deadline_h=None)]))
    w = dict(A=F(1), B=F(3, 2), C=F(1), D=F(1))
    p = dict(A=F(3, 2), B=F(1), C=F(6, 5), D=F(3, 2))
    floor = dict(A=F(1, 2), B=F(1, 2), C=F(5, 4), D=F(0))
    assert tighten(payload, w, p, floor) == dict(A=F(1)+MARGIN)
    assert tighten(payload, w, dict(B=F(1)), floor) == {}
    # A plan within the separation of the witness is not excluded; nor is a deadline already
    # at the witness's time lowered again (the loop that bound 24 rounds before this check).
    assert tighten(payload, w, dict(A=F(1)+MARGIN+F(1, 10**7)), floor) == {}
    payload['mission']['tasks'][0]['deadline_h'] = float(F(1)+MARGIN)
    assert tighten(payload, w, p, floor) == {}


def test_level4_battery_estimate_trouble_and_recharge():
    """Battery in the Level-4 constructions (16 Oct), on a hand-built UAV flying 1 h legs on a
    line: a UAV in the air carries all it has on board until the depot; a task it can no longer
    reach on its battery is in trouble although it is not late; a recharge stop is added to a
    remaining route when that brings it within battery."""
    from fractions import Fraction as F
    from types import SimpleNamespace
    from final_study.level4 import _energy_short, _troubled, _within_battery

    def model(origin, onboard, battery):
        return SimpleNamespace(
            origin=origin, onboard=F(onboard), capacity=F(3), required=dict(A=F(1), B=F(1)), cap=F(battery),
            budget=lambda nonempty: F(battery)-1, coef_v=F(1), empty=F(1), mass=F(1), reserve_wh=F(1),
            service_energy=F(0), start=(0, 0), depot=(0, 0), position=dict(A=(1, 0), B=(2, 0)),
            departure=lambda nonempty: F(0), preparation=F(0), service=F(0), first=None,
            deadline=dict(A=F(100), B=F(100)))

    class R:
        def __init__(self, m):
            self.models, self.improved, self.cache, self.committed_a = dict(U=m), set(), {}, set()
            self.table = SimpleNamespace(improve=lambda *args: False)

        def time(self, uid, a, b):
            return F(abs(a[0]-b[0])+abs(a[1]-b[1]))

        def full(self, uid, stops):
            return list(stops)+['DEPOT']
    # 9 Wh: a ground start loads the 2 units it needs and fits; in the air the same UAV carries
    # 3 units until the depot and runs short before it is home.
    ground, air = R(model(True, 0, 9)), R(model(False, 3, 9))
    assert _energy_short(ground, 'U', ['A', 'B']) == 0
    assert _energy_short(air, 'U', ['A', 'B']) > 0
    # 7 Wh: A and the way home fit; B does not: B is in trouble, A is not (neither is late).
    short = R(model(True, 0, 7))
    previous = dict(A=F(100), B=F(100))
    assert _troubled(short, dict(U=['A', 'B']), 'U', previous) == ['B']
    assert _within_battery(short, 'U', ['A', 'B']) == ['A', 'DEPOT', 'B']
    assert _within_battery(R(model(True, 0, 4)), 'U', ['A', 'B']) is None


def test_level4_in_flight_deadline_rises_until_the_previous_plan_stays_feasible():
    """In flight (17 Oct): the previous-plan check, made from the snapshot state, can need a
    little more time than the take-off floor gives a constructed deadline; the deadline rises
    in small steps until the check accepts it (exploration seed 77981, t = 1/4)."""
    payload, ledger = ls_draw('4', 8, 16, base_seed=77981, screen_seconds=5, tighten_rounds=0)
    construction = ledger['construction']
    assert ledger['time'] == '1/4' and construction['witness_level'] == 4
    assert construction['premise_lifts'] >= 1


def test_report_runs_on_an_empty_run(tmp_path):
    """Regression (17 Oct): a list in write_report named like the module's ``pooled`` function
    made Python treat ``pooled`` as a local throughout, and the report stage failed at once."""
    from final_study.analysis import write_report
    from final_study.store import Store
    config = dict(label_budget_s=60, arena=dict(budget_short=10, budget_long=60), settings={})
    store = Store(tmp_path/'run', config)
    summary = write_report(store, config)
    assert (store.path/'analysis'/'REPORT.md').exists() and summary['audit']['failed'] == 0
