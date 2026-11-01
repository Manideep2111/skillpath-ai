"""Anomaly detection and sandbox evaluation package for SkillPath AI."""

from src.services.anomaly.detector import (
    AnomalyDetectionService,
    generate_issue_id,
)
from src.services.anomaly.evaluation import (
    AnomalyEvaluator,
    EvaluationReport,
    TypeEvaluationMetrics,
    compute_metrics,
)
from src.services.anomaly.fixture_generator import (
    ANOMALY_TYPE_A1,
    ANOMALY_TYPE_A2,
    ANOMALY_TYPE_A3,
    ANOMALY_TYPE_A4,
    ANOMALY_TYPE_A5,
    DEFAULT_GROUND_TRUTH_PATH,
    AnomalyFixtureGenerator,
)
from src.services.anomaly.sandbox_manager import (
    BASELINE_DB_PATH,
    DEFAULT_SANDBOX_PATH,
    SandboxManager,
    SandboxOverwriteError,
    SandboxPathSecurityError,
)

__all__ = [
    # Sandbox
    "SandboxManager",
    "SandboxPathSecurityError",
    "SandboxOverwriteError",
    "BASELINE_DB_PATH",
    "DEFAULT_SANDBOX_PATH",
    # Fixtures
    "AnomalyFixtureGenerator",
    "DEFAULT_GROUND_TRUTH_PATH",
    "ANOMALY_TYPE_A1",
    "ANOMALY_TYPE_A2",
    "ANOMALY_TYPE_A3",
    "ANOMALY_TYPE_A4",
    "ANOMALY_TYPE_A5",
    # Detector
    "AnomalyDetectionService",
    "generate_issue_id",
    # Evaluation
    "AnomalyEvaluator",
    "EvaluationReport",
    "TypeEvaluationMetrics",
    "compute_metrics",
]
