import pytest

from app.algorithms import EMA


def test_tracks_constant_signal():
    ema = EMA(span=10)
    for _ in range(100):
        ema.update(5.0)
    assert ema.value == pytest.approx(5.0, abs=1e-6)
    assert ema.std == pytest.approx(0.0, abs=1e-6)


def test_follows_level_shift():
    ema = EMA(alpha=0.3)
    for _ in range(50):
        ema.update(10.0)
    for _ in range(50):
        ema.update(20.0)
    # Should have largely caught up to the new level.
    assert ema.value == pytest.approx(20.0, abs=0.5)


def test_zscore_flags_spike():
    ema = EMA(span=20)
    for v in [10, 11, 9, 10, 12, 8, 10, 11, 9, 10] * 5:
        ema.update(v)
    # A value far outside the recent noise band is a clear anomaly.
    assert ema.is_anomaly(40, threshold=3.0)
    assert not ema.is_anomaly(11, threshold=3.0)


def test_zero_variance_history_still_catches_deviation():
    # A perfectly flat history has std 0; a real jump must not be silently lost.
    ema = EMA(span=20)
    for _ in range(50):
        ema.update(100.0)
    assert ema.std == pytest.approx(0.0)
    assert abs(ema.zscore(500.0)) >= 3.5      # big jump -> flagged
    assert ema.zscore(100.0) == pytest.approx(0.0)  # no change -> quiet


def test_span_to_alpha_conversion():
    ema = EMA(span=19)
    assert ema.alpha == pytest.approx(0.1)


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        EMA(alpha=1.5)
    with pytest.raises(ValueError):
        EMA(span=0.5)
