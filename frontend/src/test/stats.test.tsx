import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { StatsView } from '../components/StatsView'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    getStats: vi.fn(),
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

describe('StatsView Aggregates & X-Cache Header', () => {
  it('renders category and priority counts and displays X-Cache: HIT header badge', async () => {
    vi.mocked(api.getStats).mockResolvedValue({
      by_category: {
        water: 12,
        electricity: 8,
        sanitation: 5,
        roads: 4,
        streetlights: 3,
        other: 1,
      },
      by_priority: {
        high: 10,
        normal: 18,
        low: 5,
      },
      cacheHeader: 'HIT',
    })

    render(<StatsView />)

    // Verify loading message
    expect(screen.getByText(/Computing aggregate statistics/i)).toBeInTheDocument()

    // Wait for aggregate data to render
    await waitFor(() => {
      expect(screen.getByText('High Priority')).toBeInTheDocument()
      expect(screen.getByText('Active Categories')).toBeInTheDocument()
      expect(screen.getByText('Total Grievances')).toBeInTheDocument()
    })

    // Verify X-Cache: HIT badge is rendered
    expect(screen.getByText(/X-Cache: HIT/i)).toBeInTheDocument()
  })

  it('renders X-Cache: MISS badge when response is freshly calculated', async () => {
    vi.mocked(api.getStats).mockResolvedValue({
      by_category: { water: 3 },
      by_priority: { high: 0, normal: 3, low: 0 },
      cacheHeader: 'MISS',
    })

    render(<StatsView />)

    await waitFor(() => {
      expect(screen.getByText(/X-Cache: MISS/i)).toBeInTheDocument()
      expect(screen.getByText('WATER')).toBeInTheDocument()
    })
  })
})
