import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { DashboardView } from '../components/DashboardView'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    getComplaints: vi.fn(),
    updateComplaintStatus: vi.fn(),
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
  it('advances page and queries API with updated page parameter', async () => {
    vi.mocked(api.getComplaints).mockResolvedValue({
      items: [
        {
          id: '1',
          text: 'Power outage on street 1',
          location: 'Sector F-6',
          reporter_contact: null,
          category: 'electricity',
          priority: 'high',
          status: 'new',
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
      expect(api.getComplaints).toHaveBeenCalledWith(
        expect.objectContaining({
          page: 2,
        })
      )
    })
  })
})
