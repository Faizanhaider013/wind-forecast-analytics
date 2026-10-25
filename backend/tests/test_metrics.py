"""Error-metric calculations, including WMAPE zero-denominator handling."""

from __future__ import annotations

import math

from app import analytics


def test_metrics_against_hand_computed_values():
    # forecast, actual pairs; errors = forecast - actual
    pairs = [(12.0, 10.0), (8.0, 10.0), (15.0, 10.0)]  # errors: +2, -2, +5
    m = analytics.compute_metrics(pairs)
    assert m["n"] == 3
    assert m["mae_mw"] == round((2 + 2 + 5) / 3, 3)
    assert m["rmse_mw"] == round(math.sqrt((4 + 4 + 25) / 3), 3)
    assert m["bias_mw"] == round((2 - 2 + 5) / 3, 3)  # +1.667, positive => overpredict
    # WMAPE = sum|e| / sum(actual) = 9 / 30
    assert m["wmape_fraction"] == round(9 / 30, 5)
    assert m["wmape_percent"] == round(30.0, 3)
    assert m["note"] is None


def test_bias_sign_convention_overprediction_is_positive():
    m = analytics.compute_metrics([(100.0, 60.0)])  # forecast high
    assert m["bias_mw"] > 0


def test_wmape_zero_denominator_is_safe():
    # All actuals zero -> WMAPE undefined, reported None with a note.
    m = analytics.compute_metrics([(5.0, 0.0), (3.0, 0.0)])
    assert m["wmape_fraction"] is None
    assert m["wmape_percent"] is None
    assert "zero" in m["note"].lower()
    # Other metrics are still defined.
    assert m["mae_mw"] == 4.0
    assert m["bias_mw"] == 4.0


def test_empty_pairs_returns_nulls():
    m = analytics.compute_metrics([])
    assert m["n"] == 0
    assert m["mae_mw"] is None
    assert m["rmse_mw"] is None
    assert m["wmape_fraction"] is None


def test_persistence_skill_is_paired_on_the_same_sample():
    # Persistence errors |400-300|,|500-300| -> MAE 150.
    persistence_pairs = [(400.0, 300.0), (500.0, 300.0)]
    # Model errors on the SAME two hours |350-300|,|250-300| -> MAE 50.
    model_subset = [(350.0, 300.0), (250.0, 300.0)]
    pb = analytics.persistence_benchmark(persistence_pairs, model_subset)
    assert pb["n"] == 2
    assert pb["mae_mw"] == 150.0
    assert pb["model_mae_mw_same_sample"] == 50.0
    # Skill = 1 - model_MAE/persistence_MAE on the common sample = 1 - 50/150.
    assert pb["skill_mae_percent"] == round((1 - 50 / 150) * 100, 3)
    assert pb["included"] is True


def test_persistence_benchmark_empty_has_no_skill():
    pb = analytics.persistence_benchmark([], [])
    assert pb["included"] is False
    assert pb["skill_mae_percent"] is None
    assert pb["model_mae_mw_same_sample"] is None
    assert "omitted" in pb["note"]


def test_persistence_skill_is_none_when_persistence_is_perfect():
    # Persistence predicted both hours exactly -> persistence MAE = 0. Skill is
    # 1 - model/0, which is undefined; the divide guard must return None rather
    # than raise ZeroDivisionError. The benchmark is still included (n > 0).
    persistence_pairs = [(300.0, 300.0), (500.0, 500.0)]  # zero error -> MAE 0
    model_subset = [(350.0, 300.0), (450.0, 500.0)]       # model MAE 50
    pb = analytics.persistence_benchmark(persistence_pairs, model_subset)
    assert pb["included"] is True
    assert pb["n"] == 2
    assert pb["mae_mw"] == 0.0
    assert pb["model_mae_mw_same_sample"] == 50.0
    assert pb["skill_mae_percent"] is None  # guarded, not a crash
