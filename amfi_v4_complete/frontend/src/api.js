const BASE = '/api'

function getToken() {
  return localStorage.getItem('amfi_token')
}

// ── Low-level fetch helpers ────────────────────────────────────────────────────
// These return the raw Response so callers can inspect r.ok / r.status.
// Used by pages that need fine-grained error handling (Users, etc.)

async function rawFetch(method, path, body) {
  const opts = { method, headers: {} }

  const token = getToken()
  if (token) opts.headers['Authorization'] = `Bearer ${token}`

  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }

  const r = await fetch(BASE + path, opts)

  if (r.status === 401) {
    localStorage.removeItem('amfi_token')
    window.dispatchEvent(new CustomEvent('amfi:auth-expired'))
  }

  return r  // raw response — caller checks r.ok
}

// ── JSON-throwing helper ───────────────────────────────────────────────────────
// Used by all legacy api.* calls — throws on non-OK status.

async function req(method, path, body) {
  const r = await rawFetch(method, path, body)
  if (!r.ok) {
    const text = await r.text().catch(() => r.statusText)
    throw new Error(`${method} ${path} → ${r.status}: ${text}`)
  }
  if (r.status === 204) return null
  return r.json()
}

export const api = {
  // ── Low-level methods (return raw Response) ─────────────────────────────────
  get:    (path)        => rawFetch('GET',    path),
  post:   (path, body)  => rawFetch('POST',   path, body),
  patch:  (path, body)  => rawFetch('PATCH',  path, body),
  put:    (path, body)  => rawFetch('PUT',    path, body),
  delete: (path)        => rawFetch('DELETE', path),

  // ── Core ─────────────────────────────────────────────────────────────────────
  health:    ()       => req('GET',  '/health'),
  dashboard: ()       => req('GET',  '/dashboard'),

  // ── Auth ─────────────────────────────────────────────────────────────────────
  authStatus: ()                    => req('GET',  '/auth/status'),
  login:      (username, password)  => {
    // OAuth2PasswordRequestForm expects form-encoded body
    const body = new URLSearchParams({ username, password })
    const token = getToken()
    const headers = { 'Content-Type': 'application/x-www-form-urlencoded' }
    if (token) headers['Authorization'] = `Bearer ${token}`
    return fetch(BASE + '/auth/login', { method: 'POST', headers, body })
      .then(async r => {
        if (!r.ok) throw new Error(`401`)
        return r.json()
      })
  },
  me: () => req('GET', '/auth/me'),

  // ── Incidents ─────────────────────────────────────────────────────────────────
  incidents: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
    ).toString()
    return req('GET', `/incidents${qs ? '?' + qs : ''}`)
  },
  incident:      (id)    => req('GET',  `/incidents/${id}`),
  incidentSteps: (id)    => req('GET',  `/incidents/${id}/steps`),
  createIncident:(body)  => req('POST', '/incidents', body),
  runAgent:      (id)    => req('POST', `/incidents/${id}/run`),

  // ── Monitored Hosts ───────────────────────────────────────────────────────────
  monitoredHosts:      (params) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return req('GET', `/monitored-hosts${qs}`)
  },
  createMonitoredHost: (body)   => req('POST',   '/monitored-hosts', body),
  updateMonitoredHost: (id, b)  => req('PUT',    `/monitored-hosts/${id}`, b),
  deleteMonitoredHost: (id)     => req('DELETE', `/monitored-hosts/${id}`),
  pollHost:            (id)     => req('POST',   `/monitored-hosts/${id}/poll`),
  hostMetrics:         (id, p)  => {
    const qs = new URLSearchParams(
      Object.entries(p || {}).filter(([, v]) => v !== undefined)
    ).toString()
    return req('GET', `/monitored-hosts/${id}/metrics${qs ? '?' + qs : ''}`)
  },
  metricsSummary: () => req('GET', '/metrics/summary'),

  // ── Threshold Rules ───────────────────────────────────────────────────────────
  thresholdRules:      ()      => req('GET',    '/threshold-rules'),
  createThresholdRule: (body)  => req('POST',   '/threshold-rules', body),
  updateThresholdRule: (id, b) => req('PUT',    `/threshold-rules/${id}`, b),
  deleteThresholdRule: (id)    => req('DELETE', `/threshold-rules/${id}`),

  // ── Approvals ─────────────────────────────────────────────────────────────────
  approvals: (status) => req('GET', `/approvals${status ? '?status=' + status : ''}`),
  approve:   (token, note)  => req('POST', `/approvals/${token}/approve`,
                                   note ? { note } : {}),
  reject:    (token, note)  => req('POST', `/approvals/${token}/reject`,
                                   note ? { note } : {}),

  // ── Users ────────────────────────────────────────────────────────────────────
  users:       ()         => req('GET',    '/users'),
  createUser:  (body)     => req('POST',   '/users', body),
  updateUser:  (id, body) => req('PATCH',  `/users/${id}`, body),
  deleteUser:  (id)       => req('DELETE', `/users/${id}`),

  // ── Audit Log ─────────────────────────────────────────────────────────────────
  auditLog: (params) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return req('GET', `/audit-log${qs}`)
  },

  // ── Training data ─────────────────────────────────────────────────────────────
  trainingStats:    ()  => req('GET',  '/training/stats'),
  generateSynthetic:(n) => req('POST', '/training/generate', { count: n ?? 10 }),
}
