import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { AppShell } from './components/layout/AppShell';
import { OverviewDashboard } from './components/overview/OverviewDashboard';
import { RecommendationsView } from './components/recommendations/RecommendationsView';
import { EvaluationDashboard } from './components/evaluation/EvaluationDashboard';
import { AnomaliesDashboard } from './components/anomalies/AnomaliesDashboard';

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<string>('dashboard');

  return (
    <AppShell currentTab={currentTab} onTabChange={setCurrentTab}>
      {currentTab === 'dashboard' && <OverviewDashboard onNavigateTab={setCurrentTab} />}

      {currentTab === 'recommendations' && <RecommendationsView />}

      {currentTab === 'evaluation' && <EvaluationDashboard onNavigateTab={setCurrentTab} />}

      {currentTab === 'anomalies' && <AnomaliesDashboard />}

      {currentTab === 'about' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div className="card">
            <h2 className="card-title" style={{ marginBottom: '0.25rem' }}>About SkillPath AI</h2>
            <p className="card-subtitle" style={{ marginBottom: '1.25rem' }}>
              An adaptive, personalized learning recommendation and point-in-time evaluation platform.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div>
                <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.35rem', color: 'var(--text-main)' }}>
                  Purpose
                </h3>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: 1.6, margin: 0 }}>
                  SkillPath AI guides learners through structured curricula by identifying knowledge gaps, recommending suitable learning activities, and enforcing strict prerequisite dependencies. It provides point-in-time evaluation methodology to objectively assess recommendation accuracy, observational learning gain, and fairness across diverse activity cohorts.
                </p>
              </div>

              <div>
                <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.35rem', color: 'var(--text-main)' }}>
                  How Recommendations Work
                </h3>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: 1.6, margin: 0 }}>
                  The engine combines two-stage filtering and ranking:
                </p>
                <ul style={{ paddingLeft: '1.25rem', marginTop: '0.35rem', fontSize: '0.85rem', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                  <li><strong>Prerequisite Gating:</strong> Eliminates candidate content where prerequisite competency requirements have not yet been demonstrated.</li>
                  <li><strong>Multi-Factor Scoring:</strong> Ranks eligible activities via weighted factors: Skill Gap (40%), Difficulty Suitability (25%), Learning Path Alignment (20%), and Spaced Practice Urgency (15%).</li>
                  <li><strong>Explainable Reasons:</strong> Attaches transparent reason codes to every recommended item.</li>
                </ul>
              </div>

              <div>
                <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.35rem', color: 'var(--text-main)' }}>
                  Evaluation &amp; Anomaly Detection
                </h3>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: 1.6, margin: 0 }}>
                  Recommendation quality is audited across chronological temporal windows without future data leakage. Five canonical data-quality detectors ensure prerequisite compliance, timestamp consistency, orphaned entity prevention, future attempt containment, and loop-free learning paths.
                </p>
              </div>

              <div>
                <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.35rem', color: 'var(--text-main)' }}>
                  Technology Stack
                </h3>
                <ul style={{ paddingLeft: '1.25rem', marginTop: '0.35rem', fontSize: '0.85rem', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                  <li><strong>Backend:</strong> Python 3.11+, FastAPI, Pydantic v2</li>
                  <li><strong>Database &amp; ORM:</strong> SQLite 3, SQLAlchemy 2.0 (read-only PRAGMA query_only for audits)</li>
                  <li><strong>Frontend:</strong> React 18, TypeScript, Vite, Lucide Icons</li>
                  <li><strong>Visualizations:</strong> Recharts responsive charts</li>
                </ul>
              </div>
            </div>
          </div>

          {/* Collapsible Architecture & Technical Details */}
          <details className="card" style={{ padding: '0.85rem 1.25rem' }}>
            <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.5rem', outline: 'none', color: 'var(--text-muted)' }}>
              <ChevronDown size={15} />
              <span>Technical Design &amp; Architecture Notes (Click to Expand)</span>
            </summary>
            <div style={{ marginTop: '0.75rem', fontSize: '0.8rem', color: 'var(--text-dim)', lineHeight: 1.6 }}>
              <p style={{ margin: 0, marginBottom: '0.5rem' }}>
                SkillPath AI strictly isolates production data from evaluation and anomaly detection testbeds:
              </p>
              <ul style={{ paddingLeft: '1.25rem', margin: 0, display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                <li>Baseline Database: <code>skillpath.db</code> protected by SHA-256 fingerprint verification and <code>PRAGMA query_only = ON</code>.</li>
                <li>Anomaly Sandbox: <code>data/anomalies/skillpath_anomaly_sandbox.db</code> cloned via SQLite Online Backup API.</li>
                <li>Evaluation Engine: Methodology Version 2.3 evaluating multi-window temporal slices with right-censored observation limits.</li>
                <li>Reproducibility: Deterministic synthetic generator with random seed <code>20261022</code>.</li>
              </ul>
            </div>
          </details>
        </div>
      )}
    </AppShell>
  );
};

export default App;
