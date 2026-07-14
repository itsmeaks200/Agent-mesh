import type { AgentRunResponse, Workflow, WorkflowListResponse } from '../types'

const API_BASE = '/api/v1'

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const message =
      body?.detail?.message ?? body?.detail ?? body?.message ?? `Request failed (${res.status})`
    throw new ApiError(res.status, typeof message === 'string' ? message : JSON.stringify(message))
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export function runAgent(requestText: string): Promise<AgentRunResponse> {
  return request<AgentRunResponse>('/agent/run', {
    method: 'POST',
    body: JSON.stringify({ request: requestText }),
  })
}

export function getWorkflow(workflowId: string): Promise<Workflow> {
  return request<Workflow>(`/workflows/${workflowId}`)
}

export function listWorkflows(params: {
  status?: string
  limit?: number
  offset?: number
} = {}): Promise<WorkflowListResponse> {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  query.set('limit', String(params.limit ?? 20))
  query.set('offset', String(params.offset ?? 0))
  return request<WorkflowListResponse>(`/workflows?${query.toString()}`)
}

export function deleteWorkflow(workflowId: string): Promise<void> {
  return request<void>(`/workflows/${workflowId}`, { method: 'DELETE' })
}

export function websocketUrl(workflowId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${API_BASE}/ws/workflows/${workflowId}`
}

export { ApiError }
