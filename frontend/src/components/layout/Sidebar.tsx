import React from 'react';
import {
  LayoutDashboard,
  Sparkles,
  BarChart3,
  ShieldCheck,
  GraduationCap,
  Info,
} from 'lucide-react';

interface SidebarProps {
  currentTab: string;
  onTabChange: (tab: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentTab, onTabChange }) => {
  const navItems = [
    { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
    { id: 'recommendations', label: 'Recommendations', icon: Sparkles },
    { id: 'evaluation', label: 'Evaluation', icon: BarChart3 },
    { id: 'anomalies', label: 'Data Quality', icon: ShieldCheck },
    { id: 'about', label: 'About', icon: Info },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <GraduationCap size={24} color="#3b82f6" />
          <span>SkillPath <span>AI</span></span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              className={`nav-item ${isActive ? 'active' : ''}`}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
};
