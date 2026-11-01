import React, { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';

interface AppShellProps {
  currentTab: string;
  onTabChange: (tab: string) => void;
  children: ReactNode;
}

export const AppShell: React.FC<AppShellProps> = ({
  currentTab,
  onTabChange,
  children,
}) => {
  return (
    <div className="app-container">
      <Sidebar currentTab={currentTab} onTabChange={onTabChange} />
      <div className="main-wrapper">
        <Header />
        <main className="content-container">
          {children}
        </main>
      </div>
    </div>
  );
};
