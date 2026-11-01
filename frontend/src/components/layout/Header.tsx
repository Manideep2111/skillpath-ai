import React from 'react';
import { Compass } from 'lucide-react';

export const Header: React.FC = () => {
  return (
    <header className="header">
      <div className="header-title-container">
        <h1 style={{ fontSize: '1.15rem', fontWeight: 600, margin: 0 }}>
          Adaptive Learning Recommender
        </h1>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
        <Compass size={15} style={{ color: 'var(--accent-primary)' }} />
        <span style={{ fontWeight: 500 }}>SkillPath AI</span>
      </div>
    </header>
  );
};
