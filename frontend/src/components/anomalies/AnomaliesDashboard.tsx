import React, { useEffect, useState } from 'react';
import {
  ShieldCheck,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  Database,
  Crosshair,
  FileText,
  CheckCircle2,
  ChevronDown,
  Lock,
} from 'lucide-react';
import { apiClient, ApiClientError } from '../../services/api/apiClient';
import { AnomalyStatusResponse, TypeEvaluationMetrics } from '../../services/api/types';

export const AnomaliesDashboard: React.FC = () => {
  const [data, setData] = useState<AnomalyStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = async (isSubtle = false) => {
    if (isSubtle) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const res = await apiClient.getAnomalyStatus();
      setData(res);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.detail || err.message);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to fetch anomaly status');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  if (loading) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '3.5rem' }}>
        <RefreshCw className="animate-spin" size={30} style={{ margin: '0 auto 0.75rem', color: 'var(--accent-primary)' }} />
        <p style={{ color: 'var(--text-muted)' }}>Running read-only baseline audits and benchmark evaluation...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="card">
        <div className="alert alert-danger" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <AlertTriangle size={20} />
          <div>
            <strong>Data Quality Audit Unavailable</strong>
            <div>{error || 'Unable to connect to anomaly detection services.'}</div>
          </div>
        </div>
        <button className="btn-primary" onClick={() => fetchStatus()} style={{ marginTop: '1rem' }}>
          <RefreshCw size={16} /> Retry
        </button>
      </div>
    );
  }

  const formatPct = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(Number(val))) return '—';
    return `${(Number(val) * 100).toFixed(1)}%`;
  };

  const formatRate = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(Number(val))) return '—';
    return Number(val).toFixed(4);
  };

  const anomalyTypeDescriptions: Record<string, { label: string; code: string; desc: string }> = {
    PREREQUISITE_VIOLATION: {
      label: 'Prerequisite Violation',
      code: 'A1',
      desc: 'Content recommendation when required prerequisite mastery is unmet (< 0.70).',
    },
    TIMESTAMP_ORDER_INVERSION: {
      label: 'Timestamp Order Inversion',
      code: 'A2',
      desc: 'Attempt sequence timestamps inverted or inconsistent with chronological order.',
    },
    NONEXISTENT_SKILL_REFERENCE: {
      label: 'Nonexistent Skill Reference',
      code: 'A3',
      desc: 'Content-skill mapping referencing missing or orphaned skill identifier.',
    },
    FUTURE_ATTEMPT_LEAKAGE: {
      label: 'Future Attempt Leakage',
      code: 'A4',
      desc: 'Mastery snapshot computed using attempts or assessments dated after cutoff T.',
    },
    LEARNING_PATH_LOOP: {
      label: 'Learning Path Loop',
      code: 'A5',
      desc: 'Learning path re-assigns content repeatedly at later sequences while incomplete.',
    },
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header Card */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h2 className="card-title" style={{ marginBottom: '0.25rem' }}>
              Data Quality &amp; Anomaly Detection
            </h2>
            <p className="card-subtitle" style={{ marginBottom: 0 }}>
              Dual-mode audit suite: production baseline database integrity verification and controlled synthetic benchmark evaluation.
            </p>
          </div>
          <button
            onClick={() => fetchStatus(true)}
            disabled={refreshing}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.35rem 0.75rem',
              borderRadius: 'var(--radius-sm)',
              fontSize: '0.8rem',
              background: 'var(--bg-base)',
              border: '1px solid var(--border-subtle)',
              color: 'var(--text-muted)',
              cursor: refreshing ? 'not-allowed' : 'pointer',
            }}
            title="Re-run read-only baseline audits and benchmark evaluation"
          >
            <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
            <span>{refreshing ? 'Auditing...' : 'Re-run Audits'}</span>
          </button>
        </div>
      </div>

      {/* SECTION A: Baseline Database Integrity Audit */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Database size={20} style={{ color: 'var(--accent-primary)' }} />
            <div>
              <h3 className="card-title" style={{ marginBottom: 0 }}>Section A: Baseline Database Integrity Audit</h3>
              <p className="card-subtitle" style={{ marginBottom: 0 }}>
                Verification that the production baseline dataset satisfies all five canonical SRS anomaly checks.
              </p>
            </div>
          </div>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.3rem 0.75rem',
              borderRadius: '9999px',
              fontSize: '0.8rem',
              fontWeight: 700,
              background: data.baseline_status === 'CLEAN' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
              color: data.baseline_status === 'CLEAN' ? 'var(--accent-success)' : 'var(--accent-danger)',
              border: `1px solid ${data.baseline_status === 'CLEAN' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)'}`,
            }}
          >
            <ShieldCheck size={15} />
            {data.baseline_status === 'CLEAN' ? 'BASELINE STATUS: CLEAN (0 VIOLATIONS)' : 'VIOLATIONS DETECTED'}
          </div>
        </div>

        {/* Baseline Audit Table */}
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                <th style={{ padding: '0.65rem 0.5rem' }}>Anomaly Category</th>
                <th style={{ padding: '0.65rem 0.5rem' }}>Code</th>
                <th style={{ padding: '0.65rem 0.5rem' }}>Records Checked</th>
                <th style={{ padding: '0.65rem 0.5rem' }}>Violations Detected</th>
                <th style={{ padding: '0.65rem 0.5rem' }}>Audit Status</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.baseline_audits).map(([key, audit]) => {
                const meta = anomalyTypeDescriptions[audit.anomaly_type] || {
                  label: audit.audit_name,
                  code: 'SRS',
                  desc: '',
                };

                return (
                  <tr key={key} style={{ borderBottom: '1px solid rgba(51, 65, 85, 0.4)' }}>
                    <td style={{ padding: '0.65rem 0.5rem' }}>
                      <div style={{ fontWeight: 600 }}>{meta.label}</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>{meta.desc}</div>
                    </td>
                    <td style={{ padding: '0.65rem 0.5rem' }}>
                      <span
                        style={{
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          padding: '0.15rem 0.45rem',
                          borderRadius: '3px',
                          background: 'rgba(59, 130, 246, 0.2)',
                          color: 'var(--accent-primary)',
                        }}
                      >
                        {meta.code}
                      </span>
                    </td>
                    <td style={{ padding: '0.65rem 0.5rem', fontWeight: 600 }}>
                      {audit.total_checked.toLocaleString()}
                    </td>
                    <td style={{ padding: '0.65rem 0.5rem', color: audit.violations_count === 0 ? 'var(--accent-success)' : 'var(--accent-danger)', fontWeight: 600 }}>
                      {audit.violations_count}
                    </td>
                    <td style={{ padding: '0.65rem 0.5rem' }}>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem', color: audit.passed ? 'var(--accent-success)' : 'var(--accent-danger)', fontWeight: 600, fontSize: '0.8rem' }}>
                        {audit.passed ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
                        <span>{audit.passed ? 'PASS' : 'FAIL'}</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* SECTION B: Controlled Synthetic Benchmark */}
      {data.sandbox_evaluation && (
        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
            <Crosshair size={20} style={{ color: 'var(--accent-purple)' }} />
            <div>
              <h3 className="card-title" style={{ marginBottom: 0 }}>Section B: Controlled Synthetic Benchmark (Isolated Sandbox)</h3>
              <p className="card-subtitle" style={{ marginBottom: 0 }}>
                Detector sensitivity and accuracy verification evaluated against known ground-truth labels.
              </p>
            </div>
          </div>

          <div
            style={{
              padding: '0.75rem 1rem',
              background: 'rgba(139, 92, 246, 0.08)',
              border: '1px solid rgba(139, 92, 246, 0.25)',
              borderRadius: 'var(--radius-sm)',
              fontSize: '0.8rem',
              color: '#c4b5fd',
              marginBottom: '1.25rem',
            }}
          >
            <strong>Sandbox Benchmark Purpose:</strong> Because the clean baseline dataset contains zero violations (100% clean),
            detector accuracy is tested against an isolated synthetic testbed where canonical anomalies were injected and evaluated against ground-truth labels.
            <div style={{ marginTop: '0.35rem', fontSize: '0.75rem', color: '#e2e8f0' }}>
              Micro-averaged metrics: <code>Ground Truth = TP + FN</code> | <code>Detected = TP + FP</code> | <code>Precision = TP / Detected</code> | <code>Recall = TP / Ground Truth</code> | <code>F1 = 2PR / (P + R)</code>
            </div>
          </div>

          {/* Sandbox Headline Metrics Grid */}
          <div className="stats-grid" style={{ marginBottom: '1.5rem' }}>
            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' }}>
                <FileText size={22} />
              </div>
              <div>
                <div className="stat-value">{data.sandbox_evaluation.total_ground_truth}</div>
                <div className="stat-label">Ground Truth (TP+FN)</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(139, 92, 246, 0.15)', color: '#8b5cf6' }}>
                <Crosshair size={22} />
              </div>
              <div>
                <div className="stat-value">{data.sandbox_evaluation.total_detected}</div>
                <div className="stat-label">Detected (TP+FP)</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981' }}>
                <CheckCircle size={22} />
              </div>
              <div>
                <div className="stat-value">{data.sandbox_evaluation.true_positives}</div>
                <div className="stat-label">True Positives (TP)</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981' }}>
                <CheckCircle size={22} />
              </div>
              <div>
                <div className="stat-value">{formatPct(data.sandbox_evaluation.precision)}</div>
                <div className="stat-label">Precision (TP / Det)</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8' }}>
                <CheckCircle2 size={22} />
              </div>
              <div>
                <div className="stat-value">{formatPct(data.sandbox_evaluation.recall)}</div>
                <div className="stat-label">Recall (TP / GT)</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b' }}>
                <ShieldCheck size={22} />
              </div>
              <div>
                <div className="stat-value">{formatPct(data.sandbox_evaluation.f1_score)}</div>
                <div className="stat-label">F1-Score ({formatRate(data.sandbox_evaluation.f1_score)})</div>
              </div>
            </div>
          </div>

          {/* Breakdown Table By Anomaly Type */}
          <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.75rem', color: 'var(--text-main)' }}>
            Benchmark Breakdown by SRS Anomaly Category
          </h4>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '0.75rem 0.5rem' }}>SRS Anomaly Category</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Code</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Ground Truth</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Detected</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>TP</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>FP</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>FN</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Precision</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Recall</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>F1-Score</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.sandbox_evaluation.by_type).map(([typeName, metrics]: [string, TypeEvaluationMetrics]) => {
                  const meta = anomalyTypeDescriptions[typeName] || {
                    label: typeName,
                    code: 'SRS',
                    desc: '',
                  };

                  return (
                    <tr
                      key={typeName}
                      style={{ borderBottom: '1px solid rgba(51, 65, 85, 0.4)' }}
                    >
                      <td style={{ padding: '0.65rem 0.5rem' }}>
                        <div style={{ fontWeight: 600 }}>{meta.label}</div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>{meta.desc}</div>
                      </td>
                      <td style={{ padding: '0.65rem 0.5rem' }}>
                        <span
                          style={{
                            fontSize: '0.75rem',
                            fontWeight: 700,
                            padding: '0.15rem 0.45rem',
                            borderRadius: '3px',
                            background: 'rgba(139, 92, 246, 0.2)',
                            color: '#a78bfa',
                          }}
                        >
                          {meta.code}
                        </span>
                      </td>
                      <td style={{ padding: '0.65rem 0.5rem', fontWeight: 600 }}>{metrics.ground_truth_count}</td>
                      <td style={{ padding: '0.65rem 0.5rem', fontWeight: 600 }}>{metrics.detected_count}</td>
                      <td style={{ padding: '0.65rem 0.5rem', color: 'var(--accent-success)', fontWeight: 600 }}>{metrics.true_positives}</td>
                      <td style={{ padding: '0.65rem 0.5rem' }}>{metrics.false_positives}</td>
                      <td style={{ padding: '0.65rem 0.5rem' }}>{metrics.false_negatives}</td>
                      <td style={{ padding: '0.65rem 0.5rem', color: 'var(--accent-success)', fontWeight: 600 }}>
                        {formatPct(metrics.precision)}
                      </td>
                      <td style={{ padding: '0.65rem 0.5rem', color: 'var(--accent-success)', fontWeight: 600 }}>
                        {formatPct(metrics.recall)}
                      </td>
                      <td style={{ padding: '0.65rem 0.5rem', color: 'var(--accent-primary)', fontWeight: 700 }}>
                        {formatPct(metrics.f1_score)} <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontWeight: 'normal' }}>({formatRate(metrics.f1_score)})</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Expandable Technical Details */}
      <details className="card" style={{ padding: '1rem 1.25rem' }}>
        <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.5rem', outline: 'none' }}>
          <ChevronDown size={16} />
          <span>Technical Environment &amp; Audit Specifications (Click to Expand)</span>
        </summary>
        <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.85rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Lock size={15} style={{ color: 'var(--accent-success)' }} />
            <span>Read-Only Connection Setting: <code>PRAGMA query_only = ON;</code></span>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Baseline Database: </span>
            <code>{data.baseline_database}</code>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Sandbox Database: </span>
            <code>{data.sandbox_database || 'skillpath_anomaly_sandbox.db'}</code>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Ground Truth Labels: </span>
            <code>{data.ground_truth_file || 'anomaly_labels.csv'}</code>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Baseline SHA-256 Invariant: </span>
            <code style={{ fontSize: '0.75rem' }}>252331E11EA93056AA6DAEBAB1AFAB8F75B00354B4628B30671E65C5E790E3D2</code>
          </div>
          <p style={{ color: 'var(--text-dim)', fontSize: '0.75rem', margin: 0, marginTop: '0.25rem' }}>
            Safety Guarantee: All baseline integrity checks connect with query_only=ON and never issue write, update, or delete commands.
          </p>
        </div>
      </details>
    </div>
  );
};
