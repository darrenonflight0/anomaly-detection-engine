import random

from app.algorithms import IsolationForest


def test_outliers_score_higher_than_inliers():
    rng = random.Random(0)
    # Dense normal cluster around the origin.
    normal = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(500)]
    forest = IsolationForest(n_trees=100, sample_size=256, random_state=1)
    forest.fit(normal)

    inlier_scores = [forest.anomaly_score(p) for p in normal[:50]]
    outliers = [[8.0, 8.0], [-9.0, 7.0], [10.0, -10.0]]
    outlier_scores = [forest.anomaly_score(p) for p in outliers]

    assert min(outlier_scores) > max(inlier_scores)
    assert min(outlier_scores) > 0.6


def test_scores_in_unit_interval():
    rng = random.Random(2)
    data = [[rng.random()] for _ in range(300)]
    forest = IsolationForest(n_trees=50, sample_size=128, random_state=3).fit(data)
    for p in data:
        s = forest.anomaly_score(p)
        assert 0.0 <= s <= 1.0


def test_unfitted_forest_is_neutral():
    forest = IsolationForest()
    assert forest.anomaly_score([1.0, 2.0]) == 0.0


def test_one_dimensional_stream():
    rng = random.Random(5)
    data = [[rng.gauss(50, 2)] for _ in range(400)]
    forest = IsolationForest(n_trees=80, sample_size=200, random_state=7).fit(data)
    assert forest.predict([200.0], threshold=0.6)
    assert not forest.predict([50.0], threshold=0.6)
