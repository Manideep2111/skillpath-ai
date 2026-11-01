"""Orchestration engine for recommendation quality and temporal evaluation.

Coordinates:
- Multi-cutoff temporal window slicing
- Learner cohort stratification (low, med, high, sparse, cold-start) via EvaluationDataCollector
- Point-in-time recommendation generation (persist=False)
- Ground-truth outcome extraction with 4-tier relevance (0, 1, 2, 3)
- Metric calculation:
  - Legacy: Precision@K, Recall@K, Bounded Recall@K, NDCG@K, Coverage@K, Gini
  - Version 2.3: Realized Precision@K, Observed Precision@K, Unobserved Exposure Rate@K,
    External Ideal Pool NDCG@K, Observational Learning Gain, Cold-Start Conversion,
    Stratified Activity Disparity (Section 3.5.2)
- Five read-only anomaly audits:
  1. Recommendation prerequisite compliance (A1)
  2. Attempt timestamp order inversions (A2)
  3. Orphaned content-skill references (A3)
  4. Future mastery snapshot leakage (A4)
  5. Learning path loops without progress (A5)
- Generation and Pydantic validation of detailed JSON and Markdown reports under data/reports/
"""

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from src.schemas.evaluation import (
    ColdStartConversionSchema,
    ComprehensiveEvaluationReportSchema,
    ObservationalLearningGainSchema,
    StratifiedActivityDisparityBlock,
    WindowEvaluationResultSchema,
)
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
from src.services.evaluation.ground_truth import GroundTruthExtractor
from src.services.evaluation.metrics import (
    compute_bounded_recall_at_k,
    compute_catalog_coverage_at_k,
    compute_cold_start_conversion,
    compute_gini_coefficient,
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
    get_standard_evaluation_windows,
)
from src.services.mastery_service import MasteryService
from src.services.recommendation_service import RecommendationService

logger = logging.getLogger(__name__)


@dataclass
class CutoffMetricSummary:
    """Aggregated evaluation metrics for a single cutoff window at rank K."""

    k: int
    mean_precision: float
    mean_standard_recall: float
    mean_bounded_recall: float
    mean_ndcg: float
    catalog_coverage: float
    gini_coefficient: float
    evaluated_learners_count: int
    excluded_learners_count: int
    mean_realized_precision: float = 0.0
    mean_observed_precision: Optional[float] = None
    mean_unobserved_exposure_rate: float = 0.0
    mean_ndcg_ideal_pool: Optional[float] = None
    stratified_disparity: Optional[Dict[str, Any]] = None


@dataclass
class WindowEvaluationResult:
    """Complete evaluation report for a single temporal cutoff window."""

    cutoff: str
    planned_end: str
    actual_horizon: str
    is_partially_observed: bool
    total_learners: int
    evaluated_learners: int
    excluded_learners: int
    cold_start_learners: int
    active_catalog_size: int
    metrics_by_k: Dict[int, CutoffMetricSummary] = field(default_factory=dict)
    prerequisite_audit: Optional[Dict[str, Any]] = None
    temporal_leakage_audit: Optional[Dict[str, Any]] = None
    cold_start_conversion: Optional[Dict[str, Any]] = None
    observational_learning_gain: Optional[Dict[str, Any]] = None
    stratified_disparity: Optional[Dict[str, Any]] = None
    anomaly_audits: Optional[Dict[str, Any]] = None


@dataclass
class ComprehensiveEvaluationReport:
    """Full multi-cutoff evaluation report spanning all cutoffs and metadata."""

    evaluation_id: str
    generated_at: str
    dataset_profile: str
    database_target: str
    k_values: List[int]
    windows_evaluated: List[WindowEvaluationResult] = field(default_factory=list)
    relevance_mapping_spec: Dict[int, str] = field(default_factory=dict)
    methodology_and_limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to nested dictionary."""
        return asdict(self)


class RecommendationEvaluationEngine:
    """Orchestrates temporal evaluation pipeline across learners, cutoffs, and metrics."""

    def __init__(
        self,
        session: Session,
        k_values: Tuple[int, ...] = (1, 3, 5, 10),
    ) -> None:
        self.session = session
        self.k_values = sorted(list(k_values))
        self.mastery_service = MasteryService(session)
        self.rec_service = RecommendationService(session, mastery_service=self.mastery_service)
        self.gt_extractor = GroundTruthExtractor(session, mastery_service=self.mastery_service)
        self.auditor = BusinessRuleAuditor(session, mastery_service=self.mastery_service)
        self.collector = EvaluationDataCollector(
            session=session,
            mastery_service=self.mastery_service,
            gt_extractor=self.gt_extractor,
            auditor=self.auditor,
        )

    def evaluate_window(self, window: TemporalWindow) -> WindowEvaluationResult:
        """Run complete evaluation for a single temporal window."""
        logger.info(
            "Evaluating temporal window: cutoff=%s, horizon=%s, partial=%s",
            window.cutoff.isoformat(),
            window.actual_horizon.isoformat(),
            window.is_partially_observed,
        )

        # 1. Identify active catalog items at cutoff T via collector
        catalog_snapshot: CatalogSnapshot = self.collector.collect_active_catalog(window.cutoff)
        active_catalog_set = catalog_snapshot.active_content_ids

        # 2. Collect learner cohort accounting and activity stratification via collector
        cohort_snapshot: LearnerCohortSnapshot = self.collector.collect_learner_cohorts(window.cutoff)
        all_learners = cohort_snapshot.all_learner_ids
        total_learners = cohort_snapshot.total_learners
        cold_start_lids = cohort_snapshot.cold_start_learner_ids
        activity_strata = cohort_snapshot.activity_strata

        # 3. Generate recommendations at cutoff T (persist=False) and track lineage
        max_k = max(self.k_values)
        learner_recs: Dict[str, List[str]] = {}
        lineage_evaluations: List[Tuple[str, str, datetime, List[str]]] = []

        for lid in all_learners:
            batch = self.rec_service.get_recommendations(
                learner_id=lid,
                cutoff_timestamp=window.cutoff,
                top_k=max_k,
                persist=False,
            )
            recs = [item.content_id for item in batch.items]
            learner_recs[lid] = recs

            # Extract lineage evidence used for historical mastery to audit leakage
            for item in batch.items:
                _, _, _, _, evidence_ids = self.mastery_service.compute_mastery(
                    learner_id=lid,
                    skill_id=item.target_skill_id,
                    cutoff_timestamp=window.cutoff,
                )
                lineage_evaluations.append((lid, item.target_skill_id, window.cutoff, evidence_ids))

        # 4. Extract ground truth in outcome window (cutoff, horizon] via collector
        gt_by_learner: Dict[str, LearnerInteractionSnapshot] = (
            self.collector.collect_all_learner_interactions(all_learners, window)
        )
        evaluated_lids = {
            lid for lid, snap in gt_by_learner.items() if len(snap.relevant_items) > 0
        }
        evaluated_count = len(evaluated_lids)
        excluded_count = total_learners - evaluated_count

        # Cold-start conversion metrics (Version 2.3)
        active_cold_start_lids = {
            lid for lid in cold_start_lids if len(gt_by_learner[lid].observed_items) > 0
        }
        converted_cold_start_lids = {
            lid for lid in cold_start_lids if len(gt_by_learner[lid].relevant_items) > 0
        }

        cs_overall, cs_cond, cs_diag = compute_cold_start_conversion(
            total_cold_start=len(cold_start_lids),
            active_cold_start=len(active_cold_start_lids),
            converted_cold_start=len(converted_cold_start_lids),
        )
        cold_start_conversion_block = ColdStartConversionSchema(
            total_cold_start=len(cold_start_lids),
            active_cold_start=len(active_cold_start_lids),
            converted_cold_start=len(converted_cold_start_lids),
            overall_conversion_rate=cs_overall,
            conditional_conversion_rate=cs_cond,
            diagnostic=cs_diag,
        ).model_dump()

        # Observational learning gain (Version 2.3)
        # Evaluated using earliest post-cutoff assessment
        learner_gains: List[Decimal] = []
        pre_masteries: List[Decimal] = []
        post_masteries: List[Decimal] = []

        for lid in evaluated_lids:
            snap = gt_by_learner[lid]
            if snap.earliest_post_cutoff_assessment:
                skill_id, graded_at, _ = snap.earliest_post_cutoff_assessment
                pre_m, _, _, _, _ = self.mastery_service.compute_mastery(
                    learner_id=lid,
                    skill_id=skill_id,
                    cutoff_timestamp=window.cutoff,
                )
                post_m, _, _, _, _ = self.mastery_service.compute_mastery(
                    learner_id=lid,
                    skill_id=skill_id,
                    cutoff_timestamp=graded_at,
                )
                gain = compute_observational_learning_gain(pre_m, post_m)
                if gain is not None and pre_m is not None and post_m is not None:
                    learner_gains.append(gain)
                    pre_masteries.append(pre_m)
                    post_masteries.append(post_m)

        mean_learning_gain = None
        mean_pre_m = None
        mean_post_m = None
        if learner_gains:
            FOUR_PLACES = Decimal("0.0001")
            mean_gain_dec = (sum(learner_gains) / Decimal(str(len(learner_gains)))).quantize(FOUR_PLACES)
            mean_pre_dec = (sum(pre_masteries) / Decimal(str(len(pre_masteries)))).quantize(FOUR_PLACES)
            mean_post_dec = (sum(post_masteries) / Decimal(str(len(post_masteries)))).quantize(FOUR_PLACES)
            mean_learning_gain = mean_gain_dec
            mean_pre_m = mean_pre_dec
            mean_post_m = mean_post_dec

        observational_learning_gain_block = ObservationalLearningGainSchema(
            pre_mastery=mean_pre_m,
            post_mastery=mean_post_m,
            learning_gain=mean_learning_gain,
        ).model_dump()

        # 5. Compute metrics across K values
        metrics_by_k: Dict[int, CutoffMetricSummary] = {}
        all_recs_list = list(learner_recs.values())

        # Map learner to stratum for stratification
        learner_to_stratum: Dict[str, str] = {}
        for s_name, lids in activity_strata.items():
            for lid in lids:
                learner_to_stratum[lid] = s_name

        primary_k = 5 if 5 in self.k_values else self.k_values[0]
        window_stratified_disparity_block = None

        for k in self.k_values:
            precisions = []
            recalls = []
            bounded_recalls = []
            legacy_ndcgs = []
            realized_precisions = []
            observed_precisions = []
            unobserved_rates = []
            ideal_pool_ndcgs = []

            # Per-stratum metric tracking (for realized precision)
            stratum_realized_precisions: Dict[str, List[float]] = defaultdict(list)

            for lid in evaluated_lids:
                snap = gt_by_learner[lid]
                recs = learner_recs[lid]

                # Legacy metrics
                p = compute_precision_at_k(recs, snap.relevant_items, k)
                precisions.append(p)

                r = compute_recall_at_k(recs, snap.relevant_items, k)
                if r is not None:
                    recalls.append(r)

                br = compute_bounded_recall_at_k(recs, snap.relevant_items, k)
                if br is not None:
                    bounded_recalls.append(br)

                legacy_ndcg = compute_ndcg_at_k(recs, snap.relevance_grades, k)
                if legacy_ndcg is not None:
                    legacy_ndcgs.append(legacy_ndcg)

                # Version 2.3 metrics
                rp = compute_realized_precision_at_k(recs, snap.relevant_items, k)
                realized_precisions.append(rp)

                st = learner_to_stratum.get(lid)
                if st:
                    stratum_realized_precisions[st].append(rp)

                op = compute_observed_precision_at_k(
                    recommended_items=recs,
                    relevant_items=snap.relevant_items,
                    observed_items=snap.observed_items,
                    k=k,
                )
                if op is not None:
                    observed_precisions.append(op)

                uer = compute_unobserved_exposure_rate_at_k(
                    recommended_items=recs,
                    observed_items=snap.observed_items,
                    k=k,
                )
                unobserved_rates.append(uer)

                ideal_ndcg = compute_ndcg_with_ideal_pool_at_k(
                    recommended_items=recs,
                    relevance_grades=snap.relevance_grades,
                    ideal_relevance_pool=snap.ideal_pool,
                    k=k,
                )
                if ideal_ndcg is not None:
                    ideal_pool_ndcgs.append(ideal_ndcg)

            # Catalog coverage and Gini at rank k
            freqs_k: Dict[str, int] = defaultdict(int)
            for rec_list in all_recs_list:
                for cid in rec_list[:k]:
                    freqs_k[cid] += 1

            cov = compute_catalog_coverage_at_k(all_recs_list, active_catalog_set, k)
            gini = compute_gini_coefficient(freqs_k, active_catalog_set)

            # Stratified activity disparity at rank k (Section 3.5.2)
            strata_disparity_input: Dict[str, Any] = {}
            for s_name in ("low", "med", "high"):
                s_vals = stratum_realized_precisions.get(s_name, [])
                eval_size = len(s_vals)
                total_size = len(activity_strata.get(s_name, []))
                s_metric = (sum(s_vals) / float(eval_size)) if eval_size > 0 else None
                strata_disparity_input[s_name] = (s_metric, eval_size, total_size)

            disparity_result = compute_stratified_disparity(
                strata=strata_disparity_input,
                min_evaluated_learners=5,
            )

            disparity_block = StratifiedActivityDisparityBlock(
                stratum_metrics=disparity_result["stratum_metrics"],
                stratum_sizes=disparity_result["stratum_sizes"],
                evaluated_stratum_sizes=disparity_result["evaluated_stratum_sizes"],
                absolute_disparity=disparity_result["absolute_disparity"],
                ratio_disparity=disparity_result["ratio_disparity"],
                diagnostic=disparity_result["diagnostic"],
            ).model_dump()

            if k == primary_k:
                window_stratified_disparity_block = disparity_block

            metrics_by_k[k] = CutoffMetricSummary(
                k=k,
                mean_precision=round(sum(precisions) / float(len(precisions)), 4) if precisions else 0.0,
                mean_standard_recall=round(sum(recalls) / float(len(recalls)), 4) if recalls else 0.0,
                mean_bounded_recall=round(sum(bounded_recalls) / float(len(bounded_recalls)), 4) if bounded_recalls else 0.0,
                mean_ndcg=round(sum(legacy_ndcgs) / float(len(legacy_ndcgs)), 4) if legacy_ndcgs else 0.0,
                catalog_coverage=round(cov, 4),
                gini_coefficient=round(gini, 4),
                evaluated_learners_count=evaluated_count,
                excluded_learners_count=excluded_count,
                mean_realized_precision=round(sum(realized_precisions) / float(len(realized_precisions)), 4) if realized_precisions else 0.0,
                mean_observed_precision=round(sum(observed_precisions) / float(len(observed_precisions)), 4) if observed_precisions else None,
                mean_unobserved_exposure_rate=round(sum(unobserved_rates) / float(len(unobserved_rates)), 4) if unobserved_rates else 0.0,
                mean_ndcg_ideal_pool=round(sum(ideal_pool_ndcgs) / float(len(ideal_pool_ndcgs)), 4) if ideal_pool_ndcgs else None,
                stratified_disparity=disparity_block,
            )

        # 6. Execute five read-only anomaly audits via collector
        anomaly_audits: Dict[str, AnomalyAuditResult] = self.collector.run_five_anomaly_audits(
            cutoff=window.cutoff,
            learner_recommendations=learner_recs,
            lineage_evaluations=lineage_evaluations,
        )

        anomaly_audits_summary = {
            "total_audits": len(anomaly_audits),
            "all_passed": all(a.passed for a in anomaly_audits.values()),
            "audits": {
                name: {
                    "audit_name": a.audit_name,
                    "anomaly_type": a.anomaly_type,
                    "passed": a.passed,
                    "total_checked": a.total_checked,
                    "violations_count": a.violations_count,
                    "details": a.details,
                    "metadata": a.metadata,
                }
                for name, a in anomaly_audits.items()
            },
        }

        # Backwards compatible audit dictionaries
        prereq_res = self.auditor.audit_prerequisite_compliance(learner_recs, window.cutoff)
        leakage_res = self.auditor.audit_temporal_leakage(lineage_evaluations)

        window_result = WindowEvaluationResult(
            cutoff=window.cutoff.isoformat(),
            planned_end=window.planned_end.isoformat(),
            actual_horizon=window.actual_horizon.isoformat(),
            is_partially_observed=window.is_partially_observed,
            total_learners=total_learners,
            evaluated_learners=evaluated_count,
            excluded_learners=excluded_count,
            cold_start_learners=len(cold_start_lids),
            active_catalog_size=len(active_catalog_set),
            metrics_by_k=metrics_by_k,
            prerequisite_audit=asdict(prereq_res),
            temporal_leakage_audit=asdict(leakage_res),
            cold_start_conversion=cold_start_conversion_block,
            observational_learning_gain=observational_learning_gain_block,
            stratified_disparity=window_stratified_disparity_block,
            anomaly_audits=anomaly_audits_summary,
        )

        # Validate result with Pydantic schema
        WindowEvaluationResultSchema.model_validate(asdict(window_result))

        return window_result

    def run_comprehensive_evaluation(
        self,
        windows: Optional[List[TemporalWindow]] = None,
    ) -> ComprehensiveEvaluationReport:
        """Execute full evaluation across all standard temporal windows and compile report."""
        eval_windows = windows or get_standard_evaluation_windows(self.session)
        now_utc = datetime.now(timezone.utc)
        eval_id = f"EVAL-{now_utc.strftime('%Y%m%d-%H%M%S')}"

        report = ComprehensiveEvaluationReport(
            evaluation_id=eval_id,
            generated_at=now_utc.isoformat(),
            dataset_profile="development",
            database_target="skillpath.db",
            k_values=self.k_values,
            relevance_mapping_spec={
                0: "Unobserved / Non-relevant (no completed interaction in outcome window)",
                1: "Engaged (completed content attempt in outcome window)",
                2: "Proficient (completed attempt with normalized score >= 0.70)",
                3: "Target Gap Closed (prior mastery < 0.70, assessment passed, and mastery improved)",
            },
            methodology_and_limitations=[
                "Temporal Isolation: Recommendations and historical mastery use evidence with timestamp <= T.",
                "Fixed-K Precision: Denominator is strictly K, penalizing incomplete recommendation lists.",
                "Realized Precision: Denominator is realized list length min(K, |recs|), accounting for prerequisite gating.",
                "External Ideal Pool NDCG: IDCG computed from complete outcome-window engagement pool.",
                "Observational Learning Gain: Hake-normalized delta evaluated using earliest post-cutoff assessment.",
                "Cold-Start Conversion: Evaluates conversion into active, proficient learners without prior history.",
                "Stratified Activity Disparity: Audits relative and absolute equity across low, med, high activity strata.",
                "Primary Recall: Denominator is |Relevant|, bounded Recall reported as auxiliary.",
                "Unobserved Interaction: Unobserved interaction reflects exposure limits, not proof of irrelevance.",
                "Causality Disclaimer: Retrospective alignment measures predictive correlation, not causal lift.",
                "Partially Observed Horizon: Windows extending past dataset max timestamp are flagged and bounded.",
            ],
        )

        for w in eval_windows:
            window_res = self.evaluate_window(w)
            report.windows_evaluated.append(window_res)

        # Validate comprehensive report with Pydantic schema
        ComprehensiveEvaluationReportSchema.model_validate(report.to_dict())

        return report

    def save_reports(
        self,
        report: ComprehensiveEvaluationReport,
        output_dir: Path | str = "data/reports",
    ) -> Tuple[Path, Path]:
        """Save JSON and Markdown evaluation reports."""
        out_dir = Path(output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        json_path = out_dir / f"recommendation_evaluation_{report.evaluation_id}.json"
        md_path = out_dir / f"recommendation_evaluation_{report.evaluation_id}.md"

        # 1. Save JSON report
        def _json_serializer(o: Any) -> Any:
            if isinstance(o, Decimal):
                return float(o)
            if isinstance(o, (datetime, Path)):
                return str(o)
            raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, default=_json_serializer)

        # 2. Save Markdown summary
        md_content = self._render_markdown_report(report)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        return json_path, md_path

    @staticmethod
    def _render_markdown_report(report: ComprehensiveEvaluationReport) -> str:
        """Render a clean Markdown summary report."""
        lines = [
            "# SkillPath AI — Recommendation Quality & Temporal Evaluation Report",
            "",
            f"**Evaluation ID:** `{report.evaluation_id}`  ",
            f"**Generated At:** `{report.generated_at}`  ",
            f"**Dataset Profile:** `{report.dataset_profile}` (`{report.database_target}`)  ",
            "",
            "---",
            "",
            "## 1. Relevance Mapping & Methodology Specifications",
            "",
            "| Grade | Level | Operational Definition in Outcome Window $(T, T + 30\\text{ days}]$ |",
            "|:---:|---|---|",
        ]
        for grade, desc in report.relevance_mapping_spec.items():
            lines.append(f"| **{grade}** | Grade {grade} | {desc} |")

        lines.extend([
            "",
            "### Methodology & Methodological Invariants:",
        ])
        for m in report.methodology_and_limitations:
            lines.append(f"- {m}")

        lines.extend([
            "",
            "---",
            "",
            "## 2. Multi-Cutoff Evaluation Results",
            "",
        ])

        for idx, w in enumerate(report.windows_evaluated, start=1):
            partial_str = " (⚠️ Partially Observed Horizon)" if w.is_partially_observed else ""
            lines.extend([
                f"### Window {idx}: Cutoff `{w.cutoff}`{partial_str}",
                "",
                f"- **Outcome Interval:** `{w.cutoff}` to `{w.actual_horizon}`",
                f"- **Planned End:** `{w.planned_end}` | **Truncated:** `{w.is_partially_observed}`",
                f"- **Learner Accounting:** Total = `{w.total_learners}`, Evaluated = `{w.evaluated_learners}`, Excluded = `{w.excluded_learners}`, Cold-Start = `{w.cold_start_learners}`",
                f"- **Active Catalog Size:** `{w.active_catalog_size}` items",
                "",
                "| Rank K | Precision@K | Realized Prec@K | Observed Prec@K | Exposure Rate | Std Recall@K | NDCG@K (Pool) | Coverage | Gini |",
                "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
            ])

            for k in sorted(w.metrics_by_k.keys()):
                m = w.metrics_by_k[k]
                obs_prec_str = f"{m.mean_observed_precision:.4f}" if m.mean_observed_precision is not None else "N/A"
                ndcg_pool_str = f"{m.mean_ndcg_ideal_pool:.4f}" if m.mean_ndcg_ideal_pool is not None else "N/A"
                lines.append(
                    f"| **@{k}** | {m.mean_precision:.4f} | {m.mean_realized_precision:.4f} | "
                    f"{obs_prec_str} | {m.mean_unobserved_exposure_rate:.4f} | "
                    f"{m.mean_standard_recall:.4f} | {ndcg_pool_str} | {m.catalog_coverage:.4f} | "
                    f"{m.gini_coefficient:.4f} |"
                )

            # Cold-start conversion
            cs = w.cold_start_conversion or {}
            cs_tot = cs.get("total_cold_start", 0)
            cs_act = cs.get("active_cold_start", 0)
            cs_conv = cs.get("converted_cold_start", 0)
            cs_ov = cs.get("overall_conversion_rate")
            cs_ov_str = f"{cs_ov:.4f}" if cs_ov is not None else "N/A"
            cs_cond = cs.get("conditional_conversion_rate")
            cs_cond_str = f"{cs_cond:.4f}" if cs_cond is not None else "N/A"
            cs_diag = cs.get("diagnostic") or "None"

            # Observational learning gain
            lg = w.observational_learning_gain or {}
            lg_val = lg.get("learning_gain")
            lg_str = f"{float(lg_val):.4f}" if lg_val is not None else "N/A"

            # Stratified activity disparity
            sd = w.stratified_disparity or {}
            sd_abs = sd.get("absolute_disparity")
            sd_abs_str = f"{sd_abs:.4f}" if sd_abs is not None else "N/A"
            sd_ratio = sd.get("ratio_disparity")
            sd_ratio_str = f"{sd_ratio:.4f}" if sd_ratio is not None else "N/A"
            sd_diag = sd.get("diagnostic") or "None"

            lines.extend([
                "",
                "#### Version 2.3 Diagnostic Dimensions:",
                f"- **Cold-Start Conversion:** Total={cs_tot}, Active={cs_act}, Converted={cs_conv} | "
                f"Overall Rate=`{cs_ov_str}`, Conditional Rate=`{cs_cond_str}` (Diagnostic: `{cs_diag}`)",
                f"- **Observational Learning Gain (Earliest Assessment):** `{lg_str}`",
                f"- **Stratified Activity Disparity (Rank @5):** Absolute=`{sd_abs_str}`, Ratio=`{sd_ratio_str}` (Diagnostic: `{sd_diag}`)",
            ])

            # Five anomaly audits
            anom = w.anomaly_audits or {}
            audits_dict = anom.get("audits", {})

            lines.extend([
                "",
                "#### Read-Only Business-Rule & Anomaly Audits:",
            ])
            for name, a in audits_dict.items():
                status_icon = "✅ PASS" if a.get("passed", False) else "❌ FAIL"
                lines.append(
                    f"- **{a.get('audit_name', name)} ({a.get('anomaly_type', '')}):** "
                    f"`{a.get('violations_count', 0)}` violations across `{a.get('total_checked', 0)}` checked — {status_icon}"
                )
            lines.append("")

        return "\n".join(lines) + "\n"
