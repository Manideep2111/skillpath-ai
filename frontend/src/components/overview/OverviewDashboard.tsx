import React, { useEffect, useState } from 'react';
import {
  BookOpen,
  CheckCircle2,
  Clock,
  Sparkles,
  BarChart2,
  RefreshCw,
  AlertCircle,
  TrendingUp,
  Target,
  ArrowRight,
} from 'lucide-react';
import { apiClient, ApiClientError } from '../../services/api/apiClient';
import { LearnerOverviewResponse } from '../../services/api/types';

interface OverviewDashboardProps {
  onNavigateTab?: (tab: string) => void;
}

export const OverviewDashboard: React.FC<OverviewDashboardProps> = ({ onNavigateTab }) => {
  const [selectedLearner, setSelectedLearner] = useState<string>('LRN-000001');
  const [data, setData] = useState<LearnerOverviewResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOverview = async (learnerId: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.getLearnerOverview(learnerId);
      setData(res);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.detail || err.message);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to query learner overview');
      }
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOverview(selectedLearner);
  }, [selectedLearner]);

  const handleLearnerChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedLearner(e.target.value);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Learner Selector & Welcome Header */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem' }}>
              <h2 className="card-title" style={{ marginBottom: 0 }}>
                {data ? `${data.first_name} ${data.last_name}` : 'Learner Dashboard'}
              </h2>
              {data && (
                <span
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    padding: '0.15rem 0.6rem',
                    borderRadius: '9999px',
                    background: 'rgba(59, 130, 246, 0.15)',
                    color: 'var(--accent-primary)',
                    border: '1px solid rgba(59, 130, 246, 0.3)',
                  }}
                >
                  {data.experience_level}
                </span>
              )}
            </div>
            <p className="card-subtitle" style={{ marginBottom: 0 }}>
              Track your competency progression, practice focus areas, and recent learning milestones.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <label style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Learner Profile:</label>
            <select
              className="form-select"
              value={selectedLearner}
              onChange={handleLearnerChange}
              style={{ minWidth: '190px' }}
            >
              <optgroup label="Standard Cohort">
                <option value="LRN-000001">LRN-000001 (Beginner)</option>
                <option value="LRN-000002">LRN-000002 (Intermediate)</option>
                <option value="LRN-000003">LRN-000003 (Advanced)</option>
                <option value="LRN-000005">LRN-000005</option>
                <option value="LRN-000010">LRN-000010</option>
              </optgroup>
              <optgroup label="Cold-Start Cohort">
                <option value="LRN-000091">LRN-000091 (Cold Start)</option>
                <option value="LRN-000095">LRN-000095 (Cold Start)</option>
                <option value="LRN-000100">LRN-000100 (Cold Start)</option>
              </optgroup>
            </select>
          </div>
        </div>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="card" style={{ textAlign: 'center', padding: '3.5rem' }}>
          <RefreshCw className="animate-spin" size={30} style={{ margin: '0 auto 0.75rem', color: 'var(--accent-primary)' }} />
          <p style={{ color: 'var(--text-muted)' }}>Loading learner profile and progression...</p>
        </div>
      )}

      {/* Error State */}
      {error && !loading && (
        <div className="card">
          <div className="alert alert-danger" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', margin: 0 }}>
            <AlertCircle size={20} />
            <div>
              <strong>Failed to Load Learner Overview</strong>
              <div style={{ fontSize: '0.85rem', marginTop: '0.2rem' }}>{error}</div>
            </div>
          </div>
        </div>
      )}

      {/* Content View */}
      {data && !loading && (
        <>
          {/* Progress Indicators Grid */}
          <div className="stats-grid" style={{ marginBottom: 0 }}>
            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' }}>
                <Target size={22} />
              </div>
              <div>
                <div className="stat-value">{data.total_attempts}</div>
                <div className="stat-label">Total Content Attempts</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981' }}>
                <CheckCircle2 size={22} />
              </div>
              <div>
                <div className="stat-value">{data.completed_attempts}</div>
                <div className="stat-label">Completed Activities</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b' }}>
                <TrendingUp size={22} />
              </div>
              <div>
                <div className="stat-value">
                  {data.average_score !== null ? `${(data.average_score * 100).toFixed(1)}%` : '—'}
                </div>
                <div className="stat-label">Average Assessment Score</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(139, 92, 246, 0.15)', color: '#8b5cf6' }}>
                <BookOpen size={22} />
              </div>
              <div>
                <div className="stat-value">{data.skills_practiced_count}</div>
                <div className="stat-label">Competency Skills Engaged</div>
              </div>
            </div>
          </div>

          {/* Two-Column Dashboard Layout */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.5rem' }}>
            {/* Left Column: Skills Needing Attention */}
            <div className="card">
              <h3 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                <BarChart2 size={18} style={{ color: 'var(--accent-primary)' }} />
                Skills Needing Attention
              </h3>
              <p className="card-subtitle" style={{ marginBottom: '1rem' }}>
                Target skills identified for mastery improvement based on recent assessment history.
              </p>

              {data.skills_needing_attention.length === 0 ? (
                <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                  No skill gaps recorded yet. Complete learning activities to establish point-in-time mastery baselines.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
                  {data.skills_needing_attention.map((skill) => {
                    const pct = Math.round(skill.mastery_score * 100);
                    const isProficient = pct >= 70;
                    return (
                      <div
                        key={skill.skill_id}
                        style={{
                          padding: '0.75rem 1rem',
                          background: 'var(--bg-base)',
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid var(--border-subtle)',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                          <div>
                            <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{skill.skill_name}</span>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginLeft: '0.5rem' }}>
                              ({skill.domain})
                            </span>
                          </div>
                          <span
                            style={{
                              fontSize: '0.75rem',
                              fontWeight: 700,
                              color: isProficient ? 'var(--accent-success)' : 'var(--accent-warning)',
                            }}
                          >
                            {pct}% Mastery
                          </span>
                        </div>

                        {/* Progress Bar */}
                        <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.08)', borderRadius: '3px', overflow: 'hidden' }}>
                          <div
                            style={{
                              width: `${pct}%`,
                              height: '100%',
                              background: isProficient ? 'var(--accent-success)' : 'var(--accent-warning)',
                              borderRadius: '3px',
                              transition: 'width 0.3s ease',
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Right Column: Recommended Next Activities (Preview) */}
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                <h3 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: 0 }}>
                  <Sparkles size={18} style={{ color: 'var(--accent-purple)' }} />
                  Recommended Next Activities
                </h3>
                {onNavigateTab && (
                  <button
                    onClick={() => onNavigateTab('recommendations')}
                    style={{
                      fontSize: '0.8rem',
                      color: 'var(--accent-primary)',
                      fontWeight: 600,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.25rem',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                    }}
                  >
                    View All <ArrowRight size={14} />
                  </button>
                )}
              </div>
              <p className="card-subtitle" style={{ marginBottom: '1rem' }}>
                Top learning activities tailored to current competency levels and prerequisite compliance.
              </p>

              {data.recommended_preview.length === 0 ? (
                <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                  No immediate recommendations available for this learner at the current cutoff.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
                  {data.recommended_preview.map((rec, idx) => (
                    <div
                      key={rec.content_id}
                      style={{
                        padding: '0.85rem 1rem',
                        background: 'var(--bg-base)',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: '0.75rem',
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 600, fontSize: '0.85rem', color: '#f8fafc' }}>
                          #{idx + 1} {rec.title}
                        </div>
                        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.35rem', flexWrap: 'wrap' }}>
                          <span
                            style={{
                              fontSize: '0.7rem',
                              padding: '0.1rem 0.4rem',
                              borderRadius: '3px',
                              background: 'rgba(16, 185, 129, 0.2)',
                              color: 'var(--accent-success)',
                              fontWeight: 600,
                            }}
                          >
                            &check; Eligible
                          </span>
                          <span className="badge badge-blue" style={{ fontSize: '0.7rem' }}>
                            {rec.primary_reason_code}
                          </span>
                        </div>
                      </div>

                      <div style={{ textAlign: 'right', flexShrink: 0 }}>
                        <div style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--accent-primary)', fontFamily: 'var(--font-mono)' }}>
                          {rec.score.toFixed(3)}
                        </div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>Match Score</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Recently Completed Activities */}
          <div className="card">
            <h3 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
              <Clock size={18} style={{ color: 'var(--accent-success)' }} />
              Recent Learning Activity
            </h3>
            <p className="card-subtitle" style={{ marginBottom: '1rem' }}>
              Recent interaction attempts and assessment milestones completed by this learner.
            </p>

            {data.recent_activities.length === 0 ? (
              <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                No interaction attempts recorded yet.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                      <th style={{ padding: '0.6rem 0.5rem' }}>Attempt ID</th>
                      <th style={{ padding: '0.6rem 0.5rem' }}>Content Activity</th>
                      <th style={{ padding: '0.6rem 0.5rem' }}>Status</th>
                      <th style={{ padding: '0.6rem 0.5rem' }}>Normalized Score</th>
                      <th style={{ padding: '0.6rem 0.5rem' }}>Started At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_activities.map((act) => (
                      <tr key={act.attempt_id} style={{ borderBottom: '1px solid rgba(51, 65, 85, 0.4)' }}>
                        <td style={{ padding: '0.6rem 0.5rem' }}>
                          <code>{act.attempt_id}</code>
                        </td>
                        <td style={{ padding: '0.6rem 0.5rem', fontWeight: 500 }}>
                          {act.content_title}
                        </td>
                        <td style={{ padding: '0.6rem 0.5rem' }}>
                          <span
                            style={{
                              fontSize: '0.7rem',
                              fontWeight: 600,
                              padding: '0.15rem 0.45rem',
                              borderRadius: '3px',
                              background: act.is_completed ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                              color: act.is_completed ? 'var(--accent-success)' : 'var(--accent-warning)',
                            }}
                          >
                            {act.is_completed ? 'COMPLETED' : 'IN PROGRESS'}
                          </span>
                        </td>
                        <td style={{ padding: '0.6rem 0.5rem', fontWeight: 600 }}>
                          {act.score !== null ? `${(act.score * 100).toFixed(1)}%` : '—'}
                        </td>
                        <td style={{ padding: '0.6rem 0.5rem', color: 'var(--text-dim)', fontSize: '0.8rem' }}>
                          {new Date(act.started_at).toLocaleDateString(undefined, {
                            month: 'short',
                            day: 'numeric',
                            year: 'numeric',
                          })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};
