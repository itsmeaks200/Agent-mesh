import { Link } from 'react-router-dom'
import { StatusBadge } from './StatusBadge'
import type { WorkflowSummary } from '../types'

function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export function WorkflowCard({ workflow }: { workflow: WorkflowSummary }) {
  const progress = workflow.total_tasks > 0 ? workflow.completed_tasks / workflow.total_tasks : 0

  return (
    <Link to={`/workflows/${workflow.id}`} className="workflow-card glass-card">
      <div className="workflow-card__top">
        <p className="workflow-card__request">
          {workflow.request_text ?? <span className="text-muted">Untitled workflow</span>}
        </p>
        <StatusBadge status={workflow.status} />
      </div>
      <div className="workflow-card__bottom">
        <div className="workflow-card__progress-track">
          <div className="workflow-card__progress-fill" style={{ width: `${progress * 100}%` }} />
        </div>
        <span className="workflow-card__meta">
          {workflow.completed_tasks}/{workflow.total_tasks} tasks · {timeAgo(workflow.created_at)}
        </span>
      </div>
    </Link>
  )
}
