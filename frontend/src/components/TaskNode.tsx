import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import { StatusBadge } from './StatusBadge'
import type { LiveTask } from '../types'

export type TaskNodeData = {
  task: LiveTask
  isSelected: boolean
}

export type TaskNodeType = Node<TaskNodeData, 'task'>

const STATUS_RING: Record<string, string> = {
  PENDING: 'var(--status-neutral)',
  QUEUED: 'var(--accent)',
  RUNNING: 'var(--accent)',
  COMPLETED: 'var(--status-good)',
  RETRYING: 'var(--status-warning)',
  FAILED: 'var(--status-critical)',
  CANCELLED: 'var(--status-neutral)',
}

export function TaskNode({ data }: NodeProps<TaskNodeType>) {
  const { task, isSelected } = data
  const ringColor = STATUS_RING[task.status] ?? 'var(--status-neutral)'

  return (
    <div
      className="task-node"
      style={{
        borderColor: isSelected ? ringColor : 'var(--border-strong)',
        boxShadow: isSelected
          ? `0 0 0 2px ${ringColor}, 0 16px 32px -16px rgba(0,0,0,0.7)`
          : task.status === 'RUNNING'
            ? `0 0 0 1px ${ringColor}55, 0 16px 32px -16px rgba(0,0,0,0.7)`
            : '0 16px 32px -16px rgba(0,0,0,0.7)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: ringColor }} />
      <div className="task-node__header">
        <span className="task-node__key">{task.task_key}</span>
        <StatusBadge status={task.status} />
      </div>
      <div className="task-node__tool">{task.tool_name}</div>
      {task.duration_ms != null && (
        <div className="task-node__meta">{task.duration_ms}ms</div>
      )}
      {task.error_message && (
        <div className="task-node__error" title={task.error_message}>
          {task.error_message}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ background: ringColor }} />
    </div>
  )
}
