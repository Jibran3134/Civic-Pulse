import React, { useState } from 'react'
import { Navbar, TabType } from './components/Navbar'
import { SubmitView } from './components/SubmitView'
import { DashboardView } from './components/DashboardView'
import { StatsView } from './components/StatsView'
import { ProvidersView } from './components/ProvidersView'
import { ErrorBoundary } from './components/ErrorBoundary'

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('submit')

  return (
    <ErrorBoundary>
      <div className="app-layout">
        <Navbar activeTab={activeTab} onTabChange={setActiveTab} />
        <main className="main-content">
          {activeTab === 'submit' && <SubmitView />}
          {activeTab === 'dashboard' && <DashboardView />}
          {activeTab === 'stats' && <StatsView />}
          {activeTab === 'providers' && <ProvidersView />}
        </main>
      </div>
    </ErrorBoundary>
  )
}

export default App
