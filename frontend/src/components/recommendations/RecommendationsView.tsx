import React, { useState } from 'react';
import {
  Sparkles,
  AlertCircle,
  ShieldCheck,
  RefreshCw,
  Info,
  BookOpen,
  CheckCircle,
} from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from 'recharts';
import { apiClient, ApiClientError } from '../../services/api/apiClient';
import { RecommendationResponse, RecommendedItem } from '../../services/api/types';

export const RecommendationsView: React.FC = () => {
  const [selectedLearner, setSelectedLearner] = useState<string>('LRN-000001');
  const [topK, setTopK] = useState<number>(5);
  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedItem, setSelectedItem] = useState<RecommendedItem | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  const fetchRecommendations = async () => {
    setLoading(true);
    setError(null);
    setActionNotice(null);
    try {
      const res = await apiClient.getRecommendations(selectedLearner, {
        topK,
        persist: false,
      });
      setData(res);
      if (res.items && res.items.length > 0) {
        setSelectedItem(res.items[0]);
      } else {
        setSelectedItem(null);
      }
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.detail || err.message);
      } else {
        setError(err instanceof Error ? err.message : 'Unknown error occurred');
      }
      setData(null);
      setSelectedItem(null);
    } finally {
      setLoading(false);
    }
  };

  // Prepare score component breakdown for Recharts
  const scoreChartData = selectedItem
    ? [
        { name: 'Skill Gap (0.40)', value: Number(selectedItem.score_components.gap), weight: '40%', color: '#3b82f6' },
        { name: 'Difficulty (0.25)', value: Number(selectedItem.score_components.difficulty_suitability), weight: '25%', color: '#10b981' },
        { name: 'Path Align (0.20)', value: Number(selectedItem.score_components.path_alignment), weight: '20%', color: '#8b5cf6' },
        { name: 'Practice Urgency (0.15)', value: Number(selectedItem.score_components.practice_urgency), weight: '15%', color: '#f59e0b' },
      ]
    : [];

  const handleStartActivity = (item: RecommendedItem) => {
    setActionNotice(`Started learning activity "${item.title}" (${item.content_id}). Prerequisite validation confirmed.`);
    setTimeout(() => setActionNotice(null), 5000);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header Card */}
      <div className="card">
        <h2 className="card-title">Your Next Learning Activities</h2>
        <p className="card-subtitle">
          Personalized learning activities suited to your current skills, progress, and learning goals.
        </p>

        {/* Controls */}
        <div className="control-row">
          <div className="input-group">
            <label className="input-label">Select Learner</label>
            <select
              className="form-select"
              value={selectedLearner}
              onChange={(e) => setSelectedLearner(e.target.value)}
            >
              <optgroup label="Standard Evaluated Cohort">
                <option value="LRN-000001">LRN-000001 (Beginner)</option>
                <option value="LRN-000002">LRN-000002 (Intermediate)</option>
                <option value="LRN-000003">LRN-000003 (Advanced)</option>
                <option value="LRN-000005">LRN-000005</option>
                <option value="LRN-000010">LRN-000010</option>
                <option value="LRN-000025">LRN-000025</option>
              </optgroup>
              <optgroup label="Cold-Start Cohort (0 prior attempts)">
                <option value="LRN-000091">LRN-000091 (Cold Start)</option>
                <option value="LRN-000095">LRN-000095 (Cold Start)</option>
                <option value="LRN-000100">LRN-000100 (Cold Start)</option>
              </optgroup>
            </select>
          </div>

          <div className="input-group">
            <label className="input-label">Top-K Recommendations</label>
            <select
              className="form-select"
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            >
              <option value={3}>Top 3</option>
              <option value={5}>Top 5</option>
              <option value={10}>Top 10</option>
            </select>
          </div>

          <button
            className="btn-primary"
            onClick={fetchRecommendations}
            disabled={loading}
          >
            {loading ? <RefreshCw className="animate-spin" size={16} /> : <Sparkles size={16} />}
            {loading ? 'Evaluating...' : 'Get Next Activities'}
          </button>
        </div>
      </div>

      {/* Action Notification Banner */}
      {actionNotice && (
        <div className="alert" style={{ background: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.35)', color: 'var(--accent-success)', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
          <CheckCircle size={16} />
          <span>{actionNotice}</span>
        </div>
      )}

      {/* Loading State Banner */}
      {loading && (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <RefreshCw className="animate-spin" size={28} style={{ margin: '0 auto 0.75rem', color: 'var(--accent-primary)' }} />
          <p style={{ color: 'var(--text-muted)' }}>Evaluating prerequisite compliance and computing multi-factor ranking scores...</p>
        </div>
      )}

      {/* Error State Banner */}
      {error && !loading && (
        <div className="card">
          <div className="alert alert-danger" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', margin: 0 }}>
            <AlertCircle size={20} style={{ flexShrink: 0 }} />
            <div>
              <strong>Failed to Generate Recommendations</strong>
              <div style={{ fontSize: '0.85rem', marginTop: '0.2rem' }}>{error}</div>
            </div>
          </div>
        </div>
      )}

      {/* Results View */}
      {data && !loading && (
        <div>
          {/* Prerequisite & Decision Context Bar */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '0.75rem 1.25rem',
              background: 'rgba(30, 41, 59, 0.6)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              marginBottom: '1.25rem',
              flexWrap: 'wrap',
              gap: '0.75rem',
              fontSize: '0.85rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <span style={{ color: 'var(--text-muted)' }}>
                Decision Horizon Cutoff: <code style={{ color: 'var(--text-main)' }}>{data.cutoff_timestamp}</code>
              </span>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.15rem 0.5rem',
                  borderRadius: '3px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  background: 'rgba(16, 185, 129, 0.2)',
                  color: 'var(--accent-success)',
                  border: '1px solid rgba(16, 185, 129, 0.35)',
                }}
              >
                <ShieldCheck size={13} />
                Prerequisite Gating: ACTIVE
              </span>
            </div>

            <div style={{ display: 'flex', gap: '1rem', color: 'var(--text-dim)', fontSize: '0.8rem' }}>
              <span>Prerequisites Blocked: <strong style={{ color: 'var(--accent-warning)' }}>{data.rejection_summary.prerequisite_blocked}</strong></span>
              <span>Recent Completed: <strong>{data.rejection_summary.recent_completions}</strong></span>
              <span>No Skill Gap: <strong>{data.rejection_summary.no_relevant_skill_gap}</strong></span>
            </div>
          </div>

          {/* Empty State */}
          {data.items.length === 0 ? (
            <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
              <Info size={30} style={{ margin: '0 auto 0.5rem', color: 'var(--accent-primary)' }} />
              <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>No Eligible Recommendations Available</h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '0.35rem', maxWidth: '500px', margin: '0.35rem auto 0' }}>
                All candidate items either have unmet prerequisites (mastery &lt; 0.70 required), have been recently completed, or lack relevant knowledge gaps for learner {data.learner_id}.
              </p>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(360px, 1.25fr) minmax(320px, 1fr)', gap: '1.5rem' }}>
              {/* Ranked Activities List */}
              <div className="rec-list">
                {data.items.map((item, idx) => {
                  const isSelected = selectedItem?.content_id === item.content_id;
                  const diffVal = Number(item.score_components.difficulty_suitability);
                  const diffTier = diffVal >= 0.7 ? 'Optimal Match' : diffVal >= 0.4 ? 'Moderate' : 'Foundational';

                  return (
                    <div
                      key={item.content_id}
                      className="rec-item"
                      style={{
                        cursor: 'pointer',
                        borderColor: isSelected ? 'var(--accent-primary)' : 'var(--border-subtle)',
                        background: isSelected ? 'rgba(59, 130, 246, 0.1)' : 'rgba(15, 23, 42, 0.6)',
                        transition: 'all 0.15s ease',
                      }}
                      onClick={() => setSelectedItem(item)}
                    >
                      <div className="rec-rank">#{idx + 1}</div>
                      <div className="rec-details">
                        <div className="rec-title">{item.title}</div>
                        <div className="rec-meta">
                          <span>Content ID: <code>{item.content_id}</code></span>
                          <span>Target Skill: <code>{item.target_skill_id}</code></span>
                        </div>

                        {/* Badges: Prerequisite, Difficulty, Reason Codes */}
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginTop: '0.5rem' }}>
                          <span
                            style={{
                              fontSize: '0.7rem',
                              fontWeight: 600,
                              padding: '0.15rem 0.45rem',
                              borderRadius: '3px',
                              background: 'rgba(16, 185, 129, 0.2)',
                              color: 'var(--accent-success)',
                              border: '1px solid rgba(16, 185, 129, 0.35)',
                            }}
                          >
                            &check; Prerequisite Eligible
                          </span>
                          <span className="badge badge-blue">
                            {item.primary_reason_code}
                          </span>
                          <span
                            style={{
                              fontSize: '0.7rem',
                              padding: '0.15rem 0.45rem',
                              borderRadius: '3px',
                              background: 'rgba(56, 189, 248, 0.15)',
                              color: '#38bdf8',
                              border: '1px solid rgba(56, 189, 248, 0.3)',
                            }}
                          >
                            Difficulty: {diffTier} ({diffVal.toFixed(2)})
                          </span>
                        </div>
                      </div>

                      <div className="rec-score-box">
                        <div className="rec-score-value">{Number(item.score).toFixed(4)}</div>
                        <div className="rec-score-label">Rank Score</div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Selected Item Detail & Score Visualizer */}
              {selectedItem && (
                <div className="card" style={{ background: 'rgba(15, 23, 42, 0.55)', position: 'sticky', top: '80px', height: 'fit-content' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                    <div>
                      <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>Activity Scoring Analysis</h3>
                      <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        Selected: <code>{selectedItem.content_id}</code>
                      </p>
                    </div>
                    <span className="badge badge-purple">{selectedItem.primary_reason_code}</span>
                  </div>

                  <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '1rem' }}>
                    Weighted Scoring: Score = 0.40(Gap) + 0.25(Difficulty) + 0.20(Path) + 0.15(Urgency)
                  </p>

                  <div style={{ width: '100%', height: 200 }}>
                    <ResponsiveContainer>
                      <BarChart data={scoreChartData} layout="vertical" margin={{ top: 5, right: 25, left: 15, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis type="number" domain={[0, 1]} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                        <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} width={125} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1e293b', borderColor: '#475569', color: '#f8fafc', borderRadius: 6, fontSize: 12 }}
                          formatter={(val: any) => [Number(val).toFixed(4), 'Component Factor']}
                        />
                        <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                          {scoreChartData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.color} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>

                  <div style={{ marginTop: '1rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '0.75rem', fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Activity Title:</span>
                      <span style={{ fontWeight: 600 }}>{selectedItem.title}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Target Skill:</span>
                      <code>{selectedItem.target_skill_id}</code>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Prerequisite Status:</span>
                      <strong style={{ color: 'var(--accent-success)' }}>Cleared &amp; Eligible</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Explanation:</span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-main)' }}>
                        {selectedItem.reason_codes.join(', ')}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.25rem', paddingTop: '0.4rem', borderTop: '1px dashed var(--border-subtle)' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Composite Score:</span>
                      <strong style={{ color: 'var(--accent-primary)', fontFamily: 'var(--font-mono)', fontSize: '1rem' }}>
                        {Number(selectedItem.score_components.total).toFixed(6)}
                      </strong>
                    </div>
                  </div>

                  {/* Next Action Button */}
                  <div style={{ marginTop: '1rem' }}>
                    <button
                      className="btn-primary"
                      onClick={() => handleStartActivity(selectedItem)}
                      style={{ width: '100%', justifyContent: 'center' }}
                    >
                      <BookOpen size={16} /> Start Learning Activity
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
