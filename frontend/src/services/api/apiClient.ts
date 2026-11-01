/**
 * Reusable HTTP API client for SkillPath AI.
 * Handles base URL configuration, typed payloads, network failures, and HTTP errors.
 */

import {
  ApiErrorDetail,
  CompleteRecommendationRequest,
  HealthResponse,
  SystemSummaryResponse,
  RecommendationOutcomeResponse,
  RecommendationResponse,
  StartRecommendationRequest,
  AbandonRecommendationRequest,
  ComprehensiveEvaluationReport,
  AnomalyStatusResponse,
  LearnerOverviewResponse,
} from './types';

// Read API base URL from Vite environment variables (fallback to localhost:8000)
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');

export class ApiClientError extends Error {
  public statusCode?: number;
  public detail?: string;
  public errorCode?: string;

  constructor(message: string, statusCode?: number, detail?: string, errorCode?: string) {
    super(message);
    this.name = 'ApiClientError';
    this.statusCode = statusCode;
    this.detail = detail;
    this.errorCode = errorCode;
  }
}

/**
 * Core generic fetch wrapper with error decoding and timeout handling.
 */
async function apiFetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

  const headers: Record<string, string> = {
    'Accept': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (options.body && typeof options.body === 'string' && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
    });
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : 'Unknown network error';
    throw new ApiClientError(
      `Network connection to SkillPath AI backend failed (${url}): ${errorMsg}. Please ensure the FastAPI server is running.`,
      undefined,
      errorMsg
    );
  }

  // Handle successful 2xx responses
  if (response.ok) {
    if (response.status === 204) {
      return {} as T;
    }
    try {
      return await response.json();
    } catch {
      return {} as T;
    }
  }

  // Handle HTTP error responses
  let errorDetail = `HTTP ${response.status} ${response.statusText}`;
  let errorCode: string | undefined;

  try {
    const errorJson: ApiErrorDetail | { detail: string | unknown[] } = await response.json();
    if (typeof errorJson.detail === 'string') {
      errorDetail = errorJson.detail;
    } else if (Array.isArray(errorJson.detail)) {
      // Pydantic validation errors (422)
      errorDetail = errorJson.detail
        .map((e: any) => `${e.loc?.join('.') || 'param'}: ${e.msg}`)
        .join('; ');
    }
    if ('error_code' in errorJson && typeof errorJson.error_code === 'string') {
      errorCode = errorJson.error_code;
    }
  } catch {
    // If response body is not JSON, use default status text
  }

  throw new ApiClientError(errorDetail, response.status, errorDetail, errorCode);
}

/**
 * SkillPath AI API Service Methods
 */
export const apiClient = {
  getBaseUrl(): string {
    return API_BASE_URL;
  },

  /**
   * System health check and database connectivity probe.
   * GET /api/v1/health (or fallback /health)
   */
  async getHealth(): Promise<HealthResponse> {
    return apiFetch<HealthResponse>('/api/v1/health');
  },

  /**
   * Fetch personalized recommendations for a learner.
   * GET /api/v1/learners/{learner_id}/recommendations
   */
  async getRecommendations(
    learnerId: string,
    params: {
      cutoffTimestamp?: string;
      topK?: number;
      persist?: boolean;
    } = {}
  ): Promise<RecommendationResponse> {
    const searchParams = new URLSearchParams();
    if (params.cutoffTimestamp) {
      searchParams.set('cutoff_timestamp', params.cutoffTimestamp);
    }
    if (params.topK !== undefined) {
      searchParams.set('top_k', params.topK.toString());
    }
    if (params.persist !== undefined) {
      searchParams.set('persist', params.persist.toString());
    }

    const query = searchParams.toString();
    const endpoint = `/api/v1/learners/${encodeURIComponent(learnerId)}/recommendations${query ? `?${query}` : ''}`;
    return apiFetch<RecommendationResponse>(endpoint);
  },

  /**
   * Fetch learner progression overview, skills needing attention, and recent activity.
   * GET /api/v1/learners/{learner_id}/overview
   */
  async getLearnerOverview(learnerId: string): Promise<LearnerOverviewResponse> {
    return apiFetch<LearnerOverviewResponse>(`/api/v1/learners/${encodeURIComponent(learnerId)}/overview`);
  },

  /**
   * Record recommendation interaction start.
   * POST /api/v1/recommendations/{recommendation_id}/start
   */
  async startRecommendation(
    recommendationId: string,
    request: StartRecommendationRequest
  ): Promise<RecommendationOutcomeResponse> {
    return apiFetch<RecommendationOutcomeResponse>(
      `/api/v1/recommendations/${encodeURIComponent(recommendationId)}/start`,
      {
        method: 'POST',
        body: JSON.stringify(request),
      }
    );
  },

  /**
   * Record recommendation completion.
   * POST /api/v1/recommendations/{recommendation_id}/complete
   */
  async completeRecommendation(
    recommendationId: string,
    request: CompleteRecommendationRequest = {}
  ): Promise<RecommendationOutcomeResponse> {
    return apiFetch<RecommendationOutcomeResponse>(
      `/api/v1/recommendations/${encodeURIComponent(recommendationId)}/complete`,
      {
        method: 'POST',
        body: JSON.stringify(request),
      }
    );
  },

  /**
   * Record recommendation abandonment.
   * POST /api/v1/recommendations/{recommendation_id}/abandon
   */
  async abandonRecommendation(
    recommendationId: string,
    request: AbandonRecommendationRequest = {}
  ): Promise<RecommendationOutcomeResponse> {
    return apiFetch<RecommendationOutcomeResponse>(
      `/api/v1/recommendations/${encodeURIComponent(recommendationId)}/abandon`,
      {
        method: 'POST',
        body: JSON.stringify(request),
      }
    );
  },

  /**
   * Evaluate learning gain and outcome transition (IMPROVED vs NO_IMPROVEMENT).
   * POST /api/v1/recommendations/{recommendation_id}/evaluate
   */
  async evaluateRecommendation(
    recommendationId: string
  ): Promise<RecommendationOutcomeResponse> {
    return apiFetch<RecommendationOutcomeResponse>(
      `/api/v1/recommendations/${encodeURIComponent(recommendationId)}/evaluate`,
      {
        method: 'POST',
      }
    );
  },

  /**
   * Fetch the latest comprehensive recommendation evaluation report.
   * GET /api/v1/evaluation/latest
   */
  async getLatestEvaluationReport(): Promise<ComprehensiveEvaluationReport> {
    return apiFetch<ComprehensiveEvaluationReport>('/api/v1/evaluation/latest');
  },

  /**
   * Fetch data quality audit status and sandbox anomaly evaluation metrics.
   * GET /api/v1/anomalies/status
   */
  async getAnomalyStatus(): Promise<AnomalyStatusResponse> {
    return apiFetch<AnomalyStatusResponse>('/api/v1/anomalies/status');
  },

  /**
   * Fetch live system health and dataset entity summary.
   * GET /api/v1/system/summary
   */
  async getSystemSummary(): Promise<SystemSummaryResponse> {
    return apiFetch<SystemSummaryResponse>('/api/v1/system/summary');
  },
};
