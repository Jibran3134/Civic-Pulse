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
    getStatusTransitions: vi.fn().mockResolvedValue({
      transitions: {},
    }),
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
      category: 'sanitation' as const,
      priority: 'normal' as const,
      status: 'open' as const,
      ai_summary: 'Solid waste accumulation near school',
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

    // UNIQUE backend error string to prove verbatim surfacing (not paraphrased)
    const server409Message =
      'Invalid status transition from open to resolved -- server-uuid-7f3a9b21'
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

    // Assert: the exact server string appears verbatim in the DOM
    await waitFor(() => {
      const conflictDetail = screen.getByText(server409Message)
      expect(conflictDetail).toBeInTheDocument()
      const alertBanner = document.getElementById('server-conflict-alert')
      expect(alertBanner).toBeInTheDocument()
      expect(alertBanner).toContainElement(conflictDetail)
    })
  })
})
