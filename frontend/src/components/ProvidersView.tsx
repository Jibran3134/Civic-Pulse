import React, { useState, useEffect, useCallback } from 'react'
import { api, ApiError } from '../api/client'
import { ProviderMetaResponse } from '../types'
import { Cpu, RefreshCw, Zap, Clock, ShieldCheck, Database, AlertCircle } from 'lucide-react'

export const ProvidersView: React.FC = () => {
  const [data, setData] = useState<ProviderMetaResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchProviders = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const res = await api.getProvidersMeta()
      setData(res)
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail)
      } else {
        setError((err as Error).message || 'Failed to fetch provider status')
      }
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchProviders()
  }, [fetchProviders])

  return (
    <div className="view-container">
      <div className="view-header">
        <div className="view-header-row">
          <div>
            <h2 className="view-title">Triage Provider Health & Recent Outcomes</h2>
            <p className="view-desc">
              Observability into pluggable AI engine performance, fallback executions, and 24-hour content cache.
            </p>
          </div>
          <button
            className="btn btn-secondary btn-icon"
            onClick={fetchProviders}
            disabled={isLoading}
          >
            <RefreshCw size={16} className={isLoading ? 'spinner' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="alert-banner alert-danger" role="alert">
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* Provider & Cache Status Cards */}
      <div className="stats-metric-grid">
        <div className="metric-card">
          <div className="metric-icon-bg">
            <Cpu size={24} color="#3b82f6" />
          </div>
          <div className="metric-info">
            <span className="metric-label">Active Provider</span>
            <span className="metric-value font-mono">
              {data?.active_provider || 'Loading...'}
            </span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon-bg">
            <Database size={24} color="#10b981" />
          </div>
          <div className="metric-info">
            <span className="metric-label">Content Cache Hits</span>
            <span className="metric-value">
              {data?.cache_stats?.hits ?? 0}
            </span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon-bg">
            <Zap size={24} color="#f59e0b" />
          </div>
          <div className="metric-info">
            <span className="metric-label">Cache Hit Rate</span>
            <span className="metric-value">
              {data?.cache_stats ? `${(data.cache_stats.hit_rate * 100).toFixed(1)}%` : '0.0%'}
            </span>
          </div>
        </div>
      </div>

      {/* Recent Outcomes Table */}
      <div className="breakdown-card" style={{ marginTop: '1.5rem' }}>
        <h3 className="breakdown-title">
          <Clock size={18} /> Last 20 Triage Outcomes
        </h3>

        {isLoading && !data ? (
          <div className="table-loading">
            <div className="spinner" />
            <p>Loading recent outcomes...</p>
          </div>
        ) : !data?.recent_outcomes || data.recent_outcomes.length === 0 ? (
          <div className="empty-state">
            <ShieldCheck size={40} color="#64748b" />
            <p>No recent triage outcomes recorded yet. Submit a grievance to generate telemetry.</p>
          </div>
        ) : (
          <div className="table-container">
            <table className="complaints-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Provider</th>
                  <th>Category</th>
                  <th>Priority</th>
                  <th>Latency</th>
                  <th>Cache Status</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_outcomes.map((outcome, idx) => (
                  <tr key={idx}>
                    <td className="font-mono text-sm">
                      {new Date(outcome.timestamp).toLocaleTimeString()}
                    </td>
                    <td>
                      <span className="badge badge-provider">{outcome.provider}</span>
                    </td>
                    <td>
                      <span className={`badge badge-category badge-${outcome.category}`}>
                        {outcome.category}
                      </span>
                    </td>
                    <td>
                      <span className={`badge badge-priority badge-${outcome.priority}`}>
                        {outcome.priority}
                      </span>
                    </td>
                    <td>
                      <strong>{outcome.latency_ms} ms</strong>
                    </td>
                    <td>
                      {outcome.cached ? (
                        <span className="badge-cache-hit">HIT (24h)</span>
                      ) : (
                        <span className="badge-cache-miss">COMPUTED</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
