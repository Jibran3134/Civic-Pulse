import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { SubmitView } from '../components/SubmitView'
import { api } from '../api/client'

import { Complaint } from '../types'

vi.mock('../api/client', () => ({
  api: {
    createComplaint: vi.fn(),
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

describe('SubmitView Honest Loading State', () => {
  it('renders honest loading state with progress during AI triage call', async () => {
    let resolveApi: (value: Complaint) => void
    const pendingPromise = new Promise<Complaint>((resolve) => {
      resolveApi = resolve
    })

    vi.mocked(api.createComplaint).mockReturnValue(pendingPromise)

    render(<SubmitView />)

    const textInput = screen.getByLabelText(/Complaint Description/i)
    const locInput = screen.getByLabelText(/Location \/ Neighborhood/i)
    const submitBtn = screen.getByRole('button', { name: /Submit for AI Triage/i })

    fireEvent.change(textInput, {
      target: { value: 'Main water pipeline burst flooding sector G-9 street 14' },
    })
    fireEvent.change(locInput, { target: { value: 'Sector G-9/2, Islamabad' } })
    fireEvent.click(submitBtn)

    // While unresolved, loading card should be visible
    expect(await screen.findByRole('status')).toBeInTheDocument()
    expect(screen.getByText(/AI Triage In Progress/i)).toBeInTheDocument()
    expect(screen.getByText(/Sanitizing citizen input/i)).toBeInTheDocument()

    // Resolve the promise
    resolveApi!({
      id: 'c1234567-89ab-cdef-0123-456789abcdef',
      text: 'Main water pipeline burst flooding sector G-9 street 14',
      location: 'Sector G-9/2, Islamabad',
      reporter_contact: null,
      category: 'water',
      priority: 'high',
      status: 'open',
      ai_summary: 'Major water pipeline rupture causing neighborhood flooding',
      triaged_by: 'simulated',
      triage_latency_ms: 320,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    })

    // Once resolved, triage result card appears
    await waitFor(() => {
      expect(screen.getByRole('region', { name: /Triage Result/i })).toBeInTheDocument()
      expect(screen.getByText(/Complaint Successfully Triaged/i)).toBeInTheDocument()
      expect(screen.getByText('WATER')).toBeInTheDocument()
      expect(screen.getByText('HIGH')).toBeInTheDocument()
      expect(screen.getByText('simulated')).toBeInTheDocument()
    })
  })
})
