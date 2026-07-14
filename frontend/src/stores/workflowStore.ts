import { create } from 'zustand'
import type {
  LiveTask,
  TaskUpdateEvent,
  WorkflowSnapshotEvent,
  WorkflowStatus,
  WorkflowUpdateEvent,
} from '../types'

export type ConnectionStatus = 'connecting' | 'open' | 'closed'

interface WorkflowStoreState {
  workflowId: string | null
  status: WorkflowStatus | null
  requestText: string | null
  totalTasks: number
  completedTasks: number
  errorMessage: string | null
  startedAt: string | null
  completedAt: string | null
  tasks: Record<string, LiveTask>
  taskOrder: string[]
  connectionStatus: ConnectionStatus

  setConnectionStatus: (status: ConnectionStatus) => void
  applySnapshot: (event: WorkflowSnapshotEvent) => void
  applyTaskUpdate: (event: TaskUpdateEvent) => void
  applyWorkflowUpdate: (event: WorkflowUpdateEvent) => void
  reset: (workflowId: string) => void
}

export const useWorkflowStore = create<WorkflowStoreState>((set) => ({
  workflowId: null,
  status: null,
  requestText: null,
  totalTasks: 0,
  completedTasks: 0,
  errorMessage: null,
  startedAt: null,
  completedAt: null,
  tasks: {},
  taskOrder: [],
  connectionStatus: 'connecting',

  setConnectionStatus: (connectionStatus) => set({ connectionStatus }),

  applySnapshot: (event) =>
    set(() => {
      const tasks: Record<string, LiveTask> = {}
      const taskOrder: string[] = []
      for (const t of event.tasks) {
        tasks[t.task_key] = t
        taskOrder.push(t.task_key)
      }
      return {
        workflowId: event.workflow_id,
        status: event.status,
        requestText: event.request_text,
        totalTasks: event.total_tasks,
        completedTasks: event.completed_tasks,
        errorMessage: event.error_message,
        startedAt: event.started_at,
        completedAt: event.completed_at,
        tasks,
        taskOrder,
      }
    }),

  applyTaskUpdate: (event) =>
    set((state) => {
      const existing = state.tasks[event.task_key]
      if (!existing) return state
      return {
        tasks: {
          ...state.tasks,
          [event.task_key]: {
            ...existing,
            status: event.status,
            duration_ms: event.duration_ms ?? existing.duration_ms,
            error_message: event.error_message ?? null,
          },
        },
      }
    }),

  applyWorkflowUpdate: (event) =>
    set((state) => ({
      status: event.status,
      totalTasks: event.total_tasks ?? state.totalTasks,
      completedTasks: event.completed_tasks ?? state.completedTasks,
      errorMessage: event.error_message ?? null,
    })),

  reset: (workflowId) =>
    set({
      workflowId,
      status: null,
      requestText: null,
      totalTasks: 0,
      completedTasks: 0,
      errorMessage: null,
      startedAt: null,
      completedAt: null,
      tasks: {},
      taskOrder: [],
      connectionStatus: 'connecting',
    }),
}))
