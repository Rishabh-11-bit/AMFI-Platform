import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import {
  LayoutDashboard, AlertTriangle, CheckSquare,
  Server, Network, Activity, RefreshCw
} from 'lucide-react'
import { api } from './api/client'
import Dashboard   from './pages/Dashboard'
import Incidents   from './pages/Incidents'
import IncidentDetail from './pages/IncidentDetail'
import Approvals   from './pages/Approvals'
import Hosts       from './pages/Hosts'
import NMSSources  from './pages/NMSSources'
import Analytics   from './pages/Analytics'

function Sidebar({ pendingApprovals, openIncidents, health }) {
  const ai    = health?.agent
  const ollamaOk = ai?.ollama_running && ai?.model_ready

  return (
    <aside className="sidebar">
      <div className="logo">
        <div className="logo-name">AMFI</div>
        <div className="logo-sub">Agent v4 · NOC AI</div>
      </div>

      <div className="agent-status">
        <div className="status-row">
          <div className={`dot ${health ? 'on' : 'off'}`} />
          <span className="status-label">{health ? 'System Online' : 'Connecting…'}</span>
        </div>
        <div className="status-row">
          <div className={`dot ${ollamaOk ? 'on' : ai?.claude_enabled ? 'warn' : 'off'}`} />
          <span className="status-label">
            {ollamaOk
              ? `Ollama · ${ai?.ollama_model}`
              : ai?.claude_enabled
              ? 'Claude API fallback'
              : 'No AI engine'}
          </span>
        </div>
      </div>

      <nav className="nav">
        <div className="nav-section">Operations</div>
        <NavLink to="/" end className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <LayoutDashboard size={15} /><span>Dashboard</span>
        </NavLink>
        <NavLink to="/incidents" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <AlertTriangle size={15} /><span>Incidents</span>
          {openIncidents > 0 && <span className="nav-badge">{openIncidents}</span>}
        </NavLink>
        <NavLink to="/approvals" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <CheckSquare size={15} /><span>Approvals</span>
          {pendingApprovals > 0 && <span className="nav-badge">{pendingApprovals}</span>}
        </NavLink>
        <NavLink to="/analytics" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <Activity size={15} /><span>Analytics</span>
        </NavLink>

        <div className="nav-section" style={{ marginTop: 8 }}>Configuration</div>
        <NavLink to="/hosts" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <Server size={15} /><span>Hosts (CMDB)</span>
        </NavLink>
        <NavLink to="/nms" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <Network size={15} /><span>NMS Sources</span>
        </NavLink>
      </nav>
    </aside>
  )
}

export default function App() {
  const [health,  setHealth]  = useState(null)
  const [stats,   setStats]   = useState(null)

  const load = async () => {
    try { setHealth(await api.health()) } catch {}
    try { setStats(await api.dashboard()) } catch {}
  }

  useEffect(() => { load(); const t = setInterval(load, 12000); return () => clearInterval(t) }, [])

  const pending = stats?.pending_approvals || 0
  const open    = stats?.incidents?.open    || 0

  return (
    <BrowserRouter>
      <div className="layout">
        <Sidebar pendingApprovals={pending} openIncidents={open} health={health} />
        <main className="content">
          <Routes>
            <Route path="/"               element={<Dashboard  stats={stats} health={health} />} />
            <Route path="/incidents"      element={<Incidents />} />
            <Route path="/incidents/:id"  element={<IncidentDetail />} />
            <Route path="/approvals"      element={<Approvals />} />
            <Route path="/analytics"      element={<Analytics />} />
            <Route path="/hosts"          element={<Hosts />} />
            <Route path="/nms"            element={<NMSSources />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
