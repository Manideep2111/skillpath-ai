"""Unit tests for Evaluation Methodology Version 2.3 metrics and schemas.

Covers:
- Realized Precision@K (standard, short-list, and empty-list)
- Invalid K and duplicate recommendation IDs
- Observed Precision@K and Unobserved Exposure Rate@K
- Contradictory interaction sets rejection
- NDCG with external ideal relevance pool
- NDCG when IDCG is zero (preserving legacy behavior)
- Observational learning gain: exact Version 2.3 normalized gain formula
- Observational learning gain: boundary conditions, missing baselines, and error enforcement
- Cold-start conversion: optional rates, numerical zero vs undefined, and NO_COLD_START_ATTEMPTS diagnostic
- Stratified disparity: Section 3.5.2 rules (N_min=5, finite [0.0, 1.0], metadata preservation)
- Diagnostic precedence: INSUFFICIENT_EVALUATED_STRATA -> ZERO_MAX_METRIC -> DISPARITY_WARNING -> None
- Pydantic v2 evaluation schemas: ColdStartConversionSchema, ObservationalLearningGainSchema, StratifiedActivityDisparityBlock, StratifiedDisparitySchema
"""

from decimal import Decimal
import math
import pytest

from src.schemas.evaluation import (
    ColdStartConversionSchema,
    ObservationalLearningGainSchema,
    StratifiedActivityDisparityBlock,
    StratifiedDisparitySchema,
)
from src.services.evaluation.metrics import (
    compute_cold_start_conditional_conversion,
    compute_cold_start_conversion,
    compute_cold_start_overall_conversion,
    compute_idcg_from_pool_at_k,
    compute_ndcg_at_k,
    compute_ndcg_with_ideal_pool_at_k,
    compute_observational_learning_gain,
    compute_observed_precision_at_k,
    compute_realized_precision_at_k,
    compute_stratified_disparity,
    compute_unobserved_exposure_rate_at_k,
)


def test_realized_precision_standard_short_and_empty():
    """Verify Realized Precision@K on standard lists, short lists, and empty lists."""
    # 1. Standard list: m >= k
    recs_standard = ["c1", "c2", "c3"]
    relevant = {"c1", "c3"}
    p_std = compute_realized_precision_at_k(recs_standard, relevant, k=3)
    assert round(p_std, 4) == 0.6667

    # 2. Short list: m < k (2 items recommended, cutoff k=5)
    recs_short = ["c1", "c2"]
    # 1 hit out of 2 realized items -> 1/2 = 0.5000 (Standard precision would be 1/5 = 0.2000)
    p_short = compute_realized_precision_at_k(recs_short, relevant, k=5)
    assert p_short == 0.5000

    # 3. Empty list: m = 0
    p_empty = compute_realized_precision_at_k([], relevant, k=5)
    assert p_empty == 0.0


def test_realized_precision_invalid_k_and_duplicate_ids():
    """Verify validation of invalid k and duplicate recommendation IDs."""
    # Invalid K
    with pytest.raises(ValueError, match="k must be positive"):
        compute_realized_precision_at_k(["c1"], {"c1"}, k=0)

    with pytest.raises(ValueError, match="k must be positive"):
        compute_realized_precision_at_k(["c1"], {"c1"}, k=-1)

    # Duplicate IDs within top-K
    with pytest.raises(ValueError, match="duplicate IDs in top-K"):
        compute_realized_precision_at_k(["c1", "c2", "c1"], {"c1"}, k=3)

    # Duplicate IDs beyond top-K are not evaluated at rank K
    valid_p = compute_realized_precision_at_k(["c1", "c2", "c3", "c1"], {"c1"}, k=2)
    assert valid_p == 0.5000


def test_observed_precision_and_unobserved_exposure_rate():
    """Verify observed precision and unobserved exposure rate with explicit interaction sets."""
    recs = ["c1", "c2", "c3", "c4"]
    # Learner only interacted with c1 and c2; c3 and c4 were never observed
    observed = {"c1", "c2", "c99"}
    relevant = {"c1"}  # c1 was observed and relevant; c2 was observed and non-relevant

    # Observed Precision@4: among {c1, c2}, c1 is relevant -> 1/2 = 0.5000
    obs_p = compute_observed_precision_at_k(recs, relevant, observed, k=4)
    assert obs_p == 0.5000

    # Unobserved Exposure Rate@4: c3 and c4 were unobserved -> 2/4 = 0.5000
    unobs_rate = compute_unobserved_exposure_rate_at_k(recs, observed, k=4)
    assert unobs_rate == 0.5000

    # Case: Zero recommendations observed
    no_observed = {"c99"}
    obs_p_zero = compute_observed_precision_at_k(recs, set(), no_observed, k=4)
    assert obs_p_zero is None  # Undefined denominator -> None

    unobs_rate_all = compute_unobserved_exposure_rate_at_k(recs, no_observed, k=4)
    assert unobs_rate_all == 1.0000  # 100% unobserved exposure

    # Case: Empty recommendations
    assert compute_unobserved_exposure_rate_at_k([], observed, k=4) == 0.0
    assert compute_observed_precision_at_k([], relevant, observed, k=4) is None


def test_contradictory_interaction_sets_rejected():
    """Verify rejection of contradictory interaction sets."""
    recs = ["c1", "c2"]

    # Contradiction 1: relevant_items contains item not in observed_items
    with pytest.raises(ValueError, match="relevant_items contains items not in observed_items"):
        compute_observed_precision_at_k(
            recommended_items=recs,
            relevant_items={"c1", "c2"},
            observed_items={"c1"},  # c2 claimed relevant but unobserved
            k=2,
        )

    # Contradiction 2: observed_items and unobserved_items intersect
    with pytest.raises(ValueError, match="observed_items and unobserved_items intersect"):
        compute_observed_precision_at_k(
            recommended_items=recs,
            relevant_items={"c1"},
            observed_items={"c1", "c2"},
            k=2,
            unobserved_items={"c2", "c3"},  # c2 is in both!
        )

    with pytest.raises(ValueError, match="observed_items and unobserved_items intersect"):
        compute_unobserved_exposure_rate_at_k(
            recommended_items=recs,
            observed_items={"c1", "c2"},
            k=2,
            unobserved_items={"c2", "c3"},
        )


def test_ndcg_with_external_ideal_pool():
    """Verify NDCG@K using an external ideal relevance pool for IDCG."""
    recommended = ["c1", "c2", "c3"]
    # Learner's observed grades for recommended items
    observed_grades = {"c1": 2, "c2": 0, "c3": 1}

    # External ideal pool contains all positive outcomes in the 30-day evaluation window
    ideal_pool = {"c1": 2, "c3": 1, "c5": 3, "c6": 3}

    # DCG@3: rank 1 (rel=2) -> 3.0/1.0, rank 2 (rel=0) -> 0.0, rank 3 (rel=1) -> 1.0/log2(4) = 3.5000
    # IDCG@3 from ideal pool: sorted grades [3, 3, 2] -> 12.916508
    # NDCG@3 = 3.5000 / 12.916508 = 0.27097
    idcg = compute_idcg_from_pool_at_k(ideal_pool, k=3)
    assert round(idcg, 4) == 12.9165

    ndcg = compute_ndcg_with_ideal_pool_at_k(recommended, observed_grades, ideal_pool, k=3)
    assert ndcg is not None
    assert round(ndcg, 4) == 0.2710

    # Also test passing ideal pool as list of ints
    idcg_list = compute_idcg_from_pool_at_k([3, 3, 2, 1], k=3)
    assert round(idcg_list, 4) == 12.9165


def test_ndcg_when_idcg_zero_preserves_legacy_behavior():
    """Verify NDCG returns None when external pool has zero positive relevance."""
    recommended = ["c1", "c2"]
    observed_grades = {"c1": 0, "c2": 0}
    empty_pool = {}

    ndcg = compute_ndcg_with_ideal_pool_at_k(recommended, observed_grades, empty_pool, k=2)
    assert ndcg is None  # Matches legacy compute_ndcg_at_k behavior

    # Legacy compute_ndcg_at_k also returns None
    assert compute_ndcg_at_k(recommended, observed_grades, k=2) is None


def test_observational_learning_gain_version_2_3_formula():
    """Verify exact Version 2.3 learning gain calculations."""
    # 0.4000 -> 0.7000: (0.7 - 0.4) / (1.0 - 0.4) = 0.3 / 0.6 = 0.5000
    assert compute_observational_learning_gain(Decimal("0.4000"), Decimal("0.7000")) == Decimal("0.5000")

    # 0.8000 -> 0.6000: (0.6 - 0.8) / 0.8 = -0.2 / 0.8 = -0.2500
    assert compute_observational_learning_gain(Decimal("0.8000"), Decimal("0.6000")) == Decimal("-0.2500")

    # 0.0000 -> 0.6000: (0.6 - 0.0) / (1.0 - 0.0) = 0.6 / 1.0 = 0.6000
    assert compute_observational_learning_gain(Decimal("0.0000"), Decimal("0.6000")) == Decimal("0.6000")

    # 1.0000 -> 1.0000: equal pre/post returns 0.0000
    assert compute_observational_learning_gain(Decimal("1.0000"), Decimal("1.0000")) == Decimal("0.0000")

    # 1.0000 -> 0.7000: (0.7 - 1.0) / 1.0 = -0.3 / 1.0 = -0.3000
    assert compute_observational_learning_gain(Decimal("1.0000"), Decimal("0.7000")) == Decimal("-0.3000")

    # Missing baseline (pre is None) returns None
    assert compute_observational_learning_gain(None, Decimal("0.7000")) is None

    # Missing post (post is None) returns None
    assert compute_observational_learning_gain(Decimal("0.5000"), None) is None

    # Both None returns None
    assert compute_observational_learning_gain(None, None) is None


def test_observational_learning_gain_validation():
    """Verify type, finiteness, and range error enforcement for learning gain."""
    # Non-Decimal input
    with pytest.raises(TypeError, match="must be Decimal or None"):
        compute_observational_learning_gain(0.5, Decimal("0.7"))  # type: ignore

    with pytest.raises(TypeError, match="must be Decimal or None"):
        compute_observational_learning_gain(Decimal("0.5"), "0.7")  # type: ignore

    # Non-finite input
    with pytest.raises(ValueError, match="finite Decimal"):
        compute_observational_learning_gain(Decimal("NaN"), Decimal("0.7"))

    with pytest.raises(ValueError, match="finite Decimal"):
        compute_observational_learning_gain(Decimal("0.5"), Decimal("Infinity"))

    # Out of range input
    with pytest.raises(ValueError, match="in range"):
        compute_observational_learning_gain(Decimal("-0.0001"), Decimal("0.7"))

    with pytest.raises(ValueError, match="in range"):
        compute_observational_learning_gain(Decimal("0.5"), Decimal("1.0001"))


def test_cold_start_conversion_version_2_3():
    """Verify cold-start overall and conditional conversion with diagnostics."""
    # 1. Valid conversion: 10 total cold-start, 4 active, 3 converted
    overall = compute_cold_start_overall_conversion(total_cold_start=10, converted_cold_start=3)
    assert overall == 0.3000

    cond = compute_cold_start_conditional_conversion(active_cold_start=4, converted_cold_start=3)
    assert cond == 0.7500

    both_overall, both_cond, diag = compute_cold_start_conversion(10, 4, 3)
    assert both_overall == 0.3000
    assert both_cond == 0.7500
    assert diag is None

    # 2. No cold-start learners: total=0, active=0, converted=0
    assert compute_cold_start_overall_conversion(0, 0) is None
    assert compute_cold_start_conditional_conversion(0, 0) is None
    assert compute_cold_start_conversion(0, 0, 0) == (None, None, "NO_COLD_START_ATTEMPTS")

    # 3. Cold-start learners exist but zero active learners: total=10, active=0, converted=0
    assert compute_cold_start_overall_conversion(10, 0) == 0.0  # valid numerical zero
    assert compute_cold_start_conditional_conversion(0, 0) is None  # undefined
    assert compute_cold_start_conversion(10, 0, 0) == (0.0, None, "NO_COLD_START_ATTEMPTS")

    # 4. Active learners exist but zero conversions: total=10, active=4, converted=0
    assert compute_cold_start_overall_conversion(10, 0) == 0.0
    assert compute_cold_start_conditional_conversion(4, 0) == 0.0  # valid numerical zero
    assert compute_cold_start_conversion(10, 4, 0) == (0.0, 0.0, None)

    # 5. Invalid count hierarchy
    with pytest.raises(ValueError, match="negative"):
        compute_cold_start_conversion(-1, 0, 0)

    with pytest.raises(ValueError, match="cannot exceed total_cold_start"):
        compute_cold_start_conversion(total_cold_start=5, active_cold_start=6, converted_cold_start=0)

    with pytest.raises(ValueError, match="cannot exceed active_cold_start"):
        compute_cold_start_conversion(total_cold_start=10, active_cold_start=2, converted_cold_start=3)


def test_stratified_disparity_branch1_insufficient_strata():
    """Branch 1: |V| < 2 returns None for disparities with diagnostic INSUFFICIENT_EVALUATED_STRATA."""
    # Case A: Only one stratum meets count >= 5
    strata_one = {
        "active_cohort": (0.8500, 20, 25),
        "sparse_cohort": (0.6000, 4, 15),  # count < 5
    }
    disp_one = compute_stratified_disparity(strata_one)
    assert disp_one["eligible_strata"] == ["active_cohort"]
    assert disp_one["absolute_disparity"] is None
    assert disp_one["ratio_disparity"] is None
    assert disp_one["diagnostic"] == "INSUFFICIENT_EVALUATED_STRATA"
    # Metadata preserved
    assert disp_one["stratum_metrics"]["sparse_cohort"] == 0.6000
    assert disp_one["evaluated_stratum_sizes"]["sparse_cohort"] == 4
    assert disp_one["stratum_sizes"]["sparse_cohort"] == 15

    # Case B: Zero strata meet count >= 5
    strata_none = {
        "active_cohort": (0.8500, 3),
        "sparse_cohort": (0.6000, 2),
    }
    disp_none = compute_stratified_disparity(strata_none)
    assert disp_none["eligible_strata"] == []
    assert disp_none["absolute_disparity"] is None
    assert disp_none["ratio_disparity"] is None
    assert disp_none["diagnostic"] == "INSUFFICIENT_EVALUATED_STRATA"

    # Case C: One stratum has None metric
    strata_none_metric = {
        "active_cohort": (0.8000, 15),
        "sparse_cohort": (None, 12),  # None metric excluded from |V|
    }
    disp_missing = compute_stratified_disparity(strata_none_metric)
    assert disp_missing["eligible_strata"] == ["active_cohort"]
    assert disp_missing["absolute_disparity"] is None
    assert disp_missing["ratio_disparity"] is None
    assert disp_missing["diagnostic"] == "INSUFFICIENT_EVALUATED_STRATA"
    assert disp_missing["stratum_metrics"]["sparse_cohort"] is None


def test_stratified_disparity_branch2_zero_max_metric():
    """Branch 2: |V| >= 2 and max metric == 0.0 returns abs=0.0, ratio=None, ZERO_MAX_METRIC."""
    strata_all_zero = {
        "low": (0.0, 12, 15),
        "med": (0.0, 15, 20),
        "high": (0.0, 11, 14),
    }
    disp = compute_stratified_disparity(strata_all_zero)
    assert sorted(disp["eligible_strata"]) == ["high", "low", "med"]
    assert disp["max_value"] == 0.0
    assert disp["min_value"] == 0.0
    assert disp["absolute_disparity"] == 0.0
    assert disp["ratio_disparity"] is None
    assert disp["diagnostic"] == "ZERO_MAX_METRIC"
    # Metadata preserved
    assert disp["stratum_metrics"] == {"low": 0.0, "med": 0.0, "high": 0.0}
    assert disp["evaluated_stratum_sizes"] == {"low": 12, "med": 15, "high": 11}
    assert disp["stratum_sizes"] == {"low": 15, "med": 20, "high": 14}


def test_stratified_disparity_branch3_valid_zero_ratio():
    """Branch 3: |V| >= 2 and min=0, max>0 yields ratio=0.0 and DISPARITY_WARNING."""
    strata_zero_ratio = {
        "low": (0.0, 10),
        "high": (0.50, 10),
    }
    disp = compute_stratified_disparity(strata_zero_ratio)
    assert disp["absolute_disparity"] == 0.5000
    assert disp["ratio_disparity"] == 0.0000
    assert disp["diagnostic"] == "DISPARITY_WARNING"


def test_stratified_disparity_branch3_thresholds_and_precedence():
    """Branch 3: Verify thresholds (0.25 absolute, 0.80 ratio) and warnings."""
    # 1. Absolute disparity above 0.25 triggers warning
    strata_high_abs = {
        "low": (0.60, 10),
        "high": (0.86, 10),
    }
    disp_abs = compute_stratified_disparity(strata_high_abs)
    assert disp_abs["absolute_disparity"] == 0.2600
    assert disp_abs["diagnostic"] == "DISPARITY_WARNING"

    # 2. Ratio disparity below 0.80 triggers warning
    strata_low_ratio = {
        "low": (0.70, 10),
        "high": (0.90, 10),
    }
    disp_ratio = compute_stratified_disparity(strata_low_ratio)
    assert disp_ratio["ratio_disparity"] == 0.7778
    assert disp_ratio["diagnostic"] == "DISPARITY_WARNING"

    # 3. Exact ratio threshold 0.80 (abs <= 0.25 and ratio == 0.80 -> None)
    strata_exact_ratio = {
        "low": (0.72, 10),
        "high": (0.90, 10),
    }
    disp_exact_ratio = compute_stratified_disparity(strata_exact_ratio)
    assert disp_exact_ratio["absolute_disparity"] == 0.1800
    assert disp_exact_ratio["ratio_disparity"] == 0.8000
    assert disp_exact_ratio["diagnostic"] is None

    # 4. Equal positive metrics (perfect parity: abs=0.0, ratio=1.0 -> None)
    strata_equal_pos = {
        "low": (0.60, 10),
        "high": (0.60, 10),
    }
    disp_equal = compute_stratified_disparity(strata_equal_pos)
    assert disp_equal["absolute_disparity"] == 0.0
    assert disp_equal["ratio_disparity"] == 1.0
    assert disp_equal["diagnostic"] is None


def test_stratified_disparity_input_validation():
    """Verify validation of non-finite, out-of-range, and negative inputs."""
    # Out of range (< 0.0)
    with pytest.raises(ValueError, match="in \\[0.0, 1.0\\]"):
        compute_stratified_disparity({"stratum_a": (-0.01, 10), "stratum_b": (0.5, 10)})

    # Out of range (> 1.0)
    with pytest.raises(ValueError, match="in \\[0.0, 1.0\\]"):
        compute_stratified_disparity({"stratum_a": (1.01, 10), "stratum_b": (0.5, 10)})

    # Non-finite (NaN)
    with pytest.raises(ValueError, match="must be finite"):
        compute_stratified_disparity({"stratum_a": (float("nan"), 10), "stratum_b": (0.5, 10)})

    # Non-finite (+Inf)
    with pytest.raises(ValueError, match="must be finite"):
        compute_stratified_disparity({"stratum_a": (float("inf"), 10), "stratum_b": (0.5, 10)})

    # Non-finite (-Inf)
    with pytest.raises(ValueError, match="must be finite"):
        compute_stratified_disparity({"stratum_a": (float("-inf"), 10), "stratum_b": (0.5, 10)})


def test_pydantic_evaluation_schemas():
    """Verify validation and serialization of Version 2.3 Pydantic schemas."""
    # 1. ColdStartConversionSchema
    cs_schema = ColdStartConversionSchema(
        total_cold_start=10,
        active_cold_start=0,
        converted_cold_start=0,
        overall_conversion_rate=0.0,
        conditional_conversion_rate=None,
        diagnostic="NO_COLD_START_ATTEMPTS",
    )
    assert cs_schema.overall_conversion_rate == 0.0
    assert cs_schema.conditional_conversion_rate is None
    assert cs_schema.diagnostic == "NO_COLD_START_ATTEMPTS"

    # 2. ObservationalLearningGainSchema
    gain_schema = ObservationalLearningGainSchema(
        pre_mastery=None,
        post_mastery=Decimal("0.7000"),
        learning_gain=None,
    )
    assert gain_schema.learning_gain is None

    # 3. StratifiedActivityDisparityBlock (Section 3.5.2)
    block_schema = StratifiedActivityDisparityBlock(
        stratum_metrics={"low": 0.0, "med": 0.0, "high": 0.0},
        stratum_sizes={"low": 12, "med": 15, "high": 11},
        evaluated_stratum_sizes={"low": 12, "med": 15, "high": 11},
        absolute_disparity=0.0,
        ratio_disparity=None,
        diagnostic="ZERO_MAX_METRIC",
    )
    assert block_schema.absolute_disparity == 0.0
    assert block_schema.ratio_disparity is None
    assert block_schema.diagnostic == "ZERO_MAX_METRIC"

    # 4. StratifiedDisparitySchema
    disp_schema = StratifiedDisparitySchema(
        metric_name="precision@5",
        stratum_metrics={"active": 0.85, "sparse": 0.60},
        stratum_sizes={"active": 20, "sparse": 10},
        evaluated_stratum_sizes={"active": 20, "sparse": 10},
        eligible_strata=["active", "sparse"],
        absolute_disparity=0.25,
        ratio_disparity=0.7059,
        diagnostic="DISPARITY_WARNING",
    )
    assert disp_schema.absolute_disparity == 0.25
    assert disp_schema.diagnostic == "DISPARITY_WARNING"
