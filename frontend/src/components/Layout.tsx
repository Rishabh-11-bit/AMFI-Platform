import { NavLink } from 'react-router-dom'
import { LayoutDashboard, AlertCircle, Zap, Wrench, Database, GitBranch, Activity, LogOut } from 'lucide-react'

const nav = [
  { to: '/',           icon: LayoutDashboard, label: 'Dashboard'   },
  { to: '/incidents',  icon: AlertCircle,     label: 'Incidents'   },
  { to: '/events',     icon: Zap,             label: 'Event Stream'},
  { to: '/remediation',icon: Wrench,          label: 'Remediation' },
  { to: '/cmdb',       icon: Database,        label: 'CMDB'        },
  { to: '/pipeline',   icon: GitBranch,       label: 'Pipeline'    },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const handleLogout = () => { localStorage.removeItem('amfi_token'); window.location.href = '/login' }
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <aside style={{ width: 220, flexShrink: 0, background: 'var(--bg2)', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', position: 'sticky', top: 0, height: '100vh' }}>
        <div style={{ padding: '20px 20px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 32, height: 32, borderRadius: 6, background: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Activity size={16} color="#000" strokeWidth={2.5} />
            </div>
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 13 }}>AMFI</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', letterSpacing: '.06em', textTransform: 'uppercase' }}>IT Automation</div>
            </div>
          </div>
        </div>
        <nav style={{ flex: 1, padding: '12px 10px' }}>
          {nav.map(({ to, icon: Icon, label }) => (
            <NavLink key={to} to={to} end={to === '/'} style={({ isActive }) => ({
              display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px',
              borderRadius: 5, marginBottom: 2,
              color: isActive ? 'var(--accent)' : 'var(--text2)',
              background: isActive ? 'rgba(0,229,160,.08)' : 'transparent',
              fontSize: 13, fontWeight: isActive ? 500 : 400, transition: 'all .12s',
              borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
            })}>
              <Icon size={15} />{label}
            </NavLink>
          ))}
        </nav>
        <div style={{ padding: '14px 16px', borderTop: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text2)' }}>
              <span className="dot dot-green pulse" />System Online
            </div>
            <button onClick={handleLogout} style={{ background: 'none', border: 'none', color: 'var(--text2)', cursor: 'pointer', padding: 4 }} title="Logout">
              <LogOut size={14} />
            </button>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4, fontFamily: 'var(--mono)' }}>v1.0.0</div>
        </div>
      </aside>
      <main style={{ flex: 1, overflow: 'auto' }}>{children}</main>
    </div>
  )
}
