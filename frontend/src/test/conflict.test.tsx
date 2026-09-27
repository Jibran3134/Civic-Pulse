import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { DashboardView } from '../components/DashboardView'
import { api, ApiError } from '../api/client'

vi.mock('../api/client', () => {
  class MockApiError extends Error {
    status: number
    detail: string
    constructor(status: number, detail: string) {
      super(detail)
      this.status = status
      this.detail = detail
    }
  }

  return {
    api: {
      getComplaints: vi.fn(),
      updateComplaintStatus: vi.fn(),
    },
    ApiError: MockApiError,
  }
})

describe('DashboardView 409 Conflict Error Surfacing', () => {
  it('surfaces server 409 detail message verbatim when invalid status transition is rejected', async () => {
    const mockComplaint = {
      id: 'd9b1a036-7c98-4c12-92ec-99b35b6a71cb',
      text: 'Garbage dump near primary school unattended for 2 weeks',
      location: 'Rawalpindi Satellite Town',
      reporter_contact: null,
      category: 'waste' as const,
      priority: 'medium' as const,
      status: 'new' as const,
      ai_summary: 'Solid waste accumulation',
      triaged_by: 'simulated',
      triage_latency_ms: 150,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }

    vi.mocked(api.getComplaints).mockResolvedValue({
      items: [mockComplaint],
      total: 1,
      page: 1,
      page_size: 10,
    })

    const server409Message = 'Invalid status transition from new to resolved'
    vi.mocked(api.updateComplaintStatus).mockRejectedValue(
      new ApiError(409, server409Message)
    )

    render(<DashboardView />)

    await waitFor(() => {
      expect(screen.getByText(/Garbage dump near primary school/i)).toBeInTheDocument()
    })

    const transitionSelect = screen.getByLabelText(
      `Change status for complaint ${mockComplaint.id}`
    )
    fireEvent.change(transitionSelect, { target: { value: 'resolved' } })

    // Must surface the server's exact message verbatim
    await waitFor(() => {
      const alertContainer = screen.getByRole('alert')
      expect(alertContainer).toBeInTheDocument()
      expect(screen.getByText(server409Message)).toBeInTheDocument()
    })
  })
})
