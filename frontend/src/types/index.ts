// These enums MUST match the backend database schema exactly (status_machine.py + DB column enums)
export type Category = 'water' | 'electricity' | 'sanitation' | 'roads' | 'streetlights' | 'other'

export type Priority = 'high' | 'normal' | 'low'

export type Status = 'open' | 'in_progress' | 'resolved' | 'rejected'

export interface ComplaintCreate {
  text: string
  location: string
  reporter_contact?: string | null
}

export interface Complaint {
  id: string
  text: string
  location: string
  reporter_contact: string | null
  category: Category
  priority: Priority
  status: Status
  ai_summary: string | null
  triaged_by: string
  triage_latency_ms: number
  created_at: string
  updated_at: string
}

export interface ComplaintListResponse {
  items: Complaint[]
  total: number
  page: number
  page_size: number
}

export interface StatusUpdate {
  status: Status
}

export interface StatsResponse {
  by_category: Record<string, number>
  by_priority: Record<string, number>
  cacheHeader?: 'HIT' | 'MISS' | null
}

export interface ProviderOutcome {
  timestamp: string
  provider: string
  category: string
  priority: string
  latency_ms: number
  cached?: boolean
}

export interface ProviderMetaResponse {
  active_provider: string
  recent_outcomes: ProviderOutcome[]
  cache_stats: {
    hits: number
    misses: number
    hit_rate: number
    total_requests: number
  }
}

/**
 * The workflow state machine, served by the backend.
 *
 * The dashboard renders operator actions from this instead of hard-coding
 * which button appears for which status. The assignment is explicit that valid
 * transitions are decided by the backend and rendered by the frontend,
 * "never duplicated in it" -- branching on the current status in JSX creates a
 * second source of truth that silently rots when an edge is added server-side.
 */
export interface StatusTransitionsResponse {
  transitions: Record<Status, Status[]>
}

export interface ApiError {  detail: string
  field_errors?: Record<string, string>
  status?: number
}
