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

describe('DashboardView Filtering', () => {
  it('triggers API call with category filter and resets page to 1', async () => {
    vi.mocked(api.getComplaints).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    })

    render(<DashboardView />)

    await waitFor(() => {
      expect(api.getComplaints).toHaveBeenCalledTimes(1)
    })

    const catSelect = screen.getByLabelText(/Filter by category/i)
    fireEvent.change(catSelect, { target: { value: 'water' } })

    await waitFor(() => {
      expect(api.getComplaints).toHaveBeenCalledWith(
        expect.objectContaining({
          category: 'water',
          page: 1,
        })
      )
    })
  })
})
