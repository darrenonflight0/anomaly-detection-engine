import random

from app.algorithms import CountMinSketch


def test_estimate_never_underestimates():
    cms = CountMinSketch(width=2048, depth=5)
    truth = {}
    rng = random.Random(7)
    for _ in range(50_000):
        key = f"key-{rng.randint(0, 500)}"
        cms.add(key)
        truth[key] = truth.get(key, 0) + 1
    for key, true_count in truth.items():
        assert cms.estimate(key) >= true_count


def test_error_is_bounded():
    cms = CountMinSketch.from_error(epsilon=0.001, delta=0.01)
    truth = {}
    rng = random.Random(11)
    for _ in range(100_000):
        key = rng.randint(0, 1000)
        cms.add(key)
        truth[key] = truth.get(key, 0) + 1
    overshoot = max(cms.estimate(k) - v for k, v in truth.items())
    # Additive error must stay within epsilon * N.
    assert overshoot <= 0.001 * cms.total


def test_heavy_hitters_found():
    cms = CountMinSketch(width=4096, depth=5)
    for _ in range(10_000):
        cms.add("whale")          # dominant key
    for i in range(1_000):
        cms.add(f"minnow-{i}")    # long tail
    candidates = ["whale"] + [f"minnow-{i}" for i in range(1_000)]
    hits = cms.heavy_hitters(candidates, threshold=0.5)
    assert hits and hits[0][0] == "whale"


def test_unseen_key_estimate_is_small():
    cms = CountMinSketch(width=4096, depth=5)
    for i in range(1000):
        cms.add(f"present-{i}")
    # An unseen key may collide but should read low relative to the stream.
    assert cms.estimate("definitely-absent") <= 5
