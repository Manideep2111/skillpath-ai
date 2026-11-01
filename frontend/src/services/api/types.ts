/**
 * TypeScript definitions for SkillPath AI API requests and responses.
 * Strictly aligned with FastAPI Pydantic schemas in src/schemas/recommendations.py.
 */

export interface HealthResponse {
  status: 'healthy' | 'unhealthy';
  database: 'connected' | 'disconnected';
  app_name: string;
  version: string;
}

export interface SystemSummaryResponse {
  status: 'healthy' | 'unhealthy' | string;
  database: 'connected' | 'disconnected' | string;
  database_file: string;
  app_name: string;
  version: string;
  learners_count: number;
  skills_count: number;
  courses_count: number;
  content_items_count: number;
  attempts_count: number;
  assessment_results_count: number;
  learning_paths_count: number;
}

export interface ScoreComponents {
  gap: string | number;
  difficulty_suitability: string | number;
  path_alignment: string | number;
  practice_urgency: string | number;
  total: string | number;
}

export interface RecommendedItem {
  content_id: string;
  title: string;
  score: string | number;
  score_components: ScoreComponents;
  target_skill_id: string;
  reason_codes: string[];
  primary_reason_code: string;
  recommendation_id?: string | null;
}

export interface RejectionSummary {
  inactive_content: number;
  unpublished_content: number;
  recent_completions: number;
  prerequisite_blocked: number;
  no_relevant_skill_gap: number;
  future_content: number;
  skill_already_mastered: number;
}

export interface LearnerSkillOverview {
  skill_id: string;
  skill_name: string;
  domain: string;
  mastery_score: number;
  confidence: number;
}

export interface LearnerRecentActivity {
  attempt_id: string;
  content_id: string;
  content_title: string;
  score: number | null;
  is_completed: boolean;
  started_at: string;
  completed_at: string | null;
}

export interface LearnerRecommendedPreview {
  content_id: string;
  title: string;
  target_skill_id: string;
  score: number;
  difficulty_match: number;
  primary_reason_code: string;
}

export interface LearnerOverviewResponse {
  learner_id: string;
  first_name: string;
  last_name: string;
  experience_level: string;
  total_attempts: number;
  completed_attempts: number;
  in_progress_attempts: number;
  average_score: number | null;
  skills_practiced_count: number;
  skills_needing_attention: LearnerSkillOverview[];
  recent_activities: LearnerRecentActivity[];
  recommended_preview: LearnerRecommendedPreview[];
}


export interface RecommendationResponse {
  learner_id: string;
  cutoff_timestamp: string;
  items: RecommendedItem[];
  rejection_summary: RejectionSummary;
}

export type OutcomeStatus =
  | 'RECOMMENDED'
  | 'STARTED'
  | 'COMPLETED'
  | 'ABANDONED'
  | 'IMPROVED'
  | 'NO_IMPROVEMENT';

export interface RecommendationOutcomeResponse {
  outcome_id: string;
  recommendation_id: string;
  outcome_status: OutcomeStatus;
  interaction_attempt_id: string | null;
  mastery_delta: string | number | null;
  recorded_at: string;
}

export interface StartRecommendationRequest {
  attempt_id: string;
  started_at?: string | null;
}

export interface CompleteRecommendationRequest {
  completed_at?: string | null;
}

export interface AbandonRecommendationRequest {
  abandoned_at?: string | null;
}

export interface ApiErrorDetail {
  detail: string;
  error_code?: string | null;
}

export interface ApiState<T> {
  data: T | null;
  isLoading: boolean;
  error: string | null;
}

// --- Evaluation & Quality Types (Version 2.3) ---

export interface ColdStartConversion {
  total_cold_start: number;
  active_cold_start: number;
  converted_cold_start: number;
  overall_conversion_rate: number | null;
  conditional_conversion_rate: number | null;
  diagnostic: string | null;
}

export interface ObservationalLearningGain {
  pre_mastery: number | string | null;
  post_mastery: number | string | null;
  learning_gain: number | string | null;
}

export interface StratifiedActivityDisparityBlock {
  stratum_metrics: Record<string, number | null>;
  stratum_sizes: Record<string, number>;
  evaluated_stratum_sizes: Record<string, number>;
  absolute_disparity: number | null;
  ratio_disparity: number | null;
  diagnostic: string | null;
}

export interface CutoffMetricSummary {
  k: number;
  mean_precision: number;
  mean_standard_recall: number;
  mean_bounded_recall: number;
  mean_ndcg: number;
  catalog_coverage: number;
  gini_coefficient: number;
  evaluated_learners_count: number;
  excluded_learners_count: number;
  mean_realized_precision: number;
  mean_observed_precision: number | null;
  mean_unobserved_exposure_rate: number;
  mean_ndcg_ideal_pool: number | null;
  stratified_disparity?: StratifiedActivityDisparityBlock | null;
}

export interface AnomalyAuditItem {
  audit_name: string;
  anomaly_type: string;
  passed: boolean;
  total_checked: number;
  violations_count: number;
  details: Array<Record<string, any>>;
  metadata: Record<string, any>;
}

export interface WindowEvaluationResult {
  cutoff: string;
  planned_end: string;
  actual_horizon: string;
  is_partially_observed: boolean;
  total_learners: number;
  evaluated_learners: number;
  excluded_learners: number;
  cold_start_learners: number;
  active_catalog_size: number;
  metrics_by_k: Record<string | number, CutoffMetricSummary>;
  prerequisite_audit?: Record<string, any> | null;
  temporal_leakage_audit?: Record<string, any> | null;
  cold_start_conversion?: ColdStartConversion | null;
  observational_learning_gain?: ObservationalLearningGain | null;
  stratified_disparity?: StratifiedActivityDisparityBlock | null;
  anomaly_audits?: {
    total_audits: number;
    all_passed: boolean;
    audits: Record<string, AnomalyAuditItem>;
  } | null;
}

export interface ComprehensiveEvaluationReport {
  evaluation_id: string;
  generated_at: string;
  dataset_profile: string;
  database_target: string;
  k_values: number[];
  windows_evaluated: WindowEvaluationResult[];
  relevance_mapping_spec: Record<string | number, string>;
  methodology_and_limitations: string[];
}

// --- Anomaly Benchmark Types ---

export interface TypeEvaluationMetrics {
  anomaly_type: string;
  ground_truth_count: number;
  detected_count: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  precision: number;
  recall: number;
  f1_score: number;
}

export interface SandboxEvaluationSummary {
  total_ground_truth: number;
  total_detected: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  precision: number;
  recall: number;
  f1_score: number;
  by_type: Record<string, TypeEvaluationMetrics>;
}

export interface AnomalyStatusResponse {
  baseline_status: 'CLEAN' | 'VIOLATIONS_DETECTED' | string;
  baseline_database: string;
  total_baseline_violations: number;
  baseline_audits: Record<string, AnomalyAuditItem>;
  sandbox_evaluation?: SandboxEvaluationSummary | null;
  sandbox_database?: string | null;
  ground_truth_file?: string | null;
}

