import React, { useState, useEffect } from 'react'
import { api, ApiError } from '../api/client'
import { Complaint } from '../types'
import { Send, CheckCircle2, AlertCircle, Clock, ShieldCheck, Cpu, MapPin, FileText, User } from 'lucide-react'

const TRIAGE_STEPS = [
  'Sanitizing citizen input & redacting PII patterns...',
  'Querying pluggable AI triage provider (LLM / Simulated)...',
  'Validating structured classification schema...',
  'Persisting record & updating Redis cache...',
]

export const SubmitView: React.FC = () => {
  const [text, setText] = useState('')
  const [location, setLocation] = useState('')
  const [contact, setContact] = useState('')

  const [fieldErrors, setFieldErrors] = useState<{ text?: string; location?: string }>({})
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [currentStep, setCurrentStep] = useState(0)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [triageResult, setTriageResult] = useState<Complaint | null>(null)

  useEffect(() => {
    let timer: NodeJS.Timeout
    let stepTimer: NodeJS.Timeout

    if (isSubmitting) {
      setElapsedSeconds(0)
      setCurrentStep(0)

      timer = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1)
      }, 1000)

      stepTimer = setInterval(() => {
        setCurrentStep((prev) => (prev < TRIAGE_STEPS.length - 1 ? prev + 1 : prev))
      }, 1800)
    }

    return () => {
      clearInterval(timer)
      clearInterval(stepTimer)
    }
  }, [isSubmitting])

  const validate = (): boolean => {
    const errors: { text?: string; location?: string } = {}
    const trimmedText = text.trim()
    const trimmedLocation = location.trim()

    if (!trimmedText) {
      errors.text = 'Complaint text is required.'
    } else if (trimmedText.length < 10) {
      errors.text = 'Complaint text must be at least 10 characters.'
    } else if (trimmedText.length > 2000) {
      errors.text = 'Complaint text cannot exceed 2000 characters.'
    }

    if (!trimmedLocation) {
      errors.location = 'Location is required.'
    } else if (trimmedLocation.length < 3) {
      errors.location = 'Location must be at least 3 characters.'
    } else if (trimmedLocation.length > 200) {
      errors.location = 'Location cannot exceed 200 characters.'
    }

    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitError(null)

    if (!validate()) {
      return
    }

    setIsSubmitting(true)
    setTriageResult(null)

    try {
      const complaint = await api.createComplaint({
        text: text.trim(),
        location: location.trim(),
        reporter_contact: contact.trim() || null,
      })

      setTriageResult(complaint)
      setText('')
      setLocation('')
      setContact('')
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setSubmitError(err.detail)
        if (err.field_errors) {
          setFieldErrors((prev) => ({ ...prev, ...err.field_errors }))
        }
      } else {
        setSubmitError((err as Error).message || 'Failed to submit complaint')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="view-container">
      <div className="view-header">
        <h2 className="view-title">Citizen Grievance Submission</h2>
        <p className="view-desc">
          Describe the civic issue in your neighborhood. Our resilient AI triage pipeline redacts sensitive data,
          determines municipal classification, and routes it with prioritized urgency.
        </p>
      </div>

      <div className="submit-grid">
        <div className="form-card">
          <form onSubmit={handleSubmit} noValidate>
            <div className="form-group">
              <label htmlFor="complaint-text">
                <FileText size={16} /> Complaint Description <span className="req">*</span>
              </label>
              <textarea
                id="complaint-text"
                rows={5}
                placeholder="Describe the problem in detail (e.g., Water pipeline burst on main road causing severe flooding...)"
                value={text}
                onChange={(e) => {
                  setText(e.target.value)
                  if (fieldErrors.text) setFieldErrors((prev) => ({ ...prev, text: undefined }))
                }}
                disabled={isSubmitting}
                className={fieldErrors.text ? 'input-error' : ''}
              />
              <div className="form-help">
                <span>Minimum 10 characters</span>
                <span className={text.length > 2000 ? 'text-danger' : ''}>{text.length}/2000</span>
              </div>
              {fieldErrors.text && (
                <div className="field-error-msg" role="alert">
                  <AlertCircle size={14} /> {fieldErrors.text}
                </div>
              )}
            </div>

            <div className="form-group">
              <label htmlFor="complaint-location">
                <MapPin size={16} /> Location / Neighborhood <span className="req">*</span>
              </label>
              <input
                id="complaint-location"
                type="text"
                placeholder="e.g., Sector G-9/2, Street 14, Islamabad"
                value={location}
                onChange={(e) => {
                  setLocation(e.target.value)
                  if (fieldErrors.location) setFieldErrors((prev) => ({ ...prev, location: undefined }))
                }}
                disabled={isSubmitting}
                className={fieldErrors.location ? 'input-error' : ''}
              />
              {fieldErrors.location && (
                <div className="field-error-msg" role="alert">
                  <AlertCircle size={14} /> {fieldErrors.location}
                </div>
              )}
            </div>

            <div className="form-group">
              <label htmlFor="complaint-contact">
                <User size={16} /> Reporter Contact <span className="opt">(Optional)</span>
              </label>
              <input
                id="complaint-contact"
                type="text"
                placeholder="Phone number, email, or citizen identifier (auto-redacted before AI)"
                value={contact}
                onChange={(e) => setContact(e.target.value)}
                disabled={isSubmitting}
              />
            </div>

            {submitError && (
              <div className="alert-banner alert-danger" role="alert">
                <AlertCircle size={18} />
                <span>{submitError}</span>
              </div>
            )}

            <button
              id="submit-complaint-btn"
              type="submit"
              className="btn btn-primary btn-block"
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <span className="spinner" />
                  <span>Processing with AI ({elapsedSeconds}s)...</span>
                </>
              ) : (
                <>
                  <Send size={18} />
                  <span>Submit for AI Triage</span>
                </>
              )}
            </button>
          </form>
        </div>

        <div className="status-sidebar">
          {isSubmitting && (
            <div className="loading-card" role="status" aria-live="polite">
              <div className="loading-header">
                <div className="loading-pulse-ring">
                  <Cpu size={28} className="pulse-icon" />
                </div>
                <div>
                  <h3 className="loading-title">AI Triage In Progress</h3>
                  <div className="elapsed-time">
                    <Clock size={14} /> Elapsed time: {elapsedSeconds} seconds
                  </div>
                </div>
              </div>

              <div className="steps-progress">
                {TRIAGE_STEPS.map((step, idx) => (
                  <div
                    key={idx}
                    className={`step-item ${
                      idx < currentStep ? 'completed' : idx === currentStep ? 'active' : 'pending'
                    }`}
                  >
                    <div className="step-dot" />
                    <span className="step-label">{step}</span>
                  </div>
                ))}
              </div>

              <div className="honest-notice">
                <ShieldCheck size={16} />
                <span>
                  <strong>Honest Triage Notice:</strong> LLM inference and guardrail validation typically require 2–5 seconds. We keep you informed in real time rather than freezing.
                </span>
              </div>
            </div>
          )}

          {!isSubmitting && triageResult && (
            <div className="result-card success-card" role="region" aria-label="Triage Result">
              <div className="result-card-header">
                <CheckCircle2 size={24} color="#10b981" />
                <div>
                  <h3>Complaint Successfully Triaged</h3>
                  <span className="result-id">ID: {triageResult.id}</span>
                </div>
              </div>

              <div className="result-badges">
                <div className="badge-item">
                  <span className="badge-label">Category</span>
                  <span className={`badge badge-category badge-${triageResult.category}`}>
                    {triageResult.category.toUpperCase()}
                  </span>
                </div>

                <div className="badge-item">
                  <span className="badge-label">Priority</span>
                  <span className={`badge badge-priority badge-${triageResult.priority}`}>
                    {triageResult.priority.toUpperCase()}
                  </span>
                </div>

                <div className="badge-item">
                  <span className="badge-label">Status</span>
                  <span className="badge badge-status">{triageResult.status}</span>
                </div>

                <div className="badge-item">
                  <span className="badge-label">Triage Provider</span>
                  <span className="badge badge-provider">{triageResult.triaged_by}</span>
                </div>
              </div>

              {triageResult.ai_summary && (
                <div className="summary-box">
                  <div className="summary-title">AI Triage Summary</div>
                  <p className="summary-text">{triageResult.ai_summary}</p>
                </div>
              )}

              <div className="meta-footer">
                <span>⚡ Latency: <strong>{triageResult.triage_latency_ms} ms</strong></span>
                <span>📍 Location: <strong>{triageResult.location}</strong></span>
              </div>
            </div>
          )}

          {!isSubmitting && !triageResult && (
            <div className="info-card">
              <h3 className="info-title">
                <ShieldCheck size={20} color="#3b82f6" /> Resilient Architecture
              </h3>
              <ul className="info-list">
                <li>
                  <strong>Automated PII Redaction:</strong> Pakistani phone numbers (+92/03xx), CNICs, and email addresses are masked before external LLM dispatch.
                </li>
                <li>
                  <strong>Fault-Tolerant Fallback:</strong> If the primary LLM times out or is rate-limited, the system seamlessly transitions to deterministic rule-based triage without throwing 500s.
                </li>
                <li>
                  <strong>24-Hour Semantic Cache:</strong> Duplicate complaints within identical locations are served instantly from Redis.
                </li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
