import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function Login() {
  const { login }           = useAuth()
  const navigate             = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (!username || !password) { setError('Enter username and password'); return }
    setLoading(true); setError('')
    try {
      await login(username, password)
      navigate('/')
    } catch (err) {
      setError(err.message?.includes('401') ? 'Invalid username or password' : (err.message || 'Login failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg)', padding: 24,
    }}>
      <div style={{
        width: '100%', maxWidth: 380,
        background: 'var(--bg2)', borderRadius: 'var(--radius)',
        border: '1px solid var(--border)', padding: '36px 32px',
        boxShadow: '0 20px 60px rgba(0,0,0,.5)',
      }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{
            width: 52, height: 52, borderRadius: 14, margin: '0 auto 12px',
            background: 'linear-gradient(135deg, #1f6feb 0%, #bc8cff 100%)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 24,
          }}>⬡</div>
          <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: '.02em' }}>AMFI NOC</div>
          <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 4, letterSpacing: '.06em', textTransform: 'uppercase' }}>
            Autonomous Incident Management
          </div>
        </div>

        <form onSubmit={submit}>
          <div className="form-row">
            <label>Username</label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="admin"
              autoFocus
              autoComplete="username"
              disabled={loading}
            />
          </div>

          <div className="form-row">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              disabled={loading}
            />
          </div>

          {error && (
            <div style={{
              background: 'var(--red-dim)', border: '1px solid var(--red)',
              borderRadius: 'var(--radius-sm)', padding: '8px 12px',
              fontSize: 13, color: 'var(--red)', marginBottom: 16,
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn-primary"
            disabled={loading}
            style={{ width: '100%', justifyContent: 'center', padding: '11px 0', fontSize: 15 }}
          >
            {loading ? 'Signing in…' : 'Sign In'}
          </button>
        </form>

        <div style={{
          marginTop: 24, padding: '10px 14px',
          background: 'var(--bg3)', borderRadius: 'var(--radius-sm)',
          fontSize: 12, color: 'var(--text3)',
        }}>
          Default credentials: <span style={{ color: 'var(--text2)' }}>admin</span> /
          <span style={{ color: 'var(--text2)' }}> amfi2024!</span>
        </div>
      </div>
    </div>
  )
}
