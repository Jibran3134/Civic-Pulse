import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ErrorBoundary } from '../components/ErrorBoundary'

const ThrowingComponent = () => {
  throw new Error('Simulated UI crash in child component')
}

describe('ErrorBoundary', () => {
  it('catches render errors in children and displays fallback UI', () => {
    // Suppress console.error in test output for intentional throw
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    )

    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument()
    expect(screen.getByText(/Simulated UI crash in child component/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Reload Application/i })).toBeInTheDocument()

    consoleSpy.mockRestore()
  })

  it('renders children normally when there is no error', () => {
    render(
      <ErrorBoundary>
        <div>Normal healthy component</div>
      </ErrorBoundary>
    )

    expect(screen.getByText('Normal healthy component')).toBeInTheDocument()
  })
})
