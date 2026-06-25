"""Isolation Forest: unsupervised anomaly scoring by random partitioning.

Isolation Forest exploits a simple observation: anomalies are *few and
different*, so a random partitioning of the feature space isolates them in far
fewer splits than it takes to isolate a normal point buried inside a dense
cluster.  We build an ensemble of random binary trees (iTrees); each tree picks a
random feature and a random split value between that feature's min and max, and
recurses.  The depth at which a point becomes isolated is its *path length*.

Short average path length across the forest -> easy to isolate -> anomalous.
The path length is normalised by ``c(n)``, the expected path length of an
unsuccessful binary-search-tree lookup (the same quantity arises in BST
analysis), and mapped to a score in (0, 1):

    s(x) = 2 ** ( -E[h(x)] / c(n) )

Scores above ~0.6 indicate anomalies; ~0.5 and below are normal.  Each tree is
grown on a small subsample (default 256) which both bounds depth and, perhaps
counter-intuitively, sharpens anomaly contrast.

Implemented from scratch (no scikit-learn) to keep the data-structures explicit.

Complexity:
    fit()    O(n_trees * psi * log psi)   psi = subsample size
    score()  O(n_trees * log psi)
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Sequence

EULER_MASCHERONI = 0.5772156649015329


def _expected_path_length(n: int) -> float:
    """c(n): average path length of an unsuccessful search in a BST of n nodes."""
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    return 2.0 * (math.log(n - 1) + EULER_MASCHERONI) - (2.0 * (n - 1) / n)


class _Node:
    __slots__ = ("feature", "split", "left", "right", "size", "is_leaf")

    def __init__(self) -> None:
        self.feature: int = -1
        self.split: float = 0.0
        self.left: Optional["_Node"] = None
        self.right: Optional["_Node"] = None
        self.size: int = 0
        self.is_leaf: bool = False


class _IsolationTree:
    def __init__(self, max_depth: int, rng: random.Random) -> None:
        self.max_depth = max_depth
        self.rng = rng
        self.root: Optional[_Node] = None

    def fit(self, data: Sequence[Sequence[float]]) -> "_IsolationTree":
        self.root = self._grow(list(data), 0)
        return self

    def _grow(self, data: List[Sequence[float]], depth: int) -> _Node:
        node = _Node()
        n = len(data)
        if depth >= self.max_depth or n <= 1:
            node.is_leaf = True
            node.size = n
            return node

        n_features = len(data[0])
        feature = self.rng.randrange(n_features)
        column = [row[feature] for row in data]
        lo, hi = min(column), max(column)
        if lo == hi:  # nothing to split on
            node.is_leaf = True
            node.size = n
            return node

        split = self.rng.uniform(lo, hi)
        left = [row for row in data if row[feature] < split]
        right = [row for row in data if row[feature] >= split]
        node.feature = feature
        node.split = split
        node.left = self._grow(left, depth + 1)
        node.right = self._grow(right, depth + 1)
        return node

    def path_length(self, x: Sequence[float]) -> float:
        node = self.root
        depth = 0
        while node is not None and not node.is_leaf:
            if x[node.feature] < node.split:
                node = node.left
            else:
                node = node.right
            depth += 1
        # Add the expected remaining depth for the points that ended up together.
        return depth + _expected_path_length(node.size if node else 0)


class IsolationForest:
    def __init__(
        self,
        n_trees: int = 100,
        sample_size: int = 256,
        random_state: Optional[int] = None,
    ) -> None:
        self.n_trees = n_trees
        self.sample_size = sample_size
        self.rng = random.Random(random_state)
        self.trees: List[_IsolationTree] = []
        self._c = 1.0
        self._fitted = False

    def fit(self, data: Sequence[Sequence[float]]) -> "IsolationForest":
        data = [list(row) for row in data]
        if not data:
            raise ValueError("cannot fit on empty data")
        psi = min(self.sample_size, len(data))
        # Trees only need to be as deep as it takes to isolate psi points.
        max_depth = max(1, math.ceil(math.log2(max(2, psi))))
        self.trees = []
        for _ in range(self.n_trees):
            if len(data) > psi:
                sample = self.rng.sample(data, psi)
            else:
                sample = data
            self.trees.append(_IsolationTree(max_depth, self.rng).fit(sample))
        self._c = _expected_path_length(psi)
        self._fitted = True
        return self

    def anomaly_score(self, x: Sequence[float]) -> float:
        """Score a single point in (0, 1); higher means more anomalous."""
        if not self._fitted or not self.trees:
            return 0.0
        avg = sum(t.path_length(x) for t in self.trees) / len(self.trees)
        if self._c <= 0:
            return 0.0
        return 2.0 ** (-avg / self._c)

    def score_samples(self, data: Sequence[Sequence[float]]) -> List[float]:
        return [self.anomaly_score(x) for x in data]

    def predict(self, x: Sequence[float], threshold: float = 0.6) -> bool:
        """True if ``x`` is judged anomalous at the given score threshold."""
        return self.anomaly_score(x) >= threshold
