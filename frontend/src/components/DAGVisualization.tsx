import { useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  BackgroundVariant,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { TaskNode, type TaskNodeType } from './TaskNode'
import type { LiveTask } from '../types'

const NODE_TYPES = { task: TaskNode }

const EDGE_COLOR: Record<string, string> = {
  RUNNING: 'var(--accent)',
  QUEUED: 'var(--accent)',
  COMPLETED: 'var(--status-good)',
  RETRYING: 'var(--status-warning)',
  FAILED: 'var(--status-critical)',
}

function layout(tasks: LiveTask[]): { nodes: TaskNodeType[]; edges: Edge[]; selected: string | null } {
  const byKey = new Map(tasks.map((t) => [t.task_key, t]))
  const levelOf = new Map<string, number>()

  const computeLevel = (key: string, guard: Set<string>): number => {
    const cached = levelOf.get(key)
    if (cached !== undefined) return cached
    if (guard.has(key)) return 0
    guard.add(key)
    const deps = byKey.get(key)?.depends_on ?? []
    const level = deps.length === 0 ? 0 : 1 + Math.max(...deps.map((d) => computeLevel(d, guard)))
    levelOf.set(key, level)
    return level
  }
  for (const t of tasks) computeLevel(t.task_key, new Set())

  const byLevel = new Map<number, LiveTask[]>()
  for (const t of tasks) {
    const level = levelOf.get(t.task_key) ?? 0
    if (!byLevel.has(level)) byLevel.set(level, [])
    byLevel.get(level)!.push(t)
  }
  const maxCount = Math.max(1, ...Array.from(byLevel.values()).map((l) => l.length))
  const ROW_H = 130
  const COL_W = 260

  const nodes: TaskNodeType[] = []
  for (const [level, levelTasks] of byLevel) {
    const offsetY = ((maxCount - levelTasks.length) * ROW_H) / 2
    levelTasks.forEach((task, i) => {
      nodes.push({
        id: task.task_key,
        type: 'task',
        position: { x: level * COL_W, y: offsetY + i * ROW_H },
        data: { task, isSelected: false },
      })
    })
  }

  const edges: Edge[] = tasks.flatMap((task) =>
    task.depends_on
      .filter((dep) => byKey.has(dep))
      .map((dep) => ({
        id: `${dep}->${task.task_key}`,
        source: dep,
        target: task.task_key,
        animated: task.status === 'RUNNING' || task.status === 'QUEUED',
        style: { stroke: EDGE_COLOR[task.status] ?? 'var(--border-strong)', strokeWidth: 2 },
      }))
  )

  return { nodes, edges, selected: null }
}

interface DAGVisualizationProps {
  tasks: LiveTask[]
  selectedTaskKey: string | null
  onSelectTask: (taskKey: string) => void
}

export function DAGVisualization({ tasks, selectedTaskKey, onSelectTask }: DAGVisualizationProps) {
  const { nodes, edges } = useMemo(() => layout(tasks), [tasks])

  const nodesWithSelection = useMemo(
    () =>
      nodes.map((n) => ({
        ...n,
        data: { ...n.data, isSelected: n.id === selectedTaskKey },
      })),
    [nodes, selectedTaskKey],
  )

  if (tasks.length === 0) {
    return (
      <div className="dag-empty">
        <div className="skeleton" style={{ width: '100%', height: '100%' }} />
      </div>
    )
  }

  return (
    <div className="dag-canvas">
      <ReactFlow
        nodes={nodesWithSelection}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodeClick={(_, node) => onSelectTask(node.id)}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--gridline)" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
