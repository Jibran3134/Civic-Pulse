import React, { useState, useEffect, useCallback } from 'react'
import { api, ApiError } from '../api/client'
import { Complaint, Status } from '../types'
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Filter,
  RefreshCw,
  Clock,
  MapPin,
  ArrowRight,
  XCircle,
} from 'lucide-react'
import { CategoryBadge } from './CategoryBadge'
import { PriorityBadge } from './PriorityBadge'
import { StatusBadge } from './StatusBadge'

/**
 * Presentation only. Maps a status to the button text, and deliberately holds
 * no transition information -- which statuses are reachable is fetched from the
 * backend.
 */
const STATUS_ACTION_LABELS: Record<Status, string> = {
  in_progress: 'In Progress',
  resolved: 'Resolve',
  rejected: 'Reject',
  open: 'Reopen',
}

export const DashboardView: React.FC = () => {
  const [complaints, setComplaints] = useState<Complaint[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const pageSize = 10

  const [categoryFilter, setCategoryFilter] = useState<string>('')
  const [priorityFilter, setPriorityFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  const [isLoading, setIsLoading] = useState(false)
  const [generalError, setGeneralError] = useState<string | null>(null)
  const [conflictError, setConflictError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [updatingId, setUpdatingId] = useState<string | null>(null)
  // Fetched from GET /api/meta/status-transitions. Empty until it arrives, so
  // the first paint shows no action buttons rather than guessing at them.
  const [transitions, setTransitions] = useState<Record<Status, Status[]>>(
    {} as Record<Status, Status[]>
  )

  const fetchComplaints = useCallback(async () => {
    setIsLoading(true)
    setGeneralError(null)

    try {
      const data = await api.getComplaints({
        category: categoryFilter || undefined,
        priority: priorityFilter || undefined,
        status: statusFilter || undefined,
        page,
        page_size: pageSize,
      })
      setComplaints(data.items)
      setTotal(data.total)
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setGeneralError(err.detail)
      } else {
        setGeneralError((err as Error).message || 'Failed to fetch complaints')
      }
    } finally {
      setIsLoading(false)
    }
  }, [categoryFilter, priorityFilter, statusFilter, page])

  useEffect(() => {
    fetchComplaints()
  }, [fetchComplaints])

  // Load the workflow table once per mount. A failure here must not blank the
  // dashboard: the list still renders, only the action buttons are missing,
  // and the status select is still there as a fallback.
  useEffect(() => {
    let cancelled = false
    // Wrapped in an async IIFE so a synchronous throw from the client is
    // caught too. Chaining .catch() directly would not help: if the method is
    // missing the TypeError happens before any promise exists, and it would
    // escape into render as an unhandled rejection. The dashboard must survive
    // a backend that predates this endpoint.
    void (async () => {
      try {
        const data = await api.getStatusTransitions()
        if (!cancelled) setTransitions(data.transitions)
      } catch {
        if (!cancelled) setTransitions({} as Record<Status, Status[]>)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const handleStatusChange = async (id: string, newStatus: Status) => {
    setConflictError(null)
    setSuccessMessage(null)
    setUpdatingId(id)

    try {
      const updated = await api.updateComplaintStatus(id, newStatus)
      setSuccessMessage(`Complaint status updated to ${updated.status}`)
      setComplaints((prev) => prev.map((c) => (c.id === id ? updated : c)))
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          // CRITICAL REQUIREMENT: Surface server's 409 message verbatim
          setConflictError(err.detail)
        } else {
          setGeneralError(err.detail)
        }
      } else {
        setGeneralError((err as Error).message || 'Status update failed')
      }
    } finally {
      setUpdatingId(null)
    }
  }

  const totalPages = Math.ceil(total / pageSize) || 1

  // Status values MUST match backend status_machine.py exactly
  const allStatuses: Status[] = ['open', 'in_progress', 'resolved', 'rejected']

  return (
    <div className="view-container">
      <div className="view-header">
        <div className="view-header-row">
          <div>
            <h2 className="view-title">Municipal Operator Dashboard</h2>
            <p className="view-desc">
              Monitor, filter, and transition municipal complaints through their lifecycle state machine.
            </p>
          </div>
          <button
            className="btn btn-secondary btn-icon"
            onClick={fetchComplaints}
            disabled={isLoading}
            title="Refresh Complaints"
          >
            <RefreshCw size={16} className={isLoading ? 'spinner' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {conflictError && (
        <div className="alert-banner alert-conflict" role="alert" id="server-conflict-alert">
          <div className="conflict-header">
            <XCircle size={20} color="#ef4444" />
            <strong>HTTP 409 Conflict (Server State Machine Rejection)</strong>
          </div>
          <div className="conflict-message" id="conflict-detail-text">
            {conflictError}
          </div>
        </div>
      )}

      {successMessage && (
        <div className="alert-banner alert-success" role="alert">
          <CheckCircle2 size={18} />
          <span>{successMessage}</span>
        </div>
      )}

      {generalError && (
        <div className="alert-banner alert-danger" role="alert">
          <AlertCircle size={18} />
          <span>{generalError}</span>
        </div>
      )}

      {/* Filter Bar */}
      <div className="filters-card">
        <div className="filter-title">
          <Filter size={16} /> Filter Grievances:
        </div>

        <div className="filters-group">
          <select
            id="filter-category"
            aria-label="Filter by category"
            value={categoryFilter}
            onChange={(e) => {
              setCategoryFilter(e.target.value)
              setPage(1)
            }}
          >
            {/* Category values match backend DB enum exactly */}
            <option value="">All Categories</option>
            <option value="water">Water</option>
            <option value="electricity">Electricity</option>
            <option value="sanitation">Sanitation</option>
            <option value="roads">Roads</option>
            <option value="streetlights">Streetlights</option>
            <option value="other">Other</option>
          </select>

          <select
            id="filter-priority"
            aria-label="Filter by priority"
            value={priorityFilter}
            onChange={(e) => {
              setPriorityFilter(e.target.value)
              setPage(1)
            }}
          >
            {/* Priority values match backend DB enum exactly: high | normal | low */}
            <option value="">All Priorities</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
            <option value="low">Low</option>
          </select>

          <select
            id="filter-status"
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value)
              setPage(1)
            }}
          >
            {/* Status values match backend status_machine.py: open→in_progress→resolved|rejected */}
            <option value="">All Statuses</option>
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="resolved">Resolved</option>
            <option value="rejected">Rejected</option>
          </select>

          {(categoryFilter || priorityFilter || statusFilter) && (
            <button
              className="btn btn-outline btn-sm"
              onClick={() => {
                setCategoryFilter('')
                setPriorityFilter('')
                setStatusFilter('')
                setPage(1)
              }}
            >
              Reset Filters
            </button>
          )}
        </div>

        <div className="results-count">
          Showing <strong>{complaints.length}</strong> of <strong>{total}</strong> complaints
        </div>
      </div>

      {/* Complaints List / Table */}
      {isLoading ? (
        <div className="table-loading" role="status">
          <div className="spinner large" />
          <p>Loading complaints from database...</p>
        </div>
      ) : complaints.length === 0 ? (
        <div className="empty-state">
          <Clock size={48} color="#64748b" />
          <h3>No complaints found</h3>
          <p>Try clearing filters or submit a new grievance to see it here.</p>
        </div>
      ) : (
        <div className="table-container">
          <table className="complaints-table">
            <thead>
              <tr>
                <th>Complaint Details</th>
                <th>Category</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Triaged By</th>
                <th>State Actions</th>
              </tr>
            </thead>
            <tbody>
              {complaints.map((c) => (
                <tr key={c.id} className={`row-status-${c.status}`}>
                  <td className="col-details">
                    <div className="complaint-text">{c.text}</div>
                    <div className="complaint-submeta">
                      <span className="location-tag">
                        <MapPin size={12} /> {c.location}
                      </span>
                      <span className="id-tag">ID: {c.id.substring(0, 8)}...</span>
                      {c.ai_summary && (
                        <span className="ai-summary-tag" title={c.ai_summary}>
                          AI: {c.ai_summary.substring(0, 60)}...
                        </span>
                      )}
                    </div>
                  </td>

                  <td>
                    <CategoryBadge category={c.category} />
                  </td>

                  <td>
                    <PriorityBadge priority={c.priority} />
                  </td>

                  <td>
                    <StatusBadge status={c.status} />
                  </td>

                  <td>
                    <span className="badge badge-provider" title={`Latency: ${c.triage_latency_ms}ms`}>
                      {c.triaged_by}
                    </span>
                  </td>

                  <td className="col-actions">
                    <div className="action-buttons">
                      <select
                        className="transition-select"
                        aria-label={`Change status for complaint ${c.id}`}
                        value={c.status}
                        disabled={updatingId === c.id}
                        onChange={(e) => handleStatusChange(c.id, e.target.value as Status)}
                      >
                        {allStatuses.map((st) => (
                          <option key={st} value={st}>
                            {st === c.status ? `Current: ${st}` : `→ ${st}`}
                          </option>
                        ))}
                      </select>

                      {/* Actions are rendered from the server's transition
                          table rather than from a hard-coded rule. Nothing in
                          this component decides which status may follow which;
                          it asks the backend and draws what comes back. If the
                          server adds an edge, the button appears here with no
                          frontend change. */}
                      {(transitions[c.status] ?? []).map((next) => (
                        <button
                          key={next}
                          className={
                            next === 'resolved'
                              ? 'btn-action-pill btn-action-success'
                              : 'btn-action-pill'
                          }
                          title={`Move to ${next.replace('_', ' ')}`}
                          disabled={updatingId === c.id}
                          onClick={() => handleStatusChange(c.id, next)}
                        >
                          {STATUS_ACTION_LABELS[next] ?? next}
                          <ArrowRight size={12} />
                        </button>
                      ))}
                      {(transitions[c.status] ?? []).length === 0 && (
                        <span className="text-muted">Terminal state</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination Bar */}
      <div className="pagination-bar">
        <div className="pagination-info">
          Page <strong>{page}</strong> of <strong>{totalPages}</strong> ({total} items total)
        </div>
        <div className="pagination-controls">
          <button
            id="prev-page-btn"
            className="btn btn-secondary btn-sm"
            disabled={page <= 1 || isLoading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            <ChevronLeft size={16} /> Previous
          </button>
          <span className="current-page-badge">{page}</span>
          <button
            id="next-page-btn"
            className="btn btn-secondary btn-sm"
            disabled={page >= totalPages || isLoading}
            onClick={() => setPage((p) => p + 1)}
          >
            Next <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}
