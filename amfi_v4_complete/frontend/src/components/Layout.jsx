import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useEffect, useState, useRef } from 'react'
import { api } from '../api'
import { useAuth } from '../contexts/AuthContext'

const NAV = [
  { to: '/',           icon: '⬡',  label: 'Dashboard'  },
  { to: '/incidents',  icon: '⚡',  label: 'Incidents'  },
  { to: '/hosts',      icon: '◈',  label: 'Hosts'       },
  { to: '/alerts',     icon: '◉',  label: 'Alerts'      },
  { to: '/approvals',  icon: '✔',  label: 'Approvals'  },
  { to: '/users',      icon: '👤', label: 'Users'       },
]

export default function Layout() {
  const { user, logout, authEnabled } = useAuth()
  const navigate = useNavigate()

  const [health,           setHealth]           = useState(null)
  const [clock,            setClock]            = useState(new Date())
  const [pendingApprovals, setPendingApprovals] = useState(0)
  const [wsStatus,         setWsStatus]         = useState('disconnected') // connected|disconnected|error
  const wsRef = useRef(null)

  // ── Live clock ──────────────────────────────────────────────────────────────
  useEffect(() => {
    const tick = setInterval(() => setClock(new Date()), 1000)
    return () => clearInterval(tick)
  }, [])

  // ── Health polling ──────────────────────────────────────────────────────────
  useEffect(() => {
    const load = () => api.health().then(setHealth).catch(() => {})
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  // ── Pending approvals badge ─────────────────────────────────────────────────
  const loadApprovals = () => {
    api.approvals('pending')
      .then(data => setPendingApprovals(Array.isArray(data) ? data.length : 0))
      .catch(() => {})
  }
  useEffect(() => {
    loadApprovals()
    const t = setInterval(loadApprovals, 30000)
    return () => clearInterval(t)
  }, [])

  // ── WebSocket connection ─────────────────────────────────────────────────────
  useEffect(() => {
    let reconnectTimer = null
    let dead = false

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      // Pass JWT token as query param so the server can verify it when AUTH_ENABLED=true
      const token = localStorage.getItem('amfi_token')
      const wsUrl = token
        ? `${proto}://${window.location.host}/ws?token=${encodeURIComponent(token)}`
        : `${proto}://${window.location.host}/ws`
      const ws    = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setWsStatus('connected')
        // Keepalive ping every 25s
        ws._pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        }, 25000)
      }

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data)
          if (msg.type === 'ping') return   // server keepalive — ignore
          // Broadcast to all pages via CustomEvent
          window.dispatchEvent(new CustomEvent('amfi:ws', { detail: msg }))
          // Refresh approval badge on relevant events
          if (msg.type === 'incident_created' || msg.type === 'approval_created' || msg.type === 'approval_required') {
            loadApprovals()
          }
        } catch { /* malformed — ignore */ }
      }

      ws.onerror = () => setWsStatus('error')

      ws.onclose = () => {
        clearInterval(ws._pingInterval)
        setWsStatus('disconnected')
        if (!dead) {
          reconnectTimer = setTimeout(connect, 5000)
        }
      }
    }

    connect()
    return () => {
      dead = true
      clearTimeout(reconnectTimer)
      if (wsRef.current) {
        clearInterval(wsRef.current._pingInterval)
        wsRef.current.close()
      }
    }
  }, [])

  const doLogout = () => { logout(); navigate('/login') }

  const ollama = health?.agent?.ollama_running
  const claude = health?.agent?.claude_enabled
  const active = health?.incident_counts?.active ?? 0

  const wsColor = wsStatus === 'connected' ? 'var(--green)' : wsStatus === 'error' ? 'var(--red)' : 'var(--text3)'

  return (
    <div style={{ display:'flex', height:'100vh', width:'100%', overflow:'hidden' }}>

      {/* ── Sidebar ───────────────────────────────────────────────── */}
      <aside className="sidebar" style={{
        width: 'var(--sidebar-w)', flexShrink: 0,
        background: 'var(--bg2)', borderRight: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* Logo */}
        <div style={{
          padding: '18px 20px 16px',
          borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: 'linear-gradient(135deg, #1f6feb 0%, #bc8cff 100%)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 16, flexShrink: 0,
          }}>⬡</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: '.03em' }}>AMFI</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', letterSpacing: '.08em', textTransform: 'uppercase' }}>NOC Platform v4</div>
          </div>
        </div>

        {/* Live status bar */}
        <div style={{
          padding: '10px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 12,
        }}>
          <span className="pulse pulse-green" />
          <span style={{ color: 'var(--green)', fontWeight: 600 }}>LIVE</span>
          <span title={`WebSocket: ${wsStatus}`} style={{ marginLeft: 4, color: wsColor, fontSize: 10 }}>
            {wsStatus === 'connected' ? '⬤ WS' : wsStatus === 'error' ? '⬤ WS ERR' : '◯ WS'}
          </span>
          <span style={{ color: 'var(--text3)', marginLeft: 'auto', fontVariantNumeric: 'tabular-nums' }}>
            {clock.toLocaleTimeString('en-GB')}
          </span>
        </div>

        {/* Navigation */}
        <nav style={{ flex: 1, padding: '12px 10px', overflowY: 'auto' }}>
          {NAV.map(({ to, icon, label }) => (
            <NavLink key={to} to={to} end={to === '/'}
              style={({ isActive }) => ({
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '9px 12px', borderRadius: 'var(--radius-sm)',
                marginBottom: 2, textDecoration: 'none',
                fontSize: 14, fontWeight: 500,
                color: isActive ? '#fff' : 'var(--text2)',
                background: isActive ? 'var(--bg3)' : 'transparent',
                borderLeft: isActive ? '2px solid var(--blue)' : '2px solid transparent',
                transition: 'all .15s',
              })}>
              <span style={{ fontSize: 15 }}>{icon}</span>
              <span className="nav-label">{label}</span>

              {label === 'Incidents' && active > 0 && (
                <span style={{
                  marginLeft: 'auto', background: 'var(--red-dim)', color: 'var(--red)',
                  borderRadius: 10, padding: '1px 7px', fontSize: 11, fontWeight: 700,
                }}>{active}</span>
              )}

              {label === 'Approvals' && pendingApprovals > 0 && (
                <span style={{
                  marginLeft: 'auto', background: 'rgba(240,136,62,.2)', color: '#f0883e',
                  borderRadius: 10, padding: '1px 7px', fontSize: 11, fontWeight: 700,
                }}>{pendingApprovals}</span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* AI Engine status */}
        <div style={{
          padding: '12px 16px',
          borderTop: '1px solid var(--border)',
          fontSize: 12,
        }}>
          <div style={{ color: 'var(--text3)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 8 }}>AI Engine</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
            <span className={`pulse ${ollama ? 'pulse-green' : 'pulse-red'}`} />
            <span style={{ color: 'var(--text2)' }}>Ollama</span>
            <span style={{ marginLeft: 'auto', color: ollama ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
              {ollama ? 'ONLINE' : 'OFFLINE'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className={`pulse ${claude ? 'pulse-purple' : 'pulse-gray'}`}
                  style={{ background: claude ? 'var(--purple)' : 'var(--text3)' }} />
            <span style={{ color: 'var(--text2)' }}>Claude</span>
            <span style={{ marginLeft: 'auto', color: claude ? 'var(--purple)' : 'var(--text3)', fontWeight: 600 }}>
              {claude ? 'BACKUP' : 'OFF'}
            </span>
          </div>
        </div>

        {/* User / Logout */}
        {authEnabled && user && (
          <div style={{
            padding: '10px 16px',
            borderTop: '1px solid var(--border)',
            display: 'flex', alignItems: 'center', gap: 8,
            fontSize: 12,
          }}>
            <div style={{
              width: 26, height: 26, borderRadius: '50%',
              background: 'linear-gradient(135deg, #1f6feb, #bc8cff)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 11, fontWeight: 700, flexShrink: 0,
            }}>
              {user.username?.[0]?.toUpperCase()}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: 'var(--text)', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {user.full_name || user.username}
              </div>
              <div style={{ color: 'var(--text3)', fontSize: 10, textTransform: 'uppercase' }}>{user.role}</div>
            </div>
            <button onClick={doLogout} title="Logout"
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--text3)', fontSize: 16, padding: 4,
                borderRadius: 4, transition: 'color .15s',
              }}
              onMouseEnter={e => e.target.style.color = 'var(--red)'}
              onMouseLeave={e => e.target.style.color = 'var(--text3)'}
            >⏻</button>
          </div>
        )}
      </aside>

      {/* ── Main content ──────────────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <Outlet />
      </div>
    </div>
  )
}
