import { Link } from 'react-router-dom'
import { InputBar } from '../components/InputBar'
import { WorkflowCard } from '../components/WorkflowCard'
import { useWorkflowList } from '../hooks/useWorkflow'

export function Home() {
  const { workflows, loading, error } = useWorkflowList({ limit: 6, pollMs: 5000 })

  return (
    <div className="home-page">
      <div className="home-page__hero">
        <h1>What should AgentMesh run?</h1>
        <p className="text-muted">
          Describe a task in plain language — the planner turns it into an executable workflow.
        </p>
      </div>

      <InputBar />

      <div className="home-page__recent">
        <div className="section-header">
          <h2>Recent workflows</h2>
          <Link to="/history" className="section-header__link">View all</Link>
        </div>

        {error && <div className="error-banner">{error}</div>}

        {loading && workflows.length === 0 && (
          <div className="card-grid">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="skeleton" style={{ height: 100 }} />
            ))}
          </div>
        )}

        {!loading && workflows.length === 0 && !error && (
          <div className="empty-state glass-card">
            <p>No workflows yet.</p>
            <p className="text-muted">Run a request above to get started.</p>
          </div>
        )}

        {workflows.length > 0 && (
          <div className="card-grid">
            {workflows.map((w) => (
              <WorkflowCard key={w.id} workflow={w} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
