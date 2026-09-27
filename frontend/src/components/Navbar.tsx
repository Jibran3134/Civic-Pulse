import React from 'react'
import { Activity, LayoutDashboard, Send, BarChart2, Cpu } from 'lucide-react'

export type TabType = 'submit' | 'dashboard' | 'stats' | 'providers'

interface NavbarProps {
  activeTab: TabType
  onTabChange: (tab: TabType) => void
}

export const Navbar: React.FC<NavbarProps> = ({ activeTab, onTabChange }) => {
  return (
    <header className="navbar-container">
      <div className="navbar-inner">
        <div className="navbar-brand" onClick={() => onTabChange('submit')}>
          <div className="brand-icon-wrapper">
            <Activity className="brand-icon" size={24} />
          </div>
          <div>
            <h1 className="brand-title">CivicPulse</h1>
            <span className="brand-subtitle">AI-Powered Municipal Triage</span>
          </div>
        </div>

        <nav className="nav-tabs" role="tablist">
          <button
            id="tab-submit"
            role="tab"
            aria-selected={activeTab === 'submit'}
            className={`nav-btn ${activeTab === 'submit' ? 'active' : ''}`}
            onClick={() => onTabChange('submit')}
          >
            <Send size={18} />
            <span>Submit Complaint</span>
          </button>

          <button
            id="tab-dashboard"
            role="tab"
            aria-selected={activeTab === 'dashboard'}
            className={`nav-btn ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => onTabChange('dashboard')}
          >
            <LayoutDashboard size={18} />
            <span>Dashboard</span>
          </button>

          <button
            id="tab-stats"
            role="tab"
            aria-selected={activeTab === 'stats'}
            className={`nav-btn ${activeTab === 'stats' ? 'active' : ''}`}
            onClick={() => onTabChange('stats')}
          >
            <BarChart2 size={18} />
            <span>Stats & Cache</span>
          </button>

          <button
            id="tab-providers"
            role="tab"
            aria-selected={activeTab === 'providers'}
            className={`nav-btn ${activeTab === 'providers' ? 'active' : ''}`}
            onClick={() => onTabChange('providers')}
          >
            <Cpu size={18} />
            <span>Provider Health</span>
          </button>
        </nav>
      </div>
    </header>
  )
}
