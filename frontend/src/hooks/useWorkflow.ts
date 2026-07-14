import { useCallback, useEffect, useState } from 'react'
import { listWorkflows } from '../api/client'
import type { WorkflowStatus, WorkflowSummary } from '../types'

interface UseWorkflowListOptions {
  status?: WorkflowStatus
  limit?: number
  offset?: number
  /** Poll interval in ms; omit to fetch once. */
  pollMs?: number
}

interface UseWorkflowListResult {
  workflows: WorkflowSummary[]
  total: number
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useWorkflowList(options: UseWorkflowListOptions = {}): UseWorkflowListResult {
  const { status, limit = 20, offset = 0, pollMs } = options
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  const refetch = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listWorkflows({ status, limit, offset })
      .then((res) => {
        if (cancelled) return
        setWorkflows(res.workflows)
        setTotal(res.total)
        setError(null)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [status, limit, offset, tick])

  useEffect(() => {
    if (!pollMs) return
    const id = setInterval(refetch, pollMs)
    return () => clearInterval(id)
  }, [pollMs, refetch])

  return { workflows, total, loading, error, refetch }
}
