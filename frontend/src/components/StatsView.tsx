import React, { useState, useEffect, useCallback } from 'react'
import { api, ApiError } from '../api/client'
import { StatsResponse } from '../types'
import {
  BarChart2,
  RefreshCw,
  Zap,
  Database,
  Layers,
  Flame,
  AlertTriangle,
  Info,
} from 'lucide-react'

export const StatsView: React.FC = () => {
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastFetched, setLastFetched] = useState<string | null>(null)

  const fetchStats = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const data = await api.getStats()
      setStats(data)
      setLastFetched(new Date().toLocaleTimeString())
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail)
      } else {
        setError((err as Error).message || 'Failed to fetch statistics')
      }
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  const totalComplaints = stats
    ? Object.values(stats.by_category).reduce((acc, curr) => acc + curr, 0)
    : 0

  return (
    <div className="view-container">
      <div className="view-header">
        <div className="view-header-row">
          <div>
            <h2 className="view-title">Civic Analytics & Caching Observability</h2>
            <p className="view-desc">
              Real-time aggregation across municipal categories and urgency priorities with live Redis cache telemetry.
            </p>
          </div>
          <button
            id="refresh-stats-btn"
            className="btn btn-secondary btn-icon"
            onClick={fetchStats}
            disabled={isLoading}
          >
            <RefreshCw size={16} className={isLoading ? 'spinner' : ''} />
            <span>Refresh Stats</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="alert-banner alert-danger" role="alert">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* X-Cache Header Telemetry Card */}
      <div className="cache-telemetry-card" role="region" aria-label="Cache Status">
        <div className="cache-card-inner">
          <div className="cache-status-indicator">
            {stats?.cacheHeader === 'HIT' ? (
              <div className="cache-badge hit" id="cache-status-badge">
                <Zap size={20} />
                <span>X-Cache: HIT</span>
              </div>
            ) : (
              <div className="cache-badge miss" id="cache-status-badge">
                <Database size={20} />
                <span>X-Cache: MISS</span>
              </div>
            )}
            <span className="cache-timestamp">
              Last query: <strong>{lastFetched || '—'}</strong>
            </span>
          </div>

          <div className="cache-explanation">
            <Info size={16} color="#38bdf8" />
            <span>
              {stats?.cacheHeader === 'HIT'
                ? 'Response served in sub-millisecond time from Redis cache (30-second TTL).'
                : 'Cache was cold or expired; aggregation computed live from PostgreSQL and stored in Redis.'}
            </span>
          </div>
        </div>
      </div>

      {isLoading && !stats ? (
        <div className="table-loading" role="status">
          <div className="spinner large" />
          <p>Computing aggregate statistics...</p>
        </div>
      ) : (
        <>
          {/* Top Metric Cards */}
          <div className="stats-metric-grid">
            <div className="metric-card">
              <div className="metric-icon-bg">
                <Layers size={24} color="#3b82f6" />
              </div>
              <div className="metric-info">
                <span className="metric-label">Total Grievances</span>
                <span className="metric-value">{totalComplaints}</span>
              </div>
            </div>

            <div className="metric-card">
              <div className="metric-icon-bg">
                <Flame size={24} color="#ef4444" />
              </div>
              <div className="metric-info">
                <span className="metric-label">High Priority</span>
                <span className="metric-value">{stats?.by_priority['high'] || 0}</span>
              </div>
            </div>

            <div className="metric-card">
              <div className="metric-icon-bg">
                <BarChart2 size={24} color="#10b981" />
              </div>
              <div className="metric-info">
                <span className="metric-label">Active Categories</span>
                <span className="metric-value">
                  {stats ? Object.keys(stats.by_category).length : 0}
                </span>
              </div>
            </div>
          </div>

          {/* Breakdown Sections */}
          <div className="breakdown-grid">
            {/* By Category */}
            <div className="breakdown-card">
              <h3 className="breakdown-title">
                <Layers size={18} /> Grievances by Category
              </h3>
              <div className="breakdown-list">
                {stats &&
                  Object.entries(stats.by_category).map(([category, count]) => {
                    const percentage = totalComplaints > 0 ? (count / totalComplaints) * 100 : 0
                    return (
                      <div key={category} className="breakdown-row">
                        <div className="breakdown-row-header">
                          <span className={`badge badge-category badge-${category}`}>
                            {category.toUpperCase()}
                          </span>
                          <span className="breakdown-count">
                            {count} ({percentage.toFixed(0)}%)
                          </span>
                        </div>
                        <div className="progress-track">
                          <div
                            className={`progress-fill cat-fill-${category}`}
                            style={{ width: `${percentage}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
              </div>
            </div>

            {/* By Priority */}
            <div className="breakdown-card">
              <h3 className="breakdown-title">
                <Flame size={18} /> Grievances by Priority
              </h3>
              <div className="breakdown-list">
                {stats &&
                  (['high', 'normal', 'low'] as const).map((priority) => {
                    const count = stats.by_priority[priority] || 0
                    const percentage = totalComplaints > 0 ? (count / totalComplaints) * 100 : 0
                    return (
                      <div key={priority} className="breakdown-row">
                        <div className="breakdown-row-header">
                          <span className={`badge badge-priority badge-${priority}`}>
                            {priority.toUpperCase()}
                          </span>
                          <span className="breakdown-count">
                            {count} ({percentage.toFixed(0)}%)
                          </span>
                        </div>
                        <div className="progress-track">
                          <div
                            className={`progress-fill pri-fill-${priority}`}
                            style={{ width: `${percentage}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
