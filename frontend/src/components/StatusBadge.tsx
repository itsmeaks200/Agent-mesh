import type { TaskStatus, WorkflowStatus } from '../types'

const LABELS: Record<string, string> = {
  PENDING: 'Pending',
  QUEUED: 'Queued',
  RUNNING: 'Running',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  RETRYING: 'Retrying',
  CANCELLED: 'Cancelled',
  CREATED: 'Created',
  COMPILING: 'Compiling',
  COMPILED: 'Compiled',
  SCHEDULED: 'Scheduled',
}

export function StatusBadge({ status }: { status: TaskStatus | WorkflowStatus | string }) {
  const modifier = status.toLowerCase()
  return (
    <span className={`status-badge status-badge--${modifier}`}>
      <span className="status-dot" />
      {LABELS[status] ?? status}
    </span>
  )
}
