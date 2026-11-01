"""Pure mathematical formulations for recommendation quality and catalog dispersion.

Implements:
- Precision@K (with fixed-K denominator)
- Standard Recall@K (primary, denominator |Relevant|)
- Bounded Recall@K (auxiliary, denominator min(K, |Relevant|))
- NDCG@K (with exact 4-tier relevance grades 0, 1, 2, 3)
- Catalog Coverage@K (including zero-frequency items)
- Gini coefficient (including zero-frequency items)
- Version 2.3 metrics: Realized Precision@K, Observed Precision@K, Unobserved Exposure Rate@K
- Version 2.3 metrics: External Pool NDCG@K, Observational Learning Gain, Cold-Start Conversion, Stratified Disparity
"""

from decimal import Decimal, ROUND_HALF_EVEN
import math
from typing import Any, Collection, Dict, List, Optional, Set, Tuple


def compute_precision_at_k(
    recommended_items: List[str],
    relevant_items: Set[str],
    k: int,
) -> float:
    """Calculate Precision@K with fixed-K denominator.

    Args:
        recommended_items: Ordered list of recommended content IDs (length <= K).
        relevant_items: Set of relevant content IDs in outcome window.
        k: Ranking cutoff rank (must be > 0).

    Returns:
        float: Fraction of top-K recommendations that are relevant.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    # Top-K slice
    top_k = recommended_items[:k]
    hits = sum(1 for item in top_k if item in relevant_items)

    # Fixed-K denominator penalizes truncated lists
    return hits / float(k)


def compute_recall_at_k(
    recommended_items: List[str],
    relevant_items: Set[str],
    k: int,
) -> Optional[float]:
    """Calculate standard Recall@K (primary metric).

    Denominator is strictly |relevant_items|.

    Args:
        recommended_items: Ordered list of recommended content IDs.
        relevant_items: Set of relevant content IDs.
        k: Ranking cutoff rank.

    Returns:
        Optional[float]: Recall score, or None if |relevant_items| == 0.
    """
    if not relevant_items:
        return None
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    top_k = recommended_items[:k]
    hits = sum(1 for item in top_k if item in relevant_items)
    return hits / float(len(relevant_items))


def compute_bounded_recall_at_k(
    recommended_items: List[str],
    relevant_items: Set[str],
    k: int,
) -> Optional[float]:
    """Calculate auxiliary bounded Recall@K.

    Denominator is min(K, |relevant_items|).

    Args:
        recommended_items: Ordered list of recommended content IDs.
        relevant_items: Set of relevant content IDs.
        k: Ranking cutoff rank.

    Returns:
        Optional[float]: Bounded recall score, or None if |relevant_items| == 0.
    """
    if not relevant_items:
        return None
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    top_k = recommended_items[:k]
    hits = sum(1 for item in top_k if item in relevant_items)
    max_possible_hits = min(k, len(relevant_items))
    return hits / float(max_possible_hits)


def compute_dcg_at_k(
    recommended_items: List[str],
    relevance_grades: Dict[str, int],
    k: int,
) -> float:
    """Calculate Discounted Cumulative Gain at K using graded relevance.

    DCG@K = sum_{rank=1}^{K} (2^{rel} - 1) / log2(rank + 1)
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    top_k = recommended_items[:k]
    dcg = 0.0
    for rank_idx, item in enumerate(top_k, start=1):
        grade = relevance_grades.get(item, 0)
        gain = (2.0 ** grade) - 1.0
        discount = math.log2(rank_idx + 1)
        dcg += gain / discount
    return dcg


def compute_idcg_at_k(
    relevance_grades: Dict[str, int],
    k: int,
) -> float:
    """Calculate Ideal Discounted Cumulative Gain at K.

    Sorts all positive relevance grades descending and discounts top-K.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    sorted_grades = sorted(
        [g for g in relevance_grades.values() if g > 0],
        reverse=True,
    )
    if not sorted_grades:
        return 0.0

    idcg = 0.0
    for rank_idx, grade in enumerate(sorted_grades[:k], start=1):
        gain = (2.0 ** grade) - 1.0
        discount = math.log2(rank_idx + 1)
        idcg += gain / discount
    return idcg


def compute_ndcg_at_k(
    recommended_items: List[str],
    relevance_grades: Dict[str, int],
    k: int,
) -> Optional[float]:
    """Calculate Normalized Discounted Cumulative Gain at K.

    Args:
        recommended_items: Ordered list of recommended content IDs.
        relevance_grades: Mapping of content_id to grade in {0, 1, 2, 3}.
        k: Ranking cutoff rank.

    Returns:
        Optional[float]: NDCG score, or None if no positive relevance grades exist.
    """
    idcg = compute_idcg_at_k(relevance_grades, k)
    if idcg == 0.0:
        return None

    dcg = compute_dcg_at_k(recommended_items, relevance_grades, k)
    return dcg / idcg


def compute_catalog_coverage_at_k(
    all_learner_recommendations: Collection[List[str]],
    active_catalog_ids: Set[str],
    k: int,
) -> float:
    """Calculate catalog coverage at rank K.

    Coverage = |distinct recommended active items| / |active catalog items|
    """
    if not active_catalog_ids:
        return 0.0

    distinct_recommended = set()
    for recs in all_learner_recommendations:
        for item in recs[:k]:
            if item in active_catalog_ids:
                distinct_recommended.add(item)

    return len(distinct_recommended) / float(len(active_catalog_ids))


def compute_gini_coefficient(
    recommendation_frequencies: Dict[str, int],
    active_catalog_ids: Set[str],
) -> float:
    """Calculate Gini coefficient of recommendation distribution across active catalog.

    CRITICAL: Must include active catalog items that received 0 recommendations!

    Args:
        recommendation_frequencies: Count of recommendations per content_id.
        active_catalog_ids: Set of all active catalog content IDs at cutoff.

    Returns:
        float: Gini coefficient in [0.0, 1.0]. 0.0 indicates perfect equality.
    """
    num_items = len(active_catalog_ids)
    if num_items <= 1:
        return 0.0

    # Build complete frequency array including zero counts
    frequencies = [recommendation_frequencies.get(cid, 0) for cid in active_catalog_ids]
    total_recs = sum(frequencies)

    if total_recs == 0:
        return 0.0

    # Sort ascending: f_{(1)} <= f_{(2)} <= ... <= f_{(N)}
    frequencies.sort()

    # Gini formula: sum_{i=1}^{N} (2i - N - 1) * f_{(i)} / (N * sum f_{(i)})
    numerator = sum((2 * i - num_items - 1) * f for i, f in enumerate(frequencies, start=1))
    denominator = num_items * total_recs

    return numerator / float(denominator)


# =============================================================================
# Evaluation Methodology Version 2.3 Pure Metric Implementations
# =============================================================================


def compute_realized_precision_at_k(
    recommended_items: List[str],
    relevant_items: Set[str],
    k: int,
) -> float:
    """Calculate Realized Precision@K.

    Unlike standard Precision@K (which always divides by K), Realized Precision@K
    divides by the realized recommendation list length at rank K: min(k, len(recommended_items)).
    This avoids artificially penalizing short recommendation lists resulting from prerequisite gating.

    Args:
        recommended_items: Ordered list of recommended content IDs.
        relevant_items: Set of relevant content IDs in outcome window.
        k: Ranking cutoff rank (must be > 0).

    Returns:
        float: Fraction of realized top-K recommendations that are relevant,
               or 0.0 if recommended_items is empty.

    Raises:
        ValueError: If k <= 0 or if top-K contains duplicate content IDs.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    top_k = recommended_items[:k]
    if len(top_k) != len(set(top_k)):
        raise ValueError("recommended_items contains duplicate IDs in top-K")

    if not top_k:
        return 0.0

    hits = sum(1 for item in top_k if item in relevant_items)
    return hits / float(len(top_k))


def compute_observed_precision_at_k(
    recommended_items: List[str],
    relevant_items: Set[str],
    observed_items: Set[str],
    k: int,
    unobserved_items: Optional[Set[str]] = None,
) -> Optional[float]:
    """Calculate Observed Precision@K among recommendations actually observed by the learner.

    Args:
        recommended_items: Ordered list of recommended content IDs.
        relevant_items: Set of relevant content IDs in outcome window.
        observed_items: Set of content IDs the learner observed/interacted with.
        k: Ranking cutoff rank (must be > 0).
        unobserved_items: Optional explicit set of unobserved content IDs.

    Returns:
        Optional[float]: Precision among observed recommendations, or None if
                         zero top-K recommendations were observed.

    Raises:
        ValueError: If k <= 0, duplicate IDs in top-K, or contradictory interaction sets.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    top_k = recommended_items[:k]
    if len(top_k) != len(set(top_k)):
        raise ValueError("recommended_items contains duplicate IDs in top-K")

    # Contradictory interaction sets validation
    if unobserved_items is not None:
        if observed_items & unobserved_items:
            raise ValueError("Contradictory interaction sets: observed_items and unobserved_items intersect")

    if not relevant_items.issubset(observed_items):
        raise ValueError("Contradictory interaction sets: relevant_items contains items not in observed_items")

    observed_rec_count = sum(1 for item in top_k if item in observed_items)
    if observed_rec_count == 0:
        return None

    hits = sum(1 for item in top_k if item in relevant_items)
    return hits / float(observed_rec_count)


def compute_unobserved_exposure_rate_at_k(
    recommended_items: List[str],
    observed_items: Set[str],
    k: int,
    unobserved_items: Optional[Set[str]] = None,
) -> float:
    """Calculate Unobserved Exposure Rate@K.

    Proportion of top-K recommendations that the learner never interacted with.

    Args:
        recommended_items: Ordered list of recommended content IDs.
        observed_items: Set of content IDs the learner observed/interacted with.
        k: Ranking cutoff rank (must be > 0).
        unobserved_items: Optional explicit set of unobserved content IDs.

    Returns:
        float: Proportion of top-K recommendations that were unobserved,
               or 0.0 if recommended_items is empty.

    Raises:
        ValueError: If k <= 0, duplicate IDs in top-K, or contradictory interaction sets.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    top_k = recommended_items[:k]
    if len(top_k) != len(set(top_k)):
        raise ValueError("recommended_items contains duplicate IDs in top-K")

    if not top_k:
        return 0.0

    if unobserved_items is not None:
        if observed_items & unobserved_items:
            raise ValueError("Contradictory interaction sets: observed_items and unobserved_items intersect")
        unobserved_count = sum(1 for item in top_k if (item in unobserved_items or item not in observed_items))
    else:
        unobserved_count = sum(1 for item in top_k if item not in observed_items)

    return unobserved_count / float(len(top_k))


def compute_idcg_from_pool_at_k(
    ideal_relevance_pool: Collection[int] | Dict[str, int],
    k: int,
) -> float:
    """Calculate Ideal Discounted Cumulative Gain at K using an external relevance pool.

    Args:
        ideal_relevance_pool: Complete collection of grades or mapping of content_id -> grade.
        k: Ranking cutoff rank (must be > 0).

    Returns:
        float: Ideal DCG at K, or 0.0 if no positive relevance grades exist.

    Raises:
        ValueError: If k <= 0.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    if isinstance(ideal_relevance_pool, dict):
        grades = [g for g in ideal_relevance_pool.values() if g > 0]
    else:
        grades = [g for g in ideal_relevance_pool if g > 0]

    if not grades:
        return 0.0

    grades.sort(reverse=True)
    idcg = 0.0
    for rank_idx, grade in enumerate(grades[:k], start=1):
        gain = (2.0 ** grade) - 1.0
        discount = math.log2(rank_idx + 1)
        idcg += gain / discount
    return idcg


def compute_ndcg_with_ideal_pool_at_k(
    recommended_items: List[str],
    relevance_grades: Dict[str, int],
    ideal_relevance_pool: Collection[int] | Dict[str, int],
    k: int,
) -> Optional[float]:
    """Calculate NDCG@K using a separate, complete evaluation-window relevance pool for IDCG.

    Preserves current behavior when IDCG is zero: returns None.

    Args:
        recommended_items: Ordered list of recommended content IDs.
        relevance_grades: Mapping of content_id to observed relevance grade.
        ideal_relevance_pool: External ideal pool (Collection or Dict) for IDCG.
        k: Ranking cutoff rank (must be > 0).

    Returns:
        Optional[float]: NDCG score, or None if IDCG is zero.

    Raises:
        ValueError: If k <= 0 or if top-K contains duplicate content IDs.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    top_k = recommended_items[:k]
    if len(top_k) != len(set(top_k)):
        raise ValueError("recommended_items contains duplicate IDs in top-K")

    idcg = compute_idcg_from_pool_at_k(ideal_relevance_pool, k)
    if idcg == 0.0:
        return None

    dcg = compute_dcg_at_k(top_k, relevance_grades, k)
    return dcg / idcg


def compute_observational_learning_gain(
    pre_mastery: Optional[Decimal],
    post_mastery: Optional[Decimal],
) -> Optional[Decimal]:
    """Calculate observational learning gain using exact Decimal arithmetic.

    Implements Version 2.3 normalized learning gain:
    - Missing pre-mastery (None) or missing post-mastery (None) returns None.
    - Equal pre/post mastery returns Decimal("0.0000").
    - If post_mastery > pre_mastery: (post_mastery - pre_mastery) / (Decimal("1.0000") - pre_mastery).
    - If post_mastery < pre_mastery: (post_mastery - pre_mastery) / pre_mastery.
    - Quantized to four decimal places using ROUND_HALF_EVEN.
    - Avoids converting Decimal values to float for arithmetic.

    Args:
        pre_mastery: Pre-cutoff point-in-time mastery (in [0.0, 1.0]) or None.
        post_mastery: Post-attempt point-in-time mastery (in [0.0, 1.0]) or None.

    Returns:
        Optional[Decimal]: Normalized learning gain in range [-1.0000, 1.0000],
                           or None if baseline/post mastery is missing.

    Raises:
        TypeError: If inputs are not Decimal or None.
        ValueError: If inputs are non-finite (NaN, Inf) or outside [0.0000, 1.0000].
    """
    for name, val in [("pre_mastery", pre_mastery), ("post_mastery", post_mastery)]:
        if val is not None:
            if not isinstance(val, Decimal):
                raise TypeError(f"{name} must be Decimal or None, got {type(val).__name__}")
            if not val.is_finite():
                raise ValueError(f"{name} must be a finite Decimal, got {val}")
            if val < Decimal("0.0000") or val > Decimal("1.0000"):
                raise ValueError(f"{name} must be in range [0.0000, 1.0000], got {val}")

    if pre_mastery is None or post_mastery is None:
        return None

    if post_mastery == pre_mastery:
        return Decimal("0.0000")

    FOUR_PLACES = Decimal("0.0001")
    ONE = Decimal("1.0000")

    if post_mastery > pre_mastery:
        gain = (post_mastery - pre_mastery) / (ONE - pre_mastery)
    else:
        gain = (post_mastery - pre_mastery) / pre_mastery

    return gain.quantize(FOUR_PLACES, rounding=ROUND_HALF_EVEN)


def compute_cold_start_overall_conversion(
    total_cold_start: int,
    converted_cold_start: int,
) -> Optional[float]:
    """Calculate overall cold-start conversion rate.

    Rate = converted_cold_start / total_cold_start.
    Returns None if total_cold_start is 0 (undefined).
    Returns 0.0 if total_cold_start > 0 and converted_cold_start == 0 (valid numerical zero).

    Raises:
        ValueError: If counts are negative or converted > total.
    """
    if total_cold_start < 0:
        raise ValueError(f"total_cold_start cannot be negative, got {total_cold_start}")
    if converted_cold_start < 0:
        raise ValueError(f"converted_cold_start cannot be negative, got {converted_cold_start}")
    if converted_cold_start > total_cold_start:
        raise ValueError(
            f"converted_cold_start ({converted_cold_start}) cannot exceed total_cold_start ({total_cold_start})"
        )

    if total_cold_start == 0:
        return None

    return converted_cold_start / float(total_cold_start)


def compute_cold_start_conditional_conversion(
    active_cold_start: int,
    converted_cold_start: int,
) -> Optional[float]:
    """Calculate conditional cold-start conversion rate (conditioned on platform activity).

    Rate = converted_cold_start / active_cold_start.
    Returns None if active_cold_start is 0 (undefined / no cold-start attempts).
    Returns 0.0 if active_cold_start > 0 and converted_cold_start == 0 (valid numerical zero).

    Raises:
        ValueError: If counts are negative or converted > active.
    """
    if active_cold_start < 0:
        raise ValueError(f"active_cold_start cannot be negative, got {active_cold_start}")
    if converted_cold_start < 0:
        raise ValueError(f"converted_cold_start cannot be negative, got {converted_cold_start}")
    if converted_cold_start > active_cold_start:
        raise ValueError(
            f"converted_cold_start ({converted_cold_start}) cannot exceed active_cold_start ({active_cold_start})"
        )

    if active_cold_start == 0:
        return None

    return converted_cold_start / float(active_cold_start)


def compute_cold_start_conversion(
    total_cold_start: int,
    active_cold_start: int,
    converted_cold_start: int,
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Calculate both overall and conditional cold-start conversion rates with diagnostics.

    Returns:
        Tuple[Optional[float], Optional[float], Optional[str]]:
            (overall_conversion_rate, conditional_conversion_rate, diagnostic).
            When active_cold_start == 0, conditional_conversion_rate is None and
            diagnostic is 'NO_COLD_START_ATTEMPTS'.

    Raises:
        ValueError: If counts are negative or converted <= active <= total hierarchy is violated.
    """
    if total_cold_start < 0 or active_cold_start < 0 or converted_cold_start < 0:
        raise ValueError("Counts cannot be negative")
    if active_cold_start > total_cold_start:
        raise ValueError(
            f"active_cold_start ({active_cold_start}) cannot exceed total_cold_start ({total_cold_start})"
        )
    if converted_cold_start > active_cold_start:
        raise ValueError(
            f"converted_cold_start ({converted_cold_start}) cannot exceed active_cold_start ({active_cold_start})"
        )

    overall = compute_cold_start_overall_conversion(total_cold_start, converted_cold_start)
    conditional = compute_cold_start_conditional_conversion(active_cold_start, converted_cold_start)

    diagnostic = None
    if active_cold_start == 0:
        diagnostic = "NO_COLD_START_ATTEMPTS"

    return overall, conditional, diagnostic


def compute_stratified_disparity(
    strata: Dict[str, Any],
    min_evaluated_learners: int = 5,
) -> Dict[str, Optional[Any]]:
    """Calculate disparity metrics across evaluated learner strata according to Version 2.3 Section 3.5.2.

    Stratum Qualification:
    - Minimum sample size threshold: evaluated_count >= min_evaluated_learners (default 5).
    - Excludes a stratum from aggregation if its metric is None.
    - Requires metric values to be finite and within [0.0, 1.0]. Rejects non-finite or out-of-range values with ValueError.
    - Preserves all strata in reporting metadata (stratum_metrics, stratum_sizes, evaluated_stratum_sizes).
    - Requires at least two eligible strata for disparity calculations (|V| >= 2).

    Diagnostic Precedence Order:
    1. |V| < 2:
       absolute_disparity = None
       ratio_disparity = None
       diagnostic = "INSUFFICIENT_EVALUATED_STRATA"
    2. |V| >= 2 and max_{j in V} M(S_j) == 0.0:
       absolute_disparity = 0.0
       ratio_disparity = None
       diagnostic = "ZERO_MAX_METRIC"
    3. |V| >= 2 and max_{j in V} M(S_j) > 0.0:
       absolute_disparity = max - min
       ratio_disparity = min / max
       diagnostic = "DISPARITY_WARNING" if (absolute_disparity > 0.25 or ratio_disparity < 0.80) else None

    Args:
        strata: Mapping of stratum name to:
                - (metric_value, evaluated_count)
                - (metric_value, evaluated_count, stratum_size)
                - dict with 'metric'/'metric_value', 'evaluated_count'/'count', and optional 'stratum_size'/'size'
                - object with attributes metric/metric_value and evaluated_count/count
        min_evaluated_learners: Minimum count of evaluated learners required for eligibility (default 5).

    Returns:
        Dict with:
        - stratum_metrics: Dict[str, Optional[float]]
        - stratum_sizes: Dict[str, int]
        - evaluated_stratum_sizes: Dict[str, int]
        - eligible_strata: List[str]
        - max_stratum: Optional[str]
        - min_stratum: Optional[str]
        - max_value: Optional[float]
        - min_value: Optional[float]
        - absolute_disparity: Optional[float]
        - ratio_disparity: Optional[float]
        - diagnostic: Optional[str]

    Raises:
        ValueError: If a metric value is non-finite (NaN, Inf) or outside [0.0, 1.0], or if counts are negative.
        TypeError: If a stratum representation is unsupported.
    """
    all_stratum_metrics: Dict[str, Optional[float]] = {}
    all_stratum_sizes: Dict[str, int] = {}
    all_evaluated_sizes: Dict[str, int] = {}
    eligible: Dict[str, float] = {}

    for name, entry in strata.items():
        metric_val: Optional[float] = None
        count_val: int = 0
        size_val: int = 0

        if isinstance(entry, (tuple, list)):
            if len(entry) == 2:
                m, c = entry
                metric_val = float(m) if m is not None else None
                count_val = int(c)
                size_val = count_val
            elif len(entry) >= 3:
                m, c, s = entry[:3]
                metric_val = float(m) if m is not None else None
                count_val = int(c)
                size_val = int(s)
            else:
                raise TypeError(f"Tuple stratum entry for '{name}' must have at least 2 elements")
        elif isinstance(entry, dict):
            m = entry.get("metric", entry.get("metric_value"))
            metric_val = float(m) if m is not None else None
            c = entry.get("evaluated_count", entry.get("count", 0))
            count_val = int(c)
            s = entry.get("stratum_size", entry.get("size", count_val))
            size_val = int(s)
        elif hasattr(entry, "metric_value") and hasattr(entry, "evaluated_count"):
            m = entry.metric_value
            metric_val = float(m) if m is not None else None
            count_val = int(entry.evaluated_count)
            size_val = int(getattr(entry, "stratum_size", getattr(entry, "size", count_val)))
        elif hasattr(entry, "metric") and hasattr(entry, "count"):
            m = entry.metric
            metric_val = float(m) if m is not None else None
            count_val = int(entry.count)
            size_val = int(getattr(entry, "stratum_size", getattr(entry, "size", count_val)))
        else:
            raise TypeError(f"Unsupported stratum representation for '{name}': {entry}")

        if count_val < 0 or size_val < 0:
            raise ValueError(f"Stratum sizes for '{name}' cannot be negative")

        # Validate non-None metric values
        if metric_val is not None:
            if math.isnan(metric_val) or math.isinf(metric_val):
                raise ValueError(f"Metric value for stratum '{name}' must be finite, got {metric_val}")
            if metric_val < 0.0 or metric_val > 1.0:
                raise ValueError(f"Metric value for stratum '{name}' must be in [0.0, 1.0], got {metric_val}")

        all_stratum_metrics[name] = metric_val
        all_evaluated_sizes[name] = count_val
        all_stratum_sizes[name] = size_val

        # Qualification rule: N_eval >= N_min and M is not None
        if metric_val is not None and count_val >= min_evaluated_learners:
            eligible[name] = metric_val

    # Branch 1: Insufficient Eligible Strata (|V| < 2)
    if len(eligible) < 2:
        return {
            "stratum_metrics": all_stratum_metrics,
            "stratum_sizes": all_stratum_sizes,
            "evaluated_stratum_sizes": all_evaluated_sizes,
            "eligible_strata": list(eligible.keys()),
            "max_stratum": next(iter(eligible.keys())) if eligible else None,
            "min_stratum": next(iter(eligible.keys())) if eligible else None,
            "max_value": next(iter(eligible.values())) if eligible else None,
            "min_value": next(iter(eligible.values())) if eligible else None,
            "absolute_disparity": None,
            "ratio_disparity": None,
            "diagnostic": "INSUFFICIENT_EVALUATED_STRATA",
        }

    max_s = max(eligible, key=lambda k: eligible[k])
    min_s = min(eligible, key=lambda k: eligible[k])
    max_v = eligible[max_s]
    min_v = eligible[min_s]

    # Branch 2: Zero Maximum Metric with Multiple Eligible Strata (|V| >= 2 and max == 0.0)
    if max_v == 0.0:
        return {
            "stratum_metrics": all_stratum_metrics,
            "stratum_sizes": all_stratum_sizes,
            "evaluated_stratum_sizes": all_evaluated_sizes,
            "eligible_strata": list(eligible.keys()),
            "max_stratum": max_s,
            "min_stratum": min_s,
            "max_value": 0.0,
            "min_value": 0.0,
            "absolute_disparity": 0.0,
            "ratio_disparity": None,
            "diagnostic": "ZERO_MAX_METRIC",
        }

    # Branch 3: Standard Valid Disparity (|V| >= 2 and max > 0.0)
    abs_disp = round(max_v - min_v, 4)
    ratio_disp = round(min_v / max_v, 4)

    # Diagnostic Precedence:
    # "DISPARITY_WARNING" if Disparity_abs > 0.25 or Disparity_ratio < 0.80 else None
    if abs_disp > 0.25 or ratio_disp < 0.80:
        diagnostic = "DISPARITY_WARNING"
    else:
        diagnostic = None

    return {
        "stratum_metrics": all_stratum_metrics,
        "stratum_sizes": all_stratum_sizes,
        "evaluated_stratum_sizes": all_evaluated_sizes,
        "eligible_strata": list(eligible.keys()),
        "max_stratum": max_s,
        "min_stratum": min_s,
        "max_value": max_v,
        "min_value": min_v,
        "absolute_disparity": abs_disp,
        "ratio_disparity": ratio_disp,
        "diagnostic": diagnostic,
    }

