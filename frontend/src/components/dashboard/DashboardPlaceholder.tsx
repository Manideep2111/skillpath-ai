import React, { useState } from 'react';
import {
  Users,
  BookOpen,
  Award,
  Layers,
  Sparkles,
  AlertCircle,
  Clock,
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

export const DashboardPlaceholder: React.FC = () => {
  const [selectedLearner, setSelectedLearner] = useState<string>('LRN-000001');
  const [topK, setTopK] = useState<number>(5);
  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedItem, setSelectedItem] = useState<RecommendedItem | null>(null);

  const fetchRecommendations = async () => {
    setLoading(true);
    setError(null);
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

  return (
    <div>
      {/* Overview Metric Cards */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' }}>
            <Users size={22} />
          </div>
          <div>
            <div className="stat-value">100</div>
            <div className="stat-label">Active Learners (10 Cold Start)</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981' }}>
            <BookOpen size={22} />
          </div>
          <div>
            <div className="stat-value">100</div>
            <div className="stat-label">Curriculum Content Items</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(139, 92, 246, 0.15)', color: '#8b5cf6' }}>
            <Award size={22} />
          </div>
          <div>
            <div className="stat-value">50</div>
            <div className="stat-label">Mapped Knowledge Skills</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b' }}>
            <Layers size={22} />
          </div>
          <div>
            <div className="stat-value">15 / 15</div>
            <div className="stat-label">Data Invariants Passed</div>
          </div>
        </div>
      </div>

      {/* Main Interactive Recommendation Probe */}
      <div className="card" style={{ marginBottom: '2rem' }}>
        <h2 className="card-title">Recommendation Engine Explorer</h2>
        <p className="card-subtitle">
          Query real-time personalized recommendations directly from the FastAPI backend (Stage 1–8 integration).
        </p>

        <div className="control-row">
          <div className="input-group">
            <label className="input-label">Select Learner ID</label>
            <select
              className="form-select"
              value={selectedLearner}
              onChange={(e) => setSelectedLearner(e.target.value)}
            >
              <optgroup label="Standard Learners">
                <option value="LRN-000001">LRN-000001 (Beginner)</option>
                <option value="LRN-000002">LRN-000002 (Intermediate)</option>
                <option value="LRN-000003">LRN-000003 (Advanced)</option>
                <option value="LRN-000010">LRN-000010</option>
              </optgroup>
              <optgroup label="Cold-Start Cohort (0 attempts)">
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
            <Sparkles size={16} />
            {loading ? 'Evaluating...' : 'Generate Recommendations'}
          </button>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <AlertCircle size={20} />
            <div>
              <strong>API Error:</strong> {error}
            </div>
          </div>
        )}

        {data && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                Decision Cutoff: <code>{data.cutoff_timestamp}</code> | Prerequisite Blocked: {data.rejection_summary.prerequisite_blocked} | Recent Completed: {data.rejection_summary.recent_completions}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(350px, 1.2fr) minmax(300px, 1fr)', gap: '1.5rem' }}>
              {/* Recommendations List */}
              <div className="rec-list">
                {data.items.length === 0 ? (
                  <div className="alert alert-info">
                    No recommendations eligible for this learner at the specified cutoff.
                  </div>
                ) : (
                  data.items.map((item, idx) => {
                    const isSelected = selectedItem?.content_id === item.content_id;
                    return (
                      <div
                        key={item.content_id}
                        className="rec-item"
                        style={{
                          cursor: 'pointer',
                          borderColor: isSelected ? 'var(--accent-primary)' : 'var(--border-subtle)',
                          background: isSelected ? 'rgba(59, 130, 246, 0.08)' : 'rgba(15, 23, 42, 0.6)',
                        }}
                        onClick={() => setSelectedItem(item)}
                      >
                        <div className="rec-rank">#{idx + 1}</div>
                        <div className="rec-details">
                          <div className="rec-title">{item.title}</div>
                          <div className="rec-meta">
                            <span>ID: <code>{item.content_id}</code></span>
                            <span>Target: <code>{item.target_skill_id}</code></span>
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', marginTop: '0.5rem' }}>
                            <span className="badge badge-blue">{item.primary_reason_code}</span>
                            {item.reason_codes.slice(1, 3).map((rc) => (
                              <span key={rc} className="badge badge-purple">{rc}</span>
                            ))}
                          </div>
                        </div>
                        <div className="rec-score-box">
                          <div className="rec-score-value">{Number(item.score).toFixed(4)}</div>
                          <div className="rec-score-label">Ranking Score</div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

              {/* Selected Item Score Components (Recharts Data Visualization) */}
              {selectedItem && (
                <div className="card" style={{ background: 'rgba(15, 23, 42, 0.5)' }}>
                  <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.25rem' }}>
                    Score Components Breakdown
                  </h3>
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
                    Formula: Total = 0.40(Gap) + 0.25(Diff) + 0.20(Path) + 0.15(Urgency)
                  </p>

                  <div style={{ width: '100%', height: 220 }}>
                    <ResponsiveContainer>
                      <BarChart data={scoreChartData} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis type="number" domain={[0, 1]} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                        <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} width={120} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1e293b', borderColor: '#475569', color: '#f8fafc', borderRadius: 6, fontSize: 12 }}
                          formatter={(val: any) => [Number(val).toFixed(4), 'Factor Value']}
                        />
                        <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                          {scoreChartData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.color} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>

                  <div style={{ marginTop: '1rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '0.75rem', fontSize: '0.85rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Primary Reason:</span>
                      <span className="badge badge-blue">{selectedItem.primary_reason_code}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Target Skill:</span>
                      <code>{selectedItem.target_skill_id}</code>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Computed Total:</span>
                      <strong style={{ color: 'var(--accent-primary)', fontFamily: 'var(--font-mono)' }}>
                        {Number(selectedItem.score_components.total).toFixed(6)}
                      </strong>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Architecture & Milestone Status Banner */}
      <div className="card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(30, 41, 59, 0.4)' }}>
        <div>
          <h3 style={{ fontSize: '0.95rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <CheckCircle size={16} color="#10b981" />
            Stage 9A: Frontend Foundation Established
          </h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
            React 18 + Vite + TypeScript + Recharts. Cleanly communicates with FastAPI backend via typed apiClient.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-dim)', fontSize: '0.8rem' }}>
          <Clock size={14} />
          <span>Milestone: Stage 9A Complete</span>
        </div>
      </div>
    </div>
  );
};
