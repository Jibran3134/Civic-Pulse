import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { DashboardView } from '../components/DashboardView'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    getComplaints: vi.fn(),
    updateComplaintStatus: vi.fn(),
    getStatusTransitions: vi.fn().mockResolvedValue({
      transitions: {},
    }),
  },
  ApiError: class extends Error {
    status: number
    detail: string
    constructor(status: number, detail: string) {
      super(detail)
      this.status = status
      this.detail = detail
    }
  },
}))

describe('DashboardView Pagination', () => {
  it('advances page and queries API with updated page parameter and page_size <= 100', async () => {
    vi.mocked(api.getComplaints).mockResolvedValue({
      items: [
        {
          id: '1',
          text: 'Power outage on street 1',
          location: 'Sector F-6',
          reporter_contact: null,
          category: 'electricity',
          priority: 'high',
          status: 'open',    // correct backend enum: open (not 'new')
          ai_summary: 'Power failure',
          triaged_by: 'simulated',
          triage_latency_ms: 100,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      total: 25,
      page: 1,
      page_size: 10,
    })

    render(<DashboardView />)

    await waitFor(() => {
      expect(screen.getByText(/Power outage on street 1/i)).toBeInTheDocument()
      expect(
        screen.getByText(
          (_, element) =>
            element?.className === 'pagination-info' &&
            Boolean(element?.textContent?.includes('Page 1 of 3'))
        )
      ).toBeInTheDocument()
    })

    const nextBtn = screen.getByRole('button', { name: /Next/i })
    expect(nextBtn).toBeEnabled()

    fireEvent.click(nextBtn)

    await waitFor(() => {
      // Assert page increments AND page_size is <= 100 (API contract enforcement)
      expect(api.getComplaints).toHaveBeenCalledWith(
        expect.objectContaining({
          page: 2,
          page_size: expect.any(Number),
        })
      )
      // Verify page_size constraint is respected
      const lastCall = vi.mocked(api.getComplaints).mock.calls.at(-1)?.[0]
      expect(lastCall?.page_size).toBeLessThanOrEqual(100)
    })
  })
})
