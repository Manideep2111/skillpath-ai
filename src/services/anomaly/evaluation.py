"""Evaluation service for SkillPath AI anomaly detection.

Compares detected issues in the sandbox database against external ground-truth labels.
Computes True Positives (TP), False Positives (FP), False Negatives (FN),
Precision, Recall, and F1 score, both overall and broken down by the five SRS anomaly types.
Handles zero-denominator edge cases cleanly.
"""

from dataclasses import dataclass, field
from pathlib import Path
import csv
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.entities import DataIssue
from src.services.anomaly.fixture_generator import (
    ANOMALY_TYPE_A1,
    ANOMALY_TYPE_A2,
    ANOMALY_TYPE_A3,
    ANOMALY_TYPE_A4,
    ANOMALY_TYPE_A5,
    DEFAULT_GROUND_TRUTH_PATH,
)


@dataclass(frozen=True)
class TypeEvaluationMetrics:
    """Metrics for a single anomaly type."""

    anomaly_type: str
    ground_truth_count: int
    detected_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float


@dataclass(frozen=True)
class EvaluationReport:
    """Complete evaluation report across all anomaly types."""

    total_ground_truth: int
    total_detected: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    by_type: dict[str, TypeEvaluationMetrics] = field(default_factory=dict)

    def summary_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "total_ground_truth": self.total_ground_truth,
            "total_detected": self.total_detected,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "by_type": {
                k: {
                    "ground_truth_count": v.ground_truth_count,
                    "detected_count": v.detected_count,
                    "true_positives": v.true_positives,
                    "false_positives": v.false_positives,
                    "false_negatives": v.false_negatives,
                    "precision": round(v.precision, 4),
                    "recall": round(v.recall, 4),
                    "f1_score": round(v.f1_score, 4),
                }
                for k, v in self.by_type.items()
            },
        }


def compute_metrics(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Calculate Precision, Recall, and F1 safely without zero division.

    Mathematical Formulations:
        Precision = TP / (TP + FP)
        Recall    = TP / (TP + FN)
        F1-Score  = 2 * (Precision * Recall) / (Precision + Recall)

    Zero-Denominator Invariants:
        1. When TP + FP == 0 (no positive predictions made):
           - If FN == 0 (no actual positives existed either), Precision = 1.0 (vacuously true).
           - If FN > 0 (actual anomalies existed but none predicted), Precision = 0.0.
        2. When TP + FN == 0 (no ground-truth anomalies exist):
           - If FP == 0 (no false alarms either), Recall = 1.0 (vacuously true).
           - If FP > 0 (false alarms triggered with no actual anomalies), Recall = 0.0.
        3. When Precision + Recall == 0.0, F1 = 0.0.
    """
    if tp + fp == 0:
        precision = 1.0 if fn == 0 else 0.0
    else:
        precision = tp / (tp + fp)

    if tp + fn == 0:
        recall = 1.0 if fp == 0 else 0.0
    else:
        recall = tp / (tp + fn)

    if precision + recall == 0.0:
        f1 = 0.0
    else:
        f1 = 2.0 * (precision * recall) / (precision + recall)

    return precision, recall, f1



class AnomalyEvaluator:
    """Evaluates anomaly detection accuracy against ground-truth labels."""

    @staticmethod
    def load_ground_truth(csv_path: Path | str = DEFAULT_GROUND_TRUTH_PATH) -> list[dict[str, str]]:
        """Load ground-truth labels from CSV file.

        Args:
            csv_path: Path to anomaly_labels.csv

        Returns:
            list[dict[str, str]]: List of ground truth label records.
        """
        p = Path(csv_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Ground truth file not found at '{p}'.")

        with open(p, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)

    @classmethod
    def evaluate_session(
        cls,
        session: Session,
        ground_truth_csv_path: Path | str = DEFAULT_GROUND_TRUTH_PATH,
    ) -> EvaluationReport:
        """Evaluate detected issues in the database against ground truth CSV.

        Args:
            session: SQLAlchemy session bound to sandbox database.
            ground_truth_csv_path: Path to ground-truth CSV file.

        Returns:
            EvaluationReport: Precision, Recall, and F1 metrics.
        """
        ground_truth = cls.load_ground_truth(ground_truth_csv_path)
        detected_issues = session.scalars(select(DataIssue)).all()
        return cls.evaluate(ground_truth, detected_issues)

    @classmethod
    def evaluate(
        cls,
        ground_truth: list[dict[str, str]],
        detected_issues: list[DataIssue],
    ) -> EvaluationReport:
        """Core evaluation logic comparing ground-truth records with detected DataIssue instances.

        Matches entities by (anomaly_type, entity_id).

        Aggregation Method:
            Aggregate metrics use micro-averaging by summing category-level confusion counts
            (Total TP = sum(TP_i), Total FP = sum(FP_i), Total FN = sum(FN_i))
            before computing overall Precision, Recall, and F1.
            This ensures mathematical consistency:
                Total Ground Truth = Total TP + Total FN
                Total Detected     = Total TP + Total FP
                Overall Precision  = Total TP / (Total TP + Total FP)
                Overall Recall     = Total TP / (Total TP + Total FN)
        """
        # Build ground-truth set: (anomaly_type, entity_id)
        gt_keys = {(r["anomaly_type"], r["entity_id"]) for r in ground_truth}
        det_keys = {(i.anomaly_type, i.entity_id) for i in detected_issues}

        tp_keys = gt_keys & det_keys
        fp_keys = det_keys - gt_keys
        fn_keys = gt_keys - det_keys

        overall_precision, overall_recall, overall_f1 = compute_metrics(
            len(tp_keys), len(fp_keys), len(fn_keys)
        )

        all_types = [
            ANOMALY_TYPE_A1,
            ANOMALY_TYPE_A2,
            ANOMALY_TYPE_A3,
            ANOMALY_TYPE_A4,
            ANOMALY_TYPE_A5,
        ]

        # Also include any other anomaly types present in gt or detected
        for t, _ in gt_keys | det_keys:
            if t not in all_types:
                all_types.append(t)

        by_type: dict[str, TypeEvaluationMetrics] = {}
        for t in all_types:
            t_gt = {k for k in gt_keys if k[0] == t}
            t_det = {k for k in det_keys if k[0] == t}
            t_tp = t_gt & t_det
            t_fp = t_det - t_gt
            t_fn = t_gt - t_det

            p, r, f1 = compute_metrics(len(t_tp), len(t_fp), len(t_fn))

            by_type[t] = TypeEvaluationMetrics(
                anomaly_type=t,
                ground_truth_count=len(t_gt),
                detected_count=len(t_det),
                true_positives=len(t_tp),
                false_positives=len(t_fp),
                false_negatives=len(t_fn),
                precision=p,
                recall=r,
                f1_score=f1,
            )

        return EvaluationReport(
            total_ground_truth=len(gt_keys),
            total_detected=len(det_keys),
            true_positives=len(tp_keys),
            false_positives=len(fp_keys),
            false_negatives=len(fn_keys),
            precision=overall_precision,
            recall=overall_recall,
            f1_score=overall_f1,
            by_type=by_type,
        )
