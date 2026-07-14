import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { DAGVisualization } from '../components/DAGVisualization'
import { StatusBadge } from '../components/StatusBadge'
import { useWorkflowSocket } from '../hooks/useWebSocket'
import { useWorkflowStore } from '../stores/workflowStore'

function formatDuration(startedAt: string | null, completedAt: string | null): string | null {
  if (!startedAt) return null
  const end = completedAt ? new Date(completedAt).getTime() : Date.now()
  const seconds = Math.max(0, (end - new Date(startedAt).getTime()) / 1000)
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
}

export function WorkflowDetail() {
  const { workflowId } = useParams<{ workflowId: string }>()
  useWorkflowSocket(workflowId)

  const store = useWorkflowStore()
  const [selectedTaskKey, setSelectedTaskKey] = useState<string | null>(null)

  const tasks = useMemo(
    () => store.taskOrder.map((key) => store.tasks[key]).filter(Boolean),
    [store.taskOrder, store.tasks],
  )
  const selectedTask = selectedTaskKey ? store.tasks[selectedTaskKey] : null

  if (store.connectionStatus === 'connecting' && tasks.length === 0) {
    return (
      <div className="workflow-detail">
        <div className="skeleton" style={{ height: 48, marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 520 }} />
      </div>
    )
  }

  if (store.connectionStatus === 'closed' && tasks.length === 0) {
    return (
      <div className="empty-state glass-card">
        <p>Workflow not found or connection failed.</p>
      </div>
    )
  }

  const progress = store.totalTasks > 0 ? store.completedTasks / store.totalTasks : 0
  const duration = formatDuration(store.startedAt, store.completedAt)

  return (
    <div className="workflow-detail">
      <div className="workflow-detail__header glass-card">
        <div className="workflow-detail__header-top">
          <h1 className="workflow-detail__title">
            {store.requestText ?? 'Workflow'}
          </h1>
          {store.status && <StatusBadge status={store.status} />}
        </div>
        <div className="workflow-detail__header-meta">
          <span>{store.completedTasks}/{store.totalTasks} tasks</span>
          {duration && <span>· {duration}</span>}
          <span className={`conn-dot conn-dot--${store.connectionStatus}`} title={`WebSocket: ${store.connectionStatus}`} />
        </div>
        <div className="workflow-card__progress-track">
          <div className="workflow-card__progress-fill" style={{ width: `${progress * 100}%` }} />
        </div>
        {store.errorMessage && <div className="error-banner">{store.errorMessage}</div>}
      </div>

      <div className="workflow-detail__body">
        <DAGVisualization tasks={tasks} selectedTaskKey={selectedTaskKey} onSelectTask={setSelectedTaskKey} />

        <div className="task-panel glass-card">
          {!selectedTask && (
            <div className="empty-state">
              <p>Click a node to inspect a task.</p>
            </div>
          )}
          {selectedTask && (
            <div className="task-panel__content">
              <div className="task-panel__header">
                <h3>{selectedTask.task_key}</h3>
                <StatusBadge status={selectedTask.status} />
              </div>
              <dl className="task-panel__list">
                <dt>Tool</dt>
                <dd className="mono">{selectedTask.tool_name}</dd>

                <dt>Depends on</dt>
                <dd>{selectedTask.depends_on.length ? selectedTask.depends_on.join(', ') : '—'}</dd>

                <dt>Retries</dt>
                <dd>{selectedTask.retry_count}</dd>

                {selectedTask.duration_ms != null && (
                  <>
                    <dt>Duration</dt>
                    <dd>{selectedTask.duration_ms}ms</dd>
                  </>
                )}
              </dl>

              {selectedTask.params && Object.keys(selectedTask.params).length > 0 && (
                <>
                  <p className="task-panel__section-label">Params</p>
                  <pre className="task-panel__pre">{JSON.stringify(selectedTask.params, null, 2)}</pre>
                </>
              )}

              {selectedTask.error_message && (
                <>
                  <p className="task-panel__section-label">Error</p>
                  <div className="error-banner">{selectedTask.error_message}</div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
