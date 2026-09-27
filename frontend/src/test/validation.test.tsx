import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { SubmitView } from '../components/SubmitView'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    createComplaint: vi.fn(),
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

describe('SubmitView Client-Side Validation', () => {
  it('blocks submission and shows field validation errors when inputs are invalid', async () => {
    render(<SubmitView />)

    const submitBtn = screen.getByRole('button', { name: /Submit for AI Triage/i })
    fireEvent.click(submitBtn)

    expect(await screen.findByText(/Complaint text is required/i)).toBeInTheDocument()
    expect(screen.getByText(/Location is required/i)).toBeInTheDocument()
    expect(api.createComplaint).not.toHaveBeenCalled()
  })

  it('enforces minimum length constraints for text and location', async () => {
    render(<SubmitView />)

    const textInput = screen.getByLabelText(/Complaint Description/i)
    const locInput = screen.getByLabelText(/Location \/ Neighborhood/i)
    const submitBtn = screen.getByRole('button', { name: /Submit for AI Triage/i })

    // Too short (text < 10, loc < 3)
    fireEvent.change(textInput, { target: { value: 'short' } })
    fireEvent.change(locInput, { target: { value: 'G9' } })
    fireEvent.click(submitBtn)

    expect(await screen.findByText(/Complaint text must be at least 10 characters/i)).toBeInTheDocument()
    expect(screen.getByText(/Location must be at least 3 characters/i)).toBeInTheDocument()
    expect(api.createComplaint).not.toHaveBeenCalled()
  })
})
