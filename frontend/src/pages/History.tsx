import { useState } from 'react'
import { WorkflowCard } from '../components/WorkflowCard'
import { useWorkflowList } from '../hooks/useWorkflow'
import type { WorkflowStatus } from '../types'

const PAGE_SIZE = 20
const STATUS_FILTERS: (WorkflowStatus | 'ALL')[] = [
  'ALL', 'RUNNING', 'COMPLETED', 'FAILED', 'CREATED',
]

export function History() {
  const [offset, setOffset] = useState(0)
  const [status, setStatus] = useState<WorkflowStatus | 'ALL'>('ALL')

  const { workflows, total, loading, error } = useWorkflowList({
    status: status === 'ALL' ? undefined : status,
    limit: PAGE_SIZE,
    offset,
  })

  const page = Math.floor(offset / PAGE_SIZE) + 1
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  function changeStatus(next: WorkflowStatus | 'ALL') {
    setStatus(next)
    setOffset(0)
  }

  return (
    <div className="history-page">
      <div className="section-header">
        <h2>History</h2>
        <span className="text-muted">{total} workflow{total === 1 ? '' : 's'}</span>
      </div>

      <div className="filter-row">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f}
            className={`filter-chip ${status === f ? 'filter-chip--active' : ''}`}
            onClick={() => changeStatus(f)}
          >
            {f === 'ALL' ? 'All' : f.charAt(0) + f.slice(1).toLowerCase()}
          </button>
        ))}
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading && workflows.length === 0 && (
        <div className="card-grid">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 100 }} />
          ))}
        </div>
      )}

      {!loading && workflows.length === 0 && !error && (
        <div className="empty-state glass-card">
          <p>No workflows match this filter.</p>
        </div>
      )}

      {workflows.length > 0 && (
        <div className="card-grid">
          {workflows.map((w) => (
            <WorkflowCard key={w.id} workflow={w} />
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="pagination">
          <button
            className="btn"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </button>
          <span className="text-muted">Page {page} of {totalPages}</span>
          <button
            className="btn"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
