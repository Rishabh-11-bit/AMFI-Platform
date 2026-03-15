const BASE = '/api';

async function req(path: string, opts?: RequestInit) {
  const token = localStorage.getItem('amfi_token');
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...opts?.headers,
    },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  // Auth
  login: (username: string, password: string) =>
    req('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),

  // Dashboard
  dashboard: () => req('/dashboard'),

  // Ingest
  ingestManual: (data: object) => req('/ingest/manual', { method: 'POST', body: JSON.stringify(data) }),
  ingestAlertmanager: (data: object) => req('/ingest/alertmanager', { method: 'POST', body: JSON.stringify(data) }),
  rawEvents: (params?: Record<string, string>) =>
    req('/ingest/events' + (params ? '?' + new URLSearchParams(params) : '')),
  ingestStats: () => req('/ingest/stats'),

  // Incidents
  incidents: (params?: Record<string, string>) =>
    req('/incidents' + (params ? '?' + new URLSearchParams(params) : '')),
  incidentStats: () => req('/incidents/stats'),
  getIncident: (id: number) => req(`/incidents/${id}`),
  createIncident: (data: object) => req('/incidents', { method: 'POST', body: JSON.stringify(data) }),
  updateIncident: (id: number, data: object) =>
    req(`/incidents/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteIncident: (id: number) => req(`/incidents/${id}`, { method: 'DELETE' }),
  incidentDiagnostics: (id: number) => req(`/incidents/${id}/diagnostics`),
  incidentRemediation: (id: number) => req(`/incidents/${id}/remediation`),

  // Remediation
  remediationJobs: (params?: Record<string, string>) =>
    req('/remediation' + (params ? '?' + new URLSearchParams(params) : '')),
  createJob: (data: object) => req('/remediation', { method: 'POST', body: JSON.stringify(data) }),
  approveJob: (id: number, approved_by: string) =>
    req(`/remediation/${id}/approve`, { method: 'POST', body: JSON.stringify({ approved_by }) }),
  rejectJob: (id: number, rejected_by: string, reason: string) =>
    req(`/remediation/${id}/reject`, { method: 'POST', body: JSON.stringify({ rejected_by, reason }) }),
  executeJob: (id: number) => req(`/remediation/${id}/execute`, { method: 'POST' }),

  // CMDB
  cmdb: (params?: Record<string, string>) =>
    req('/cmdb' + (params ? '?' + new URLSearchParams(params) : '')),
  createCI: (data: object) => req('/cmdb', { method: 'POST', body: JSON.stringify(data) }),
  updateCI: (ciId: string, data: object) =>
    req(`/cmdb/${ciId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteCI: (ciId: string) => req(`/cmdb/${ciId}`, { method: 'DELETE' }),

  // Health
  health: () => req('/health'),
};
