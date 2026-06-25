import random

import pytest

from app.algorithms import TDigest


def _abs_quantile(sorted_vals, q):
    idx = min(len(sorted_vals) - 1, int(q * len(sorted_vals)))
    return sorted_vals[idx]


def test_uniform_quantiles_are_accurate():
    rng = random.Random(42)
    data = [rng.uniform(0, 1000) for _ in range(50_000)]
    td = TDigest(compression=200)
    td.batch_update(data)

    ordered = sorted(data)
    for q in (0.01, 0.25, 0.5, 0.75, 0.95, 0.99):
        est = td.quantile(q)
        true = _abs_quantile(ordered, q)
        # Generous absolute tolerance relative to the 0-1000 range.
        assert abs(est - true) < 25, f"q={q}: est={est:.2f} true={true:.2f}"


def test_memory_is_bounded():
    td = TDigest(compression=100)
    td.batch_update(range(100_000))
    # Centroid count stays bounded regardless of stream length.
    assert td.num_centroids <= 250
    assert len(td) == 100_000


def test_tail_percentiles_track_extremes():
    td = TDigest(compression=200)
    td.batch_update([1.0] * 9_900)
    td.batch_update([1000.0] * 100)  # 1% extreme tail
    assert td.percentile(50) == pytest.approx(1.0, abs=1.0)
    assert td.quantile(0.999) > 500


def test_single_value():
    td = TDigest()
    td.add(7.0)
    assert td.quantile(0.5) == pytest.approx(7.0)


def test_nan_and_inf_ignored():
    td = TDigest()
    td.batch_update([1.0, 2.0, 3.0])
    td.add(float("nan"))
    td.add(float("inf"))
    assert len(td) == 3
