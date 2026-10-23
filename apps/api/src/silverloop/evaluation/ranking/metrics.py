"""Ranking-quality metrics over a graded top-K, plus a seeded, deterministic bootstrap.

Every metric here is a pure function of `(relevances, ...)` -- a list of the graded relevance
(`labels.grade_candidate`) of the top-K candidates, in ranked order. Nothing here knows about
`ActivityCandidate`, `ActivityIntent` or a persona; that keeps this module trivially unit-testable
against hand-computed cases, independent of the dataset in `dataset.py`.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from functools import lru_cache

RELEVANT_THRESHOLD = 3
"""What P@k and MRR count as relevant: a TASTE MATCH (grade 3), not the neutral grade 2.

This was 2, which made `P@3` a measurement of pool composition rather than of ranking: 77.8% of
the core kept pool grades >=2, and a random shuffle already scored 0.788. Grade 2 means "satisfies
the hard constraints and hits no avoid" -- true of most of the catalogue after filtering, and not
a statement that the listing suits the person.
"""

DEFAULT_K = 3


def dcg(relevances: Sequence[int]) -> float:
    """Discounted cumulative gain, standard `(2^rel - 1) / log2(rank + 1)` form -- graded, not
    binary, so a rank-1 grade-3 item counts far more than a rank-1 grade-1 item.
    """
    return sum((2**rel - 1) / math.log2(index + 2) for index, rel in enumerate(relevances))


def ndcg_at_k(relevances: Sequence[int], k: int = DEFAULT_K) -> float:
    """NDCG@k. `0.0` when every relevance in the top-k (and hence the ideal ordering) is zero --
    there is nothing to discount against, and reporting 1.0 (as a bare 0/0 could) would flatter an
    empty or entirely-irrelevant result."""
    top = list(relevances[:k])
    ideal = sorted(relevances, reverse=True)[:k]
    ideal_dcg = dcg(ideal)
    if ideal_dcg == 0:
        return 0.0
    return dcg(top) / ideal_dcg


def precision_at_k(
    relevances: Sequence[int], k: int = DEFAULT_K, threshold: int = RELEVANT_THRESHOLD
) -> float:
    top = list(relevances[:k])
    if not top:
        return 0.0
    return sum(1 for rel in top if rel >= threshold) / len(top)


def mrr(relevances: Sequence[int], threshold: int = RELEVANT_THRESHOLD) -> float:
    for index, rel in enumerate(relevances):
        if rel >= threshold:
            return 1.0 / (index + 1)
    return 0.0


def hit_rate_at_k(
    relevances: Sequence[int], k: int = DEFAULT_K, threshold: int = RELEVANT_THRESHOLD
) -> float:
    """Is there AT LEAST ONE item of at least `threshold` relevance in the top-k? 1.0 or 0.0.

    The slate question rather than the ordering one: a person is shown three cards and only needs
    one of them to be worth going to. Deliberately blind to where in the top-k it sits -- `NDCG@1`
    is the metric that asks that.
    """
    return 1.0 if any(rel >= threshold for rel in list(relevances[:k])) else 0.0


def _best_per_category(relevances: Sequence[int], categories: Sequence[str | None]) -> list[int]:
    """The relevances available under the product's own one-per-category slate rule.

    A listing with no category is never treated as "a kind" by `activity_search._diversify`
    ("absence is not a kind"), so it is not subject to the constraint here either and every such
    listing stays available.
    """
    best: dict[str, int] = {}
    uncategorised: list[int] = []
    for relevance, category in zip(relevances, categories, strict=True):
        if category is None:
            uncategorised.append(relevance)
        else:
            best[category] = max(best.get(category, relevance), relevance)
    return sorted([*best.values(), *uncategorised], reverse=True)


def slate_ndcg_at_k(
    relevances: Sequence[int], categories: Sequence[str | None], k: int = DEFAULT_K
) -> float:
    """NDCG@k whose IDEAL is computed under the product's own "no two of the top-k share a
    category" rule, capped at 1.0.

    Plain NDCG@3 structurally penalises `activity_search._diversify`: nine of fourteen personas'
    only route to a grade 3 is a CATEGORY taste, and each category has five listings, so the plain
    ideal top-3 is three sessions of one kind -- precisely the slate the product refuses to show.
    Measured against the constrained ideal, a within-margin variety swap is no longer a loss.

    The cap matters and is not a fudge: a slate can only out-score the constrained ideal by
    breaking the constraint, and a slate that breaks the product's own rule is not better than one
    that keeps it. `min(..., 1.0)` says that rather than rewarding it.
    """
    top = list(relevances[:k])
    ideal = _best_per_category(relevances, categories)[:k]
    ideal_dcg = dcg(ideal)
    if ideal_dcg == 0:
        return 0.0
    return min(1.0, dcg(top) / ideal_dcg)


def category_entropy_at_k(categories: Sequence[str | None], k: int = DEFAULT_K) -> float:
    """Shannon entropy, in bits, of the category distribution over the top-k. `None` (a listing
    with no category) is its own bucket, exactly like every other axis in this codebase treats
    genuinely missing data as an honest value rather than a null to discard.
    """
    top = list(categories[:k])
    if not top:
        return 0.0
    counts = Counter(top)
    total = len(top)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


@dataclass(frozen=True)
class Stat:
    """A macro-averaged metric, plus a seeded, deterministic 95% bootstrap CI over the per-case
    values it was averaged from.

    `n_clusters` is `0` for a per-case (i.i.d.) bootstrap and the number of resampled clusters --
    personas, or unordered persona pairs -- for a clustered one. It is printed beside `n`
    everywhere, because the two answer different questions: `n` is how many numbers were averaged,
    `n_clusters` is how many *independent* things they came from.
    """

    mean: float
    ci_low: float
    ci_high: float
    n: int
    n_clusters: int = 0


@lru_cache(maxsize=64)
def _resample_indices(n: int, seed: int, resamples: int) -> tuple[tuple[int, ...], ...]:
    """The seeded index draws behind one bootstrap, memoised on `(n, seed, resamples)`.

    Callers that pass the SAME seed share the same draws -- common random numbers, which is both
    cheaper (the artifact runs hundreds of bootstraps over the same case list) and slightly better
    behaved: two arms measured against the same resamples differ only by the arm, not by the luck
    of two independent draw sequences. Plain `random.Random`, never `numpy`: the artifact is
    committed and re-checked byte-for-byte in CI, so every float must come from a summation order
    that is identical on every machine.
    """
    rng = random.Random(seed)
    return tuple(tuple(rng.randrange(n) for _ in range(n)) for _ in range(resamples))


def _percentile_ci(resample_means: list[float], resamples: int) -> tuple[float, float]:
    resample_means.sort()
    low_index = int(0.025 * resamples)
    high_index = min(resamples - 1, int(0.975 * resamples))
    return resample_means[low_index], resample_means[high_index]


def bootstrap_stat(values: Sequence[float], *, seed: int, resamples: int = 2000) -> Stat:
    """Percentile bootstrap over `values` (one number per replayed case), seeded so re-running the
    generator twice produces byte-identical output -- the same discipline `report.py`'s digest
    provenance already relies on for the policy-comparison artifact.

    Cases are resampled i.i.d., which is only the right unit when the cases ARE independent. Six
    cases that share one persona's trace, preference store and grade table are not, and this CI is
    ~2.2x too narrow on them; use `cluster_bootstrap_stat` for those and report the two side by
    side.
    """
    values = list(values)
    n = len(values)
    if n == 0:
        return Stat(mean=0.0, ci_low=0.0, ci_high=0.0, n=0)
    mean = sum(values) / n
    if n == 1:
        return Stat(mean=mean, ci_low=mean, ci_high=mean, n=1)
    resample_means = [
        sum(values[index] for index in draw) / n for draw in _resample_indices(n, seed, resamples)
    ]
    ci_low, ci_high = _percentile_ci(resample_means, resamples)
    return Stat(mean=round(mean, 4), ci_low=round(ci_low, 4), ci_high=round(ci_high, 4), n=n)


def cluster_bootstrap_stat(
    values: Sequence[float],
    clusters: Sequence[Hashable],
    *,
    seed: int,
    resamples: int = 2000,
) -> Stat:
    """Percentile bootstrap that resamples CLUSTERS with replacement, not cases.

    Draw `k` clusters with replacement from the `k` observed ones, concatenate the drawn clusters'
    values, take the mean of the concatenation. This is the right sampling unit whenever the cases
    inside a cluster share the thing that generated them -- one persona's trace, preference store
    and grade table produce all six of her cases, so resampling cases pretends to six times the
    evidence the benchmark actually has.

    A single cluster carries no between-cluster information at all, so the CI collapses onto the
    point estimate rather than pretending to a width it cannot support -- the same honesty
    `Rate.rate` applies to a zero denominator.
    """
    values = list(values)
    cluster_keys = list(clusters)
    if len(values) != len(cluster_keys):
        raise ValueError("cluster_bootstrap_stat requires equal-length, index-aligned sequences")
    n = len(values)
    if n == 0:
        return Stat(mean=0.0, ci_low=0.0, ci_high=0.0, n=0, n_clusters=0)
    mean = round(sum(values) / n, 4)

    grouped: dict[Hashable, list[float]] = {}
    for value, key in zip(values, cluster_keys, strict=True):
        grouped.setdefault(key, []).append(value)
    k = len(grouped)
    if k <= 1:
        return Stat(mean=mean, ci_low=mean, ci_high=mean, n=n, n_clusters=k)

    sums = [sum(group) for group in grouped.values()]
    counts = [len(group) for group in grouped.values()]
    resample_means = []
    for draw in _resample_indices(k, seed, resamples):
        total = 0.0
        drawn = 0
        for index in draw:
            total += sums[index]
            drawn += counts[index]
        resample_means.append(total / drawn)
    ci_low, ci_high = _percentile_ci(resample_means, resamples)
    return Stat(mean=mean, ci_low=round(ci_low, 4), ci_high=round(ci_high, 4), n=n, n_clusters=k)


@dataclass(frozen=True)
class Delta:
    """An arm comparison's effect on one metric: the paired difference (arm - baseline),
    bootstrapped over the SAME case indices for both arms so the CI reflects the paired design
    rather than treating the two arms as independent samples.
    """

    mean: float
    ci_low: float
    ci_high: float
    exercised: bool
    """False when every paired difference is exactly zero -- the dataset does not exercise this
    factor for this metric. Printed as prose rather than a numeric 0.0 +/- 0.0, which would read as
    "measured no effect" rather than "never had a chance to show one"."""
    n: int = 0
    n_clusters: int = 0
    """`0` for a per-case paired bootstrap; the cluster count for a clustered one (see `Stat`)."""

    @property
    def excludes_zero(self) -> bool:
        return self.ci_low > 0.0 or self.ci_high < 0.0


def _paired_diffs(
    baseline_values: Sequence[float], arm_values: Sequence[float], *, name: str
) -> list[float]:
    baseline = list(baseline_values)
    arm = list(arm_values)
    if len(baseline) != len(arm):
        raise ValueError(f"{name} requires equal-length, index-aligned sequences")
    return [a - b for b, a in zip(baseline, arm, strict=True)]


def paired_delta(
    full_values: Sequence[float], ablated_values: Sequence[float], *, seed: int
) -> Delta:
    diffs = _paired_diffs(full_values, ablated_values, name="paired_delta")
    exercised = any(abs(d) > 1e-9 for d in diffs)
    stat = bootstrap_stat(diffs, seed=seed)
    return Delta(
        mean=stat.mean,
        ci_low=stat.ci_low,
        ci_high=stat.ci_high,
        exercised=exercised,
        n=stat.n,
    )


def cluster_paired_delta(
    full_values: Sequence[float],
    ablated_values: Sequence[float],
    clusters: Sequence[Hashable],
    *,
    seed: int,
    resamples: int = 2000,
) -> Delta:
    """The paired difference (`ablated - full`), bootstrapped by resampling CLUSTERS.

    This is the form every arm comparison in the artifact uses. Both arms are measured on the same
    cases, with the same grade table and the same kept pool, so the difference is paired; and the
    cases inside one persona are not independent, so the personas -- not the cases -- are what gets
    resampled. Comparing two marginal CIs instead is the wrong test and systematically understates
    a real difference.
    """
    diffs = _paired_diffs(full_values, ablated_values, name="cluster_paired_delta")
    exercised = any(abs(d) > 1e-9 for d in diffs)
    stat = cluster_bootstrap_stat(diffs, clusters, seed=seed, resamples=resamples)
    return Delta(
        mean=stat.mean,
        ci_low=stat.ci_low,
        ci_high=stat.ci_high,
        exercised=exercised,
        n=stat.n,
        n_clusters=stat.n_clusters,
    )


@dataclass(frozen=True)
class Rate:
    numerator: int
    denominator: int

    @property
    def rate(self) -> float | None:
        if self.denominator == 0:
            return None
        return round(self.numerator / self.denominator, 4)

    def formatted(self) -> str:
        rate = self.rate
        rate_text = "n/a" if rate is None else f"{rate:.2%}"
        return f"{self.numerator}/{self.denominator} ({rate_text})"
