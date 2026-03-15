import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Incidents from './pages/Incidents'
import Events from './pages/Events'
import Remediation from './pages/Remediation'
import CMDB from './pages/CMDB'
import Pipeline from './pages/Pipeline'
import Login from './pages/Login'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Layout><Dashboard /></Layout>} />
        <Route path="/incidents" element={<Layout><Incidents /></Layout>} />
        <Route path="/events" element={<Layout><Events /></Layout>} />
        <Route path="/remediation" element={<Layout><Remediation /></Layout>} />
        <Route path="/cmdb" element={<Layout><CMDB /></Layout>} />
        <Route path="/pipeline" element={<Layout><Pipeline /></Layout>} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
