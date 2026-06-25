from app.algorithms import HyperLogLog


def test_estimate_within_error_bound():
    hll = HyperLogLog(precision=14)
    n = 100_000
    for i in range(n):
        hll.add(f"item-{i}")
    est = hll.count()
    rel_err = abs(est - n) / n
    # Theoretical ~0.81% std error for p=14; allow a comfortable margin.
    assert rel_err < 0.03, f"estimate={est:.0f} rel_err={rel_err:.4f}"


def test_duplicates_do_not_inflate():
    hll = HyperLogLog(precision=12)
    for _ in range(10_000):
        hll.add("same-key")
    assert len(hll) <= 3  # essentially 1 distinct item


def test_small_cardinality_is_exactish():
    hll = HyperLogLog(precision=14)
    for i in range(50):
        hll.add(i)
    assert abs(len(hll) - 50) <= 3


def test_merge_is_union():
    a = HyperLogLog(precision=12)
    b = HyperLogLog(precision=12)
    for i in range(0, 20_000):
        a.add(i)
    for i in range(10_000, 30_000):  # 10k overlap -> union is 30k
        b.add(i)
    merged = a.merge(b)
    rel_err = abs(merged.count() - 30_000) / 30_000
    assert rel_err < 0.04
