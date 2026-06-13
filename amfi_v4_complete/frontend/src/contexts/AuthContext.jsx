import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { api } from '../api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user,        setUser]        = useState(null)      // { username, role, full_name }
  const [token,       setToken]       = useState(() => localStorage.getItem('amfi_token') || null)
  const [authEnabled, setAuthEnabled] = useState(false)
  const [loading,     setLoading]     = useState(true)

  // On mount: check if auth is enabled + validate stored token
  useEffect(() => {
    const init = async () => {
      try {
        const status = await api.authStatus()
        setAuthEnabled(status.auth_enabled)
        if (status.auth_enabled && token) {
          try {
            const me = await api.me()
            setUser(me)
          } catch {
            // Token invalid/expired — clear it
            localStorage.removeItem('amfi_token')
            setToken(null)
          }
        }
      } catch {
        // Server unreachable — proceed unauthenticated
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [])   // run once on mount; token changes handled below

  const login = useCallback(async (username, password) => {
    const data = await api.login(username, password)
    localStorage.setItem('amfi_token', data.access_token)
    setToken(data.access_token)
    setUser({ username: data.username, role: data.role, full_name: data.full_name })
    return data
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('amfi_token')
    setToken(null)
    setUser(null)
  }, [])

  const isAuthenticated = !authEnabled || !!user

  return (
    <AuthContext.Provider value={{ user, token, authEnabled, loading, login, logout, isAuthenticated }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
