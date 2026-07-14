import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import { Home } from './pages/Home'
import { History } from './pages/History'
import { WorkflowDetail } from './pages/WorkflowDetail'

function Nav() {
  return (
    <nav className="app-nav">
      <NavLink to="/" className="app-nav__brand">
        <span className="app-nav__brand-mark" />
        AgentMesh
      </NavLink>
      <div className="app-nav__links">
        <NavLink
          to="/"
          end
          className={({ isActive }) => `app-nav__link ${isActive ? 'app-nav__link--active' : ''}`}
        >
          Home
        </NavLink>
        <NavLink
          to="/history"
          className={({ isActive }) => `app-nav__link ${isActive ? 'app-nav__link--active' : ''}`}
        >
          History
        </NavLink>
      </div>
    </nav>
  )
}

function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <Nav />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/history" element={<History />} />
            <Route path="/workflows/:workflowId" element={<WorkflowDetail />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
