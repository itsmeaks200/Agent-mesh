import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { runAgent, ApiError } from '../api/client'

const PLACEHOLDER = 'Fetch two APIs in parallel, summarize the results with an LLM, and save a report...'

export function InputBar() {
  const [value, setValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const requestText = value.trim()
    if (!requestText || submitting) return

    setSubmitting(true)
    setError(null)
    try {
      const res = await runAgent(requestText)
      navigate(`/workflows/${res.workflow_id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to plan workflow.')
      setSubmitting(false)
    }
  }

  return (
    <form className="input-bar glass-card" onSubmit={handleSubmit}>
      <textarea
        className="text-area input-bar__textarea"
        placeholder={PLACEHOLDER}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit(e)
        }}
        disabled={submitting}
        rows={3}
      />
      <div className="input-bar__footer">
        <span className="input-bar__hint">⌘/Ctrl + Enter to run</span>
        <button className="btn btn--primary" type="submit" disabled={submitting || !value.trim()}>
          {submitting ? 'Planning…' : 'Run'}
        </button>
      </div>
      {error && <div className="error-banner input-bar__error">{error}</div>}
    </form>
  )
}
