"""Unit tests for mathematical recommendation quality metrics and catalog dispersion.

Asserts exact numerical values down to 4 decimal places for manually verified toy fixtures,
edge cases (empty sets, truncated lists, ties), and Gini coefficient boundary distributions.
"""

import pytest

from src.services.evaluation.metrics import (
    compute_bounded_recall_at_k,
    compute_catalog_coverage_at_k,
    compute_dcg_at_k,
    compute_gini_coefficient,
    compute_idcg_at_k,
    compute_ndcg_at_k,
    compute_precision_at_k,
    compute_recall_at_k,
)


def test_toy_ranking_example_at_k3():
    """Verify toy example at K=3 with exact hand-calculated metrics.

    Recommended: [c1, c2, c3]
    Relevant in window: c1 (grade 2), c3 (grade 1), c5 (grade 3) -> |Relevant| = 3
    Hits: {c1, c3} -> count = 2
    """
    recommended = ["c1", "c2", "c3"]
    relevant = {"c1", "c3", "c5"}
    relevance_grades = {"c1": 2, "c3": 1, "c5": 3}

    # 1. Precision@3 (fixed-K denominator = 3) -> 2 / 3 = 0.6667
    p = compute_precision_at_k(recommended, relevant, k=3)
    assert round(p, 4) == 0.6667

    # 2. Standard Recall@3 (denominator = |relevant| = 3) -> 2 / 3 = 0.6667
    r = compute_recall_at_k(recommended, relevant, k=3)
    assert r is not None
    assert round(r, 4) == 0.6667

    # 3. Bounded Recall@3 (denominator = min(3, 3) = 3) -> 2 / 3 = 0.6667
    br = compute_bounded_recall_at_k(recommended, relevant, k=3)
    assert br is not None
    assert round(br, 4) == 0.6667

    # 4. DCG@3: rank 1 (rel=2) -> 3.0, rank 2 (rel=0) -> 0.0, rank 3 (rel=1) -> 0.5 = 3.5000
    dcg = compute_dcg_at_k(recommended, relevance_grades, k=3)
    assert round(dcg, 4) == 3.5000

    # 5. IDCG@3: sorted grades [3, 2, 1] -> rank 1: 7.0, rank 2: 3/log2(3)=1.8928, rank 3: 0.5 = 9.3928
    idcg = compute_idcg_at_k(relevance_grades, k=3)
    assert round(idcg, 4) == 9.3928

    # 6. NDCG@3: 3.5000 / 9.392789 = 0.3726
    ndcg = compute_ndcg_at_k(recommended, relevance_grades, k=3)
    assert ndcg is not None
    assert round(ndcg, 4) == 0.3726


def test_incomplete_recommendation_list():
    """Verify that a list with m < K has its Precision penalised by fixed-K denominator."""
    # Engine only returned 2 items (c1, c4) due to prerequisite filtering
    recommended = ["c1", "c4"]
    relevant = {"c1"}
    relevance_grades = {"c1": 1}

    # Precision@3 has denominator 3: 1 / 3 = 0.3333
    p = compute_precision_at_k(recommended, relevant, k=3)
    assert round(p, 4) == 0.3333

    # Standard Recall@3: 1 / 1 = 1.0000
    r = compute_recall_at_k(recommended, relevant, k=3)
    assert r == 1.0000

    # Bounded Recall@3: 1 / min(3, 1) = 1.0000
    br = compute_bounded_recall_at_k(recommended, relevant, k=3)
    assert br == 1.0000

    # NDCG@3: DCG=1.0, IDCG=1.0 -> NDCG = 1.0000
    ndcg = compute_ndcg_at_k(recommended, relevance_grades, k=3)
    assert ndcg == 1.0000


def test_empty_predictions():
    """Verify edge case where recommendation engine returns an empty list."""
    recommended = []
    relevant = {"c1", "c2"}
    relevance_grades = {"c1": 2, "c2": 1}

    p = compute_precision_at_k(recommended, relevant, k=3)
    assert p == 0.0

    r = compute_recall_at_k(recommended, relevant, k=3)
    assert r == 0.0

    br = compute_bounded_recall_at_k(recommended, relevant, k=3)
    assert br == 0.0

    ndcg = compute_ndcg_at_k(recommended, relevance_grades, k=3)
    assert ndcg == 0.0


def test_empty_ground_truth():
    """Verify edge case where learner has no relevant outcomes in window."""
    recommended = ["c1", "c2", "c3"]
    relevant = set()
    relevance_grades = {}

    p = compute_precision_at_k(recommended, relevant, k=3)
    assert p == 0.0

    # Recall and NDCG return None when ground truth is empty (excluded from average)
    assert compute_recall_at_k(recommended, relevant, k=3) is None
    assert compute_bounded_recall_at_k(recommended, relevant, k=3) is None
    assert compute_ndcg_at_k(recommended, relevance_grades, k=3) is None


def test_catalog_coverage_and_gini():
    """Verify catalog coverage and Gini coefficient with active zero-frequency items."""
    active_catalog = {"c1", "c2", "c3", "c4", "c5"}
    learner_recs = [
        ["c1", "c2"],
        ["c1", "c3"],
    ]
    # Coverage: {c1, c2, c3} out of 5 items = 3 / 5 = 0.6000
    cov = compute_catalog_coverage_at_k(learner_recs, active_catalog, k=2)
    assert round(cov, 4) == 0.6000

    # Frequencies: c1: 2, c2: 1, c3: 1, c4: 0, c5: 0
    freqs = {"c1": 2, "c2": 1, "c3": 1}
    # Sorted frequencies: [0, 0, 1, 1, 2], N=5, sum=4 -> Numerator = 10, Denom = 20 -> Gini = 0.5000
    gini = compute_gini_coefficient(freqs, active_catalog)
    assert round(gini, 4) == 0.5000


def test_gini_boundary_conditions():
    """Verify Gini on perfect equality, complete monopoly, and empty recommendations."""
    # 1. Perfect equality: 4 items each recommended 5 times
    active_4 = {"c1", "c2", "c3", "c4"}
    equal_freqs = {"c1": 5, "c2": 5, "c3": 5, "c4": 5}
    assert compute_gini_coefficient(equal_freqs, active_4) == 0.0000

    # 2. Complete monopoly: 4 items, 1 item gets all 10 recommendations
    monopoly_freqs = {"c4": 10}
    # Formula gives (1 - 1/N) = 1 - 0.25 = 0.7500
    assert compute_gini_coefficient(monopoly_freqs, active_4) == 0.7500

    # 3. Empty recommendations
    empty_freqs = {}
    assert compute_gini_coefficient(empty_freqs, active_4) == 0.0000

    # 4. Single item catalog
    single_catalog = {"c1"}
    assert compute_gini_coefficient({"c1": 10}, single_catalog) == 0.0000


def test_invalid_k_raises_error():
    """Verify that k <= 0 raises ValueError across metric functions."""
    with pytest.raises(ValueError):
        compute_precision_at_k(["c1"], {"c1"}, k=0)
    with pytest.raises(ValueError):
        compute_recall_at_k(["c1"], {"c1"}, k=-1)
    with pytest.raises(ValueError):
        compute_bounded_recall_at_k(["c1"], {"c1"}, k=0)
    with pytest.raises(ValueError):
        compute_dcg_at_k(["c1"], {"c1": 1}, k=0)
    with pytest.raises(ValueError):
        compute_idcg_at_k({"c1": 1}, k=-2)
