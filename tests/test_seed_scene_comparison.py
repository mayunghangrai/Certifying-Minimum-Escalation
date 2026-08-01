"""Tests for the schema-honest seed-18427 scene comparison."""

from __future__ import annotations

import numpy as np

from scripts.visualize_seed_18427_comparison import (
    TRAINED_MODE,
    _parser,
    _state_at,
    _uav_positions,
)


def _state(time_h: float, x0: float, x1: float):
    return {
        "time_h": time_h,
        "uavs": [
            {"uav_id": 0, "x_km": x0, "y_km": 0.0},
            {"uav_id": 1, "x_km": x1, "y_km": 2.0},
        ],
    }


def test_uav_position_interpolation_uses_independent_training_clock():
    states = [_state(0.0, 0.0, 2.0), _state(1.0, 10.0, 4.0)]
    np.testing.assert_allclose(
        _uav_positions(states, 0.25),
        np.array([[2.5, 0.0], [2.5, 2.0]]),
    )
    left, right, weight = _state_at(states, 0.25)
    assert left["time_h"] == 0.0
    assert right["time_h"] == 1.0
    assert weight == 0.25


def test_cli_defaults_to_unguided_production_checkpoint():
    args = _parser().parse_args([])
    assert TRAINED_MODE == "graph_mappo"
    assert args.seed == 18427
    assert args.results.as_posix() == "results/gate_learning_final"
    assert args.checkpoint is None
    assert args.output.as_posix() == "results/seed_18427_scene_comparison"

