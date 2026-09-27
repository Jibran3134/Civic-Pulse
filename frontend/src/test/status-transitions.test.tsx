import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DashboardView } from '../components/DashboardView'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    getComplaints: vi.fn(),
    updateComplaintStatus: vi.fn(),
    getStatusTransitions: vi.fn(),
  },
}))

/**
 * The assignment is explicit: valid status transitions are decided by the
 * backend and rendered by the frontend, "never duplicated in it" -- the moment
 * React contains a list of valid transitions there are two sources of truth.
 *
 * These tests pin that the action buttons are rendered from
 * GET /api/meta/status-transitions. A component that branched on
 * `status === 'open'` would fail the first test below, because the mock table
 * is deliberately not the real one.
 */
describe('DashboardView status transitions come from the backend', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getStatusTransitions).mockResolvedValue({
      transitions: {
        open: ['in_progress'],
        in_progress: ['rejected'],
        resolved: [],
        rejected: [],
      },
    })
  })

  it('renders exactly the actions the server returned, not a hard-coded rule', async () => {
    vi.mocked(api.getComplaints).mockResolvedValue({
      items: [
        {
          id: 'c-open',
          text: 'Burst water main flooding the street',
          location: 'Mall Road',
          reporter_contact: null,
          category: 'water',
          priority: 'high',
          status: 'open',
          ai_summary: 'Burst main',
          triaged_by: 'simulated',
          triage_latency_ms: 3,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
        {
          id: 'c-done',
          text: 'Streetlight repaired',
          location: 'Model Town',
          reporter_contact: null,
          category: 'streetlights',
          priority: 'normal',
          status: 'resolved',
          ai_summary: 'Repaired',
          triaged_by: 'simulated',
          triage_latency_ms: 2,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 2,
      page: 1,
      page_size: 10,
    })

    render(<DashboardView />)

    // The mock says open -> in_progress only. The real table also allows
    // open -> rejected, so a "Reject" button here proves the component is
    // reading the response rather than embedding the rule.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /in progress/i })).toBeInTheDocument()
    })
    expect(
      screen.queryByRole('button', { name: /reject/i })
    ).not.toBeInTheDocument()
  })

  it('shows no action buttons for a terminal status the server reports as final', async () => {
    vi.mocked(api.getComplaints).mockResolvedValue({
      items: [
        {
          id: 'c-done',
          text: 'Streetlight repaired',
          location: 'Model Town',
          reporter_contact: null,
          category: 'streetlights',
          priority: 'normal',
          status: 'resolved',
          ai_summary: 'Repaired',
          triaged_by: 'simulated',
          triage_latency_ms: 2,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    })

    render(<DashboardView />)

    await waitFor(() => {
      expect(screen.getByText(/terminal state/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /in progress/i })).not.toBeInTheDocument()
  })

  it('requests the transition table on mount', async () => {
    vi.mocked(api.getComplaints).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    })

    render(<DashboardView />)

    await waitFor(() => {
      expect(api.getStatusTransitions).toHaveBeenCalledTimes(1)
    })
  })

  it('still renders the complaint list when the transition endpoint fails', async () => {
    vi.mocked(api.getStatusTransitions).mockRejectedValue(new Error('404'))
    vi.mocked(api.getComplaints).mockResolvedValue({
      items: [
        {
          id: 'c-open',
          text: 'Pothole on the main road',
          location: 'Cantt',
          reporter_contact: null,
          category: 'roads',
          priority: 'normal',
          status: 'open',
          ai_summary: 'Pothole',
          triaged_by: 'simulated',
          triage_latency_ms: 1,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    })

    render(<DashboardView />)

    // The list is the point of the view; a missing action table degrades the
    // buttons, not the data.
    await waitFor(() => {
      expect(screen.getByText(/pothole on the main road/i)).toBeInTheDocument()
    })
  })

  it('sends the status the operator clicked, not one the component derived', async () => {
    vi.mocked(api.getComplaints).mockResolvedValue({
      items: [
        {
          id: 'c-open',
          text: 'Garbage not collected',
          location: 'Johar Town',
          reporter_contact: null,
          category: 'sanitation',
          priority: 'normal',
          status: 'open',
          ai_summary: 'Missed collection',
          triaged_by: 'simulated',
          triage_latency_ms: 4,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    })
    vi.mocked(api.updateComplaintStatus).mockResolvedValue({
      id: 'c-open',
      text: 'Garbage not collected',
      location: 'Johar Town',
      reporter_contact: null,
      category: 'sanitation',
      priority: 'normal',
      status: 'in_progress',
      ai_summary: 'Missed collection',
      triaged_by: 'simulated',
      triage_latency_ms: 4,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })

    render(<DashboardView />)

    const button = await screen.findByRole('button', { name: /in progress/i })
    await userEvent.click(button)

    await waitFor(() => {
      expect(api.updateComplaintStatus).toHaveBeenCalledWith('c-open', 'in_progress')
    })
  })
})
