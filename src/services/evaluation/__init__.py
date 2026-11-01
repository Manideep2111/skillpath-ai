"""Recommendation quality and temporal evaluation package for SkillPath AI."""

from src.services.evaluation.business_rules import (
    BusinessRuleAuditor,
    PrerequisiteAuditResult,
    TemporalLeakageAuditResult,
)
from src.services.evaluation.collectors import (
    AnomalyAuditResult,
    CatalogSnapshot,
    EvaluationDataCollector,
    LearnerCohortSnapshot,
    LearnerInteractionSnapshot,
)
from src.services.evaluation.engine import (
    ComprehensiveEvaluationReport,
    CutoffMetricSummary,
    RecommendationEvaluationEngine,
    WindowEvaluationResult,
)
from src.services.evaluation.ground_truth import (
    GroundTruthExtractor,
    LearnerGroundTruth,
)
from src.services.evaluation.metrics import (
    compute_bounded_recall_at_k,
    compute_catalog_coverage_at_k,
    compute_cold_start_conditional_conversion,
    compute_cold_start_conversion,
    compute_cold_start_overall_conversion,
    compute_dcg_at_k,
    compute_gini_coefficient,
    compute_idcg_at_k,
    compute_idcg_from_pool_at_k,
    compute_ndcg_at_k,
    compute_ndcg_with_ideal_pool_at_k,
    compute_observational_learning_gain,
    compute_observed_precision_at_k,
    compute_precision_at_k,
    compute_realized_precision_at_k,
    compute_recall_at_k,
    compute_stratified_disparity,
    compute_unobserved_exposure_rate_at_k,
)
from src.services.evaluation.temporal_split import (
    TemporalWindow,
    get_dataset_temporal_bounds,
    get_standard_evaluation_windows,
)

__all__ = [
    # Temporal Split
    "TemporalWindow",
    "get_dataset_temporal_bounds",
    "get_standard_evaluation_windows",
    # Metrics
    "compute_precision_at_k",
    "compute_recall_at_k",
    "compute_bounded_recall_at_k",
    "compute_dcg_at_k",
    "compute_idcg_at_k",
    "compute_ndcg_at_k",
    "compute_catalog_coverage_at_k",
    "compute_gini_coefficient",
    # Version 2.3 Metrics
    "compute_realized_precision_at_k",
    "compute_observed_precision_at_k",
    "compute_unobserved_exposure_rate_at_k",
    "compute_idcg_from_pool_at_k",
    "compute_ndcg_with_ideal_pool_at_k",
    "compute_observational_learning_gain",
    "compute_cold_start_overall_conversion",
    "compute_cold_start_conditional_conversion",
    "compute_cold_start_conversion",
    "compute_stratified_disparity",
    # Ground Truth
    "LearnerGroundTruth",
    "GroundTruthExtractor",
    # Business Rules
    "PrerequisiteAuditResult",
    "TemporalLeakageAuditResult",
    "BusinessRuleAuditor",
    # Collectors
    "CatalogSnapshot",
    "LearnerCohortSnapshot",
    "LearnerInteractionSnapshot",
    "AnomalyAuditResult",
    "EvaluationDataCollector",
    # Engine
    "CutoffMetricSummary",
    "WindowEvaluationResult",
    "ComprehensiveEvaluationReport",
    "RecommendationEvaluationEngine",
]
