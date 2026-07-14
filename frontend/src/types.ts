export type WorkflowStatus =
  | 'CREATED'
  | 'COMPILING'
  | 'COMPILED'
  | 'SCHEDULED'
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export type TaskStatus =
  | 'PENDING'
  | 'QUEUED'
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED'
  | 'RETRYING'
  | 'CANCELLED'

export interface TaskResult {
  id: string
  task_id: string
  data: Record<string, unknown> | null
  status: string
  duration_ms: number | null
  created_at: string
}

export interface Task {
  id: string
  task_key: string
  tool_name: string
  params: Record<string, unknown>
  status: TaskStatus
  retry_count: number
  max_retries: number
  timeout_seconds: number
  created_at: string
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  error_message: string | null
  worker_id: string | null
  depends_on_keys: string[]
  result: TaskResult | null
}

export interface Workflow {
  id: string
  status: WorkflowStatus
  request_text: string | null
  total_tasks: number
  completed_tasks: number
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  tasks: Task[]
}

export interface WorkflowSummary {
  id: string
  status: WorkflowStatus
  request_text: string | null
  total_tasks: number
  completed_tasks: number
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface WorkflowListResponse {
  workflows: WorkflowSummary[]
  total: number
  limit: number
  offset: number
}

export interface AgentRunResponse {
  workflow_id: string
  status: string
  tasks_planned: number
  message: string
}

/** Live task view kept in the store — merges REST task shape with WS event fields. */
export interface LiveTask {
  task_key: string
  tool_name: string
  status: TaskStatus
  retry_count: number
  duration_ms: number | null
  error_message: string | null
  depends_on: string[]
  params?: Record<string, unknown>
}

export interface WorkflowSnapshotEvent {
  type: 'snapshot'
  workflow_id: string
  status: WorkflowStatus
  request_text: string | null
  total_tasks: number
  completed_tasks: number
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  tasks: LiveTask[]
}

export interface TaskUpdateEvent {
  type: 'task_update'
  workflow_id: string
  task_key: string
  status: TaskStatus
  duration_ms?: number | null
  error_message?: string | null
}

export interface WorkflowUpdateEvent {
  type: 'workflow_update'
  workflow_id: string
  status: WorkflowStatus
  total_tasks?: number
  completed_tasks?: number
  error_message?: string | null
}

export interface WorkflowErrorEvent {
  type: 'error'
  message: string
}

export type WorkflowWsEvent =
  | WorkflowSnapshotEvent
  | TaskUpdateEvent
  | WorkflowUpdateEvent
  | WorkflowErrorEvent
