import { useEffect, useState } from 'react'
import { api } from '../api'

const ROLES = ['viewer', 'operator', 'admin']

export default function Users() {
  const [users,   setUsers]   = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')
  const [showNew, setShowNew] = useState(false)
  const [form,    setForm]    = useState({ username: '', password: '', email: '', full_name: '', role: 'viewer' })
  const [formErr, setFormErr] = useState('')
  const [saving,  setSaving]  = useState(false)

  // Password change state
  const [changePwd,    setChangePwd]    = useState(null) // userId being changed
  const [pwdCurrent,   setPwdCurrent]   = useState('')
  const [pwdNew,       setPwdNew]       = useState('')
  const [pwdErr,       setPwdErr]       = useState('')
  const [pwdSaving,    setPwdSaving]    = useState(false)

  const load = () => {
    setLoading(true)
    api.get('/users')
      .then(r => r.json())
      .then(d => { setUsers(d); setError('') })
      .catch(() => setError('Failed to load users'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const handleCreate = async e => {
    e.preventDefault()
    setFormErr('')
    if (!form.username.trim()) { setFormErr('Username is required'); return }
    if (form.password.length < 8) { setFormErr('Password must be at least 8 characters'); return }
    setSaving(true)
    try {
      const r = await api.post('/users', form)
      if (!r.ok) {
        const d = await r.json()
        setFormErr(d.detail || 'Error creating user')
      } else {
        setShowNew(false)
        setForm({ username: '', password: '', email: '', full_name: '', role: 'viewer' })
        load()
      }
    } catch { setFormErr('Network error') }
    finally  { setSaving(false) }
  }

  const handleToggleActive = async (u) => {
    await api.patch(`/users/${u.id}`, { is_active: !u.is_active })
    load()
  }

  const handleRoleChange = async (u, role) => {
    await api.patch(`/users/${u.id}`, { role })
    load()
  }

  const handleDelete = async (u) => {
    if (!window.confirm(`Delete user "${u.username}"? This cannot be undone.`)) return
    await api.delete(`/users/${u.id}`)
    load()
  }

  const handleChangePwd = async e => {
    e.preventDefault()
    setPwdErr('')
    if (pwdNew.length < 8) { setPwdErr('New password must be at least 8 characters'); return }
    setPwdSaving(true)
    try {
      const r = await api.post('/auth/change-password', {
        current_password: pwdCurrent,
        new_password:     pwdNew,
      })
      if (!r.ok) {
        const d = await r.json()
        setPwdErr(d.detail || 'Error changing password')
      } else {
        setChangePwd(null)
        setPwdCurrent('')
        setPwdNew('')
      }
    } catch { setPwdErr('Network error') }
    finally  { setPwdSaving(false) }
  }

  const roleBadge = role => {
    const colors = { admin: '#f85149', operator: '#e3b341', viewer: '#3fb950' }
    return (
      <span style={{
        background:   colors[role] + '22',
        color:        colors[role] || '#8b949e',
        border:       `1px solid ${colors[role] || '#30363d'}`,
        borderRadius: '12px',
        padding:      '2px 8px',
        fontSize:     '0.7rem',
        fontWeight:   700,
        textTransform:'uppercase',
      }}>{role}</span>
    )
  }

  return (
    <div style={{ padding: '1.5rem', maxWidth: '900px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <h1 style={{ margin: 0, fontSize: '1.4rem' }}>User Management</h1>
        <button
          onClick={() => setShowNew(v => !v)}
          style={{
            background: '#238636', color: '#fff', border: 'none',
            borderRadius: '6px', padding: '0.5rem 1rem', cursor: 'pointer', fontFamily: 'monospace',
          }}
        >
          {showNew ? '✕ Cancel' : '＋ New User'}
        </button>
      </div>

      {/* Create user form */}
      {showNew && (
        <form onSubmit={handleCreate} style={{
          background: '#161b22', border: '1px solid #30363d', borderRadius: '8px',
          padding: '1.25rem', marginBottom: '1.5rem',
        }}>
          <h3 style={{ margin: '0 0 1rem', fontSize: '0.95rem', color: '#8b949e' }}>Create New User</h3>
          {formErr && <div style={{ color: '#f85149', marginBottom: '0.75rem', fontSize: '0.85rem' }}>{formErr}</div>}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            {[
              ['Username *', 'username', 'text', true],
              ['Password * (min 8)', 'password', 'password', true],
              ['Email', 'email', 'email', false],
              ['Full Name', 'full_name', 'text', false],
            ].map(([label, key, type]) => (
              <label key={key} style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', fontSize: '0.8rem', color: '#8b949e' }}>
                {label}
                <input
                  type={type}
                  value={form[key]}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                  style={{
                    background: '#0d1117', border: '1px solid #30363d', borderRadius: '4px',
                    padding: '0.4rem 0.6rem', color: '#e6edf3', fontFamily: 'monospace', fontSize: '0.85rem',
                  }}
                />
              </label>
            ))}
            <label style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', fontSize: '0.8rem', color: '#8b949e' }}>
              Role
              <select
                value={form.role}
                onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
                style={{
                  background: '#0d1117', border: '1px solid #30363d', borderRadius: '4px',
                  padding: '0.4rem 0.6rem', color: '#e6edf3', fontFamily: 'monospace', fontSize: '0.85rem',
                }}
              >
                {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
          </div>
          <button
            type="submit" disabled={saving}
            style={{
              marginTop: '1rem', background: '#238636', color: '#fff', border: 'none',
              borderRadius: '6px', padding: '0.5rem 1.25rem', cursor: 'pointer', fontFamily: 'monospace',
            }}
          >
            {saving ? 'Creating…' : 'Create User'}
          </button>
        </form>
      )}

      {/* Password change modal */}
      {changePwd && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <form onSubmit={handleChangePwd} style={{
            background: '#161b22', border: '1px solid #30363d', borderRadius: '8px',
            padding: '1.5rem', width: '360px',
          }}>
            <h3 style={{ margin: '0 0 1rem' }}>Change Password</h3>
            {pwdErr && <div style={{ color: '#f85149', marginBottom: '0.75rem', fontSize: '0.85rem' }}>{pwdErr}</div>}
            {[
              ['Current password', pwdCurrent, setPwdCurrent],
              ['New password (min 8)', pwdNew, setPwdNew],
            ].map(([label, val, setter]) => (
              <label key={label} style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', fontSize: '0.8rem', color: '#8b949e', marginBottom: '0.75rem' }}>
                {label}
                <input
                  type="password" value={val}
                  onChange={e => setter(e.target.value)}
                  style={{
                    background: '#0d1117', border: '1px solid #30363d', borderRadius: '4px',
                    padding: '0.4rem 0.6rem', color: '#e6edf3', fontFamily: 'monospace', fontSize: '0.85rem',
                  }}
                />
              </label>
            ))}
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
              <button
                type="submit" disabled={pwdSaving}
                style={{
                  background: '#238636', color: '#fff', border: 'none',
                  borderRadius: '6px', padding: '0.5rem 1rem', cursor: 'pointer', fontFamily: 'monospace',
                }}
              >
                {pwdSaving ? 'Saving…' : 'Change'}
              </button>
              <button
                type="button" onClick={() => { setChangePwd(null); setPwdCurrent(''); setPwdNew(''); setPwdErr('') }}
                style={{
                  background: 'transparent', color: '#8b949e', border: '1px solid #30363d',
                  borderRadius: '6px', padding: '0.5rem 1rem', cursor: 'pointer', fontFamily: 'monospace',
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* User list */}
      {loading ? (
        <div style={{ color: '#8b949e', textAlign: 'center', padding: '2rem' }}>Loading users…</div>
      ) : error ? (
        <div style={{ color: '#f85149', padding: '1rem' }}>{error}</div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #30363d', color: '#8b949e' }}>
              {['Username', 'Full Name', 'Email', 'Role', 'Status', 'Actions'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 600 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} style={{ borderBottom: '1px solid #21262d' }}>
                <td style={{ padding: '0.6rem 0.75rem', fontWeight: 600, color: '#e6edf3' }}>{u.username}</td>
                <td style={{ padding: '0.6rem 0.75rem', color: '#8b949e' }}>{u.full_name || '—'}</td>
                <td style={{ padding: '0.6rem 0.75rem', color: '#8b949e' }}>{u.email || '—'}</td>
                <td style={{ padding: '0.6rem 0.75rem' }}>
                  <select
                    value={u.role}
                    onChange={e => handleRoleChange(u, e.target.value)}
                    style={{
                      background: '#0d1117', border: '1px solid #30363d', borderRadius: '4px',
                      padding: '0.2rem 0.4rem', color: '#e6edf3', fontFamily: 'monospace', fontSize: '0.8rem',
                    }}
                  >
                    {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
                <td style={{ padding: '0.6rem 0.75rem' }}>
                  <button
                    onClick={() => handleToggleActive(u)}
                    style={{
                      background: u.is_active ? '#3fb95022' : '#f8514922',
                      color:      u.is_active ? '#3fb950'   : '#f85149',
                      border:     `1px solid ${u.is_active ? '#3fb950' : '#f85149'}`,
                      borderRadius: '12px', padding: '2px 8px', cursor: 'pointer',
                      fontSize: '0.75rem', fontFamily: 'monospace',
                    }}
                  >
                    {u.is_active ? 'Active' : 'Disabled'}
                  </button>
                </td>
                <td style={{ padding: '0.6rem 0.75rem' }}>
                  <div style={{ display: 'flex', gap: '0.4rem' }}>
                    <button
                      onClick={() => { setChangePwd(u.id); setPwdCurrent(''); setPwdNew(''); setPwdErr('') }}
                      title="Change password"
                      style={{
                        background: 'transparent', color: '#8b949e', border: '1px solid #30363d',
                        borderRadius: '4px', padding: '0.25rem 0.5rem', cursor: 'pointer',
                        fontSize: '0.8rem', fontFamily: 'monospace',
                      }}
                    >
                      🔑
                    </button>
                    {u.username !== 'admin' && (
                      <button
                        onClick={() => handleDelete(u)}
                        title="Delete user"
                        style={{
                          background: 'transparent', color: '#f85149', border: '1px solid #f8514944',
                          borderRadius: '4px', padding: '0.25rem 0.5rem', cursor: 'pointer',
                          fontSize: '0.8rem', fontFamily: 'monospace',
                        }}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
