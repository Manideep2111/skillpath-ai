"""Pydantic v2 schemas for Evaluation Methodology Version 2.3 metrics and reporting."""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ColdStartConversionSchema(BaseModel):
    """Schema for cold-start conversion metrics."""

    total_cold_start: int = Field(..., ge=0, description="Total count of cold-start learners at cutoff")
    active_cold_start: int = Field(..., ge=0, description="Count of cold-start learners active in window")
    converted_cold_start: int = Field(..., ge=0, description="Count of cold-start learners who converted")
    overall_conversion_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Converted / Total")
    conditional_conversion_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Converted / Active")
    diagnostic: Optional[str] = Field(default=None, description="Diagnostic code when rates are undefined")

    model_config = ConfigDict(from_attributes=True)


class ObservationalLearningGainSchema(BaseModel):
    """Schema for observational learning gain calculation."""

    pre_mastery: Optional[Decimal] = Field(default=None, ge=Decimal("0.0"), le=Decimal("1.0"))
    post_mastery: Optional[Decimal] = Field(default=None, ge=Decimal("0.0"), le=Decimal("1.0"))
    learning_gain: Optional[Decimal] = Field(default=None, ge=Decimal("-1.0000"), le=Decimal("1.0000"))

    model_config = ConfigDict(from_attributes=True)


class StratifiedActivityDisparityBlock(BaseModel):
    """Block schema for stratified activity disparity evaluation (Section 3.5.2)."""

    stratum_metrics: Dict[str, Optional[float]] = Field(..., description="Observed metric per stratum")
    stratum_sizes: Dict[str, int] = Field(..., description="Total stratum sizes")
    evaluated_stratum_sizes: Dict[str, int] = Field(..., description="Evaluated learner count per stratum")
    absolute_disparity: Optional[float] = Field(default=None, description="Max minus Min eligible metric")
    ratio_disparity: Optional[float] = Field(default=None, description="Min divided by Max eligible metric")
    diagnostic: Optional[str] = Field(default=None, description="Disparity diagnostic code")

    model_config = ConfigDict(from_attributes=True)


class StratifiedDisparitySchema(BaseModel):
    """Schema for stratified disparity evaluation across learner cohorts."""

    metric_name: Optional[str] = Field(default=None, description="Name of the metric evaluated (e.g. precision@5)")
    stratum_metrics: Dict[str, Optional[float]] = Field(default_factory=dict)
    stratum_sizes: Dict[str, int] = Field(default_factory=dict)
    evaluated_stratum_sizes: Dict[str, int] = Field(default_factory=dict)
    eligible_strata: List[str] = Field(default_factory=list, description="Strata meeting eligibility criteria")
    max_stratum: Optional[str] = Field(default=None)
    min_stratum: Optional[str] = Field(default=None)
    max_value: Optional[float] = Field(default=None)
    min_value: Optional[float] = Field(default=None)
    absolute_disparity: Optional[float] = Field(default=None)
    ratio_disparity: Optional[float] = Field(default=None)
    diagnostic: Optional[str] = Field(default=None, description="Diagnostic code if disparity cannot be computed or warns")

    model_config = ConfigDict(from_attributes=True)


class AnomalyAuditItemSchema(BaseModel):
    """Schema for individual anomaly audit result."""

    audit_name: str
    anomaly_type: str
    passed: bool
    total_checked: int = Field(..., ge=0)
    violations_count: int = Field(..., ge=0)
    details: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class AnomalyAuditSummarySchema(BaseModel):
    """Schema for full suite of five anomaly audits."""

    total_audits: int = Field(..., ge=0)
    all_passed: bool
    audits: Dict[str, AnomalyAuditItemSchema] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class CutoffMetricSummarySchema(BaseModel):
    """Schema for rank-K metric summary at a temporal cutoff."""

    k: int = Field(..., gt=0)
    mean_precision: float = Field(..., ge=0.0, le=1.0)
    mean_standard_recall: float = Field(..., ge=0.0, le=1.0)
    mean_bounded_recall: float = Field(..., ge=0.0, le=1.0)
    mean_ndcg: float = Field(..., ge=0.0, le=1.0)
    catalog_coverage: float = Field(..., ge=0.0, le=1.0)
    gini_coefficient: float = Field(..., ge=0.0, le=1.0)
    evaluated_learners_count: int = Field(..., ge=0)
    excluded_learners_count: int = Field(..., ge=0)
    mean_realized_precision: float = Field(default=0.0, ge=0.0, le=1.0)
    mean_observed_precision: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    mean_unobserved_exposure_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    mean_ndcg_ideal_pool: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    stratified_disparity: Optional[StratifiedActivityDisparityBlock] = Field(default=None)

    model_config = ConfigDict(from_attributes=True)


class WindowEvaluationResultSchema(BaseModel):
    """Schema for evaluation results of a single temporal window."""

    cutoff: str
    planned_end: str
    actual_horizon: str
    is_partially_observed: bool
    total_learners: int = Field(..., ge=0)
    evaluated_learners: int = Field(..., ge=0)
    excluded_learners: int = Field(..., ge=0)
    cold_start_learners: int = Field(..., ge=0)
    active_catalog_size: int = Field(..., ge=0)
    metrics_by_k: Dict[int, CutoffMetricSummarySchema] = Field(default_factory=dict)
    prerequisite_audit: Optional[Dict[str, Any]] = None
    temporal_leakage_audit: Optional[Dict[str, Any]] = None
    cold_start_conversion: Optional[ColdStartConversionSchema] = None
    observational_learning_gain: Optional[ObservationalLearningGainSchema] = None
    stratified_disparity: Optional[StratifiedActivityDisparityBlock] = None
    anomaly_audits: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class ComprehensiveEvaluationReportSchema(BaseModel):
    """Schema for comprehensive multi-window evaluation report."""

    evaluation_id: str
    generated_at: str
    dataset_profile: str
    database_target: str
    k_values: List[int]
    windows_evaluated: List[WindowEvaluationResultSchema] = Field(default_factory=list)
    relevance_mapping_spec: Dict[int, str] = Field(default_factory=dict)
    methodology_and_limitations: List[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TypeEvaluationMetricsSchema(BaseModel):
    """Metrics for a single anomaly type in sandbox benchmark."""

    anomaly_type: str
    ground_truth_count: int = Field(..., ge=0)
    detected_count: int = Field(..., ge=0)
    true_positives: int = Field(..., ge=0)
    false_positives: int = Field(..., ge=0)
    false_negatives: int = Field(..., ge=0)
    precision: float = Field(..., ge=0.0, le=1.0)
    recall: float = Field(..., ge=0.0, le=1.0)
    f1_score: float = Field(..., ge=0.0, le=1.0)

    model_config = ConfigDict(from_attributes=True)


class SandboxEvaluationSummarySchema(BaseModel):
    """Summary of anomaly detection benchmark against ground truth."""

    total_ground_truth: int = Field(..., ge=0)
    total_detected: int = Field(..., ge=0)
    true_positives: int = Field(..., ge=0)
    false_positives: int = Field(..., ge=0)
    false_negatives: int = Field(..., ge=0)
    precision: float = Field(..., ge=0.0, le=1.0)
    recall: float = Field(..., ge=0.0, le=1.0)
    f1_score: float = Field(..., ge=0.0, le=1.0)
    by_type: Dict[str, TypeEvaluationMetricsSchema] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class AnomalyStatusResponse(BaseModel):
    """Response schema for GET /api/v1/anomalies/status."""

    baseline_status: str = Field(..., description="Overall baseline status ('CLEAN' or 'VIOLATIONS_DETECTED')")
    baseline_database: str = Field(..., description="Target database file evaluated")
    total_baseline_violations: int = Field(..., ge=0)
    baseline_audits: Dict[str, AnomalyAuditItemSchema] = Field(default_factory=dict)
    sandbox_evaluation: Optional[SandboxEvaluationSummarySchema] = None
    sandbox_database: Optional[str] = None
    ground_truth_file: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
