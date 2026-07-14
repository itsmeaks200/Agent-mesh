import { useEffect, useRef } from 'react'
import { websocketUrl } from '../api/client'
import { useWorkflowStore } from '../stores/workflowStore'
import type { WorkflowWsEvent } from '../types'

const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])

/** Opens a live event stream for one workflow and feeds it into the workflow store. */
export function useWorkflowSocket(workflowId: string | undefined) {
  const reset = useWorkflowStore((s) => s.reset)
  const applySnapshot = useWorkflowStore((s) => s.applySnapshot)
  const applyTaskUpdate = useWorkflowStore((s) => s.applyTaskUpdate)
  const applyWorkflowUpdate = useWorkflowStore((s) => s.applyWorkflowUpdate)
  const setConnectionStatus = useWorkflowStore((s) => s.setConnectionStatus)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!workflowId) return

    reset(workflowId)
    setConnectionStatus('connecting')

    const socket = new WebSocket(websocketUrl(workflowId))
    socketRef.current = socket

    socket.onopen = () => setConnectionStatus('open')
    socket.onclose = () => setConnectionStatus('closed')
    socket.onerror = () => setConnectionStatus('closed')

    socket.onmessage = (raw) => {
      const event = JSON.parse(raw.data) as WorkflowWsEvent
      switch (event.type) {
        case 'snapshot':
          applySnapshot(event)
          if (TERMINAL_STATUSES.has(event.status)) socket.close()
          break
        case 'task_update':
          applyTaskUpdate(event)
          break
        case 'workflow_update':
          applyWorkflowUpdate(event)
          if (event.status && TERMINAL_STATUSES.has(event.status)) socket.close()
          break
        case 'error':
          setConnectionStatus('closed')
          break
      }
    }

    return () => {
      socket.close()
      socketRef.current = null
    }
  }, [workflowId, reset, applySnapshot, applyTaskUpdate, applyWorkflowUpdate, setConnectionStatus])
}
