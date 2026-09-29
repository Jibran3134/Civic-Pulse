import {
  Complaint,
  ComplaintCreate,
  ComplaintListResponse,
  ProviderMetaResponse,
  StatusTransitionsResponse,
  StatsResponse,
  Status,
} from '../types'

export class ApiError extends Error {
  status: number
  detail: string
  field_errors?: Record<string, string>

  constructor(status: number, detail: string, field_errors?: Record<string, string>) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.field_errors = field_errors
  }
}

const API_BASE = '/api'

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<{ data: T; headers: Headers }> {
  const url = `${API_BASE}${endpoint}`
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}: ${response.statusText}`
    let fieldErrors: Record<string, string> | undefined

    try {
      const errJson = await response.json()
      if (errJson.detail) {
        errorDetail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail)
      }
      if (errJson.field_errors) {
        fieldErrors = errJson.field_errors
      }
    } catch {
      // Body is not JSON
    }

    throw new ApiError(response.status, errorDetail, fieldErrors)
  }

  const data = (await response.json()) as T
  return { data, headers: response.headers }
}

export const api = {
  async createComplaint(payload: ComplaintCreate): Promise<Complaint> {
    const { data } = await request<Complaint>('/complaints', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    return data
  },

  async getComplaints(params?: {
    category?: string
    priority?: string
    status?: string
    page?: number
    page_size?: number
  }): Promise<ComplaintListResponse> {
    const query = new URLSearchParams()
    if (params?.category) query.set('category', params.category)
    if (params?.priority) query.set('priority', params.priority)
    if (params?.status) query.set('status', params.status)
    if (params?.page) query.set('page', params.page.toString())
    if (params?.page_size) query.set('page_size', params.page_size.toString())

    const qs = query.toString() ? `?${query.toString()}` : ''
    const { data } = await request<ComplaintListResponse>(`/complaints${qs}`)
    return data
  },

  async getComplaint(id: string): Promise<Complaint> {
    const { data } = await request<Complaint>(`/complaints/${id}`)
    return data
  },

  async updateComplaintStatus(id: string, newStatus: Status): Promise<Complaint> {
    const { data } = await request<Complaint>(`/complaints/${id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status: newStatus }),
    })
    return data
  },

  async getStats(): Promise<StatsResponse> {
    const { data, headers } = await request<StatsResponse>('/stats')
    const xCache = headers.get('X-Cache') || headers.get('x-cache')
    return {
      ...data,
      cacheHeader: xCache === 'HIT' ? 'HIT' : xCache === 'MISS' ? 'MISS' : null,
    }
  },

  async getProvidersMeta(): Promise<ProviderMetaResponse> {
    const { data } = await request<ProviderMetaResponse>('/meta/providers')
    return data
  },

  async getStatusTransitions(): Promise<StatusTransitionsResponse> {
    const { data } = await request<StatusTransitionsResponse>('/meta/status-transitions')
    return data
  },
}
