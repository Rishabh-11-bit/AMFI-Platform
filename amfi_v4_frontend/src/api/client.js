const BASE = '/api'

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const api = {
  health:    () => req('/health'),
  dashboard: () => req('/dashboard'),
  incidents: {
    list:   (params = '') => req(`/incidents${params}`),
    get:    (id) => req(`/incidents/${id}`),
    steps:  (id) => req(`/incidents/${id}/steps`),
    create: (data) => req('/incidents', { method: 'POST', body: JSON.stringify(data) }),
    run:    (id) => req(`/incidents/${id}/run`, { method: 'POST' }),
  },
  approvals: {
    list:    (status = 'pending') => req(`/approvals?status=${status}`),
    approve: (token, note = '') => req(`/approvals/${token}/approve?note=${encodeURIComponent(note)}`, { method: 'POST' }),
    reject:  (token, reason = 'Rejected') => req(`/approvals/${token}/reject?reason=${encodeURIComponent(reason)}`, { method: 'POST' }),
  },
  hosts: {
    list:   () => req('/hosts'),
    create: (data) => req('/hosts', { method: 'POST', body: JSON.stringify(data) }),
    delete: (id) => req(`/hosts/${id}`, { method: 'DELETE' }),
  },
  nms: {
    list:   () => req('/nms'),
    create: (data) => req('/nms', { method: 'POST', body: JSON.stringify(data) }),
  },
  resolutions: () => req('/resolutions'),
  webhook: {
    alertmanager: (payload) => req('/webhook/alertmanager', { method: 'POST', body: JSON.stringify(payload) }),
  },
}
