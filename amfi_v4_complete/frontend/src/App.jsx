import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect }   from 'react'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import ErrorBoundary from './components/ErrorBoundary'
import Layout     from './components/Layout'
import Dashboard  from './pages/Dashboard'
import Incidents  from './pages/Incidents'
import Hosts      from './pages/Hosts'
import Alerts     from './pages/Alerts'
import Approvals  from './pages/Approvals'
import Users      from './pages/Users'
import Login      from './pages/Login'

// Guard: if auth is enabled and user is not logged in → redirect to /login
function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth()
  if (loading) return null   // wait for token check
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return children
}

// Redirect logged-in users away from /login
function PublicOnlyRoute({ children }) {
  const { isAuthenticated, loading } = useAuth()
  if (loading) return null
  if (isAuthenticated) return <Navigate to="/" replace />
  return children
}

// Handle token expiry from any page
function AuthExpiredListener() {
  const { logout } = useAuth()
  useEffect(() => {
    const handler = () => logout()
    window.addEventListener('amfi:auth-expired', handler)
    return () => window.removeEventListener('amfi:auth-expired', handler)
  }, [logout])
  return null
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <BrowserRouter>
          <AuthExpiredListener />
          <Routes>
            {/* Public: login */}
            <Route path="/login" element={
              <PublicOnlyRoute><Login /></PublicOnlyRoute>
            } />

            {/* Protected: main layout */}
            <Route path="/" element={
              <ProtectedRoute><Layout /></ProtectedRoute>
            }>
              <Route index              element={<Dashboard />}  />
              <Route path="incidents"   element={<Incidents />}  />
              <Route path="hosts"       element={<Hosts />}      />
              <Route path="alerts"      element={<Alerts />}     />
              <Route path="approvals"   element={<Approvals />}  />
              <Route path="users"       element={<Users />}      />
              <Route path="*"           element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ErrorBoundary>
  )
}
