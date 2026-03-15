import { useEffect, useState, useCallback } from 'react'
import { api } from '../api/client'
import { Plus, RefreshCw, Trash2, CheckCircle, XCircle, Play, ChevronDown, ChevronRight } from 'lucide-react'

// ─── Shared helpers ───────────────────────────────────────────────────────────

function Wrap({ children }: { children: React.ReactNode }) {
  return <div style={{ padding: '32px 36px', maxWidth: 1300 }}>{children}</div>
}
function PageHeader({ title, subtitle, children }: any) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
      <div><div className="page-title">{title}</div><div className="page-subtitle">{subtitle}</div></div>
      <div style={{ display: 'flex', gap: 8 }}>{children}</div>
    </div>
  )
}
function Badge({ value }: { value: string }) {
  const cls = value?.toLowerCase().replace(/[\s/]/g, '_')
  return <span className={`badge badge-${cls}`}>{value}</span>
}
function Empty({ msg }: { msg: string }) {
  return <div style={{ padding: 48, textAlign: 'center', color: 'var(--text2)' }}>{msg}</div>
}
function fmtDate(d: string | null) {
  return d ? new Date(d).toLocaleString() : '—'
}

// ─── DASHBOARD ────────────────────────────────────────────────────────────────

export function Dashboard() {
  const [data, setData] = useState<any>(null)
  useEffect(() => {
    api.dashboard().then(setData)
    const t = setInterval(() => api.dashboard().then(setData), 15000)
    return () => clearInterval(t)
  }, [])

  const { incidents = {}, events = {}, remediation = {}, targets = {}, recent_incidents = [] } = data || {}

  return (
    <Wrap>
      <div style={{ marginBottom: 28 }}>
        <div className="page-title">Operations Dashboard</div>
        <div className="page-subtitle">Live platform health — refreshes every 15s</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14, marginBottom: 24 }}>
        {[
          { label: 'Open Incidents',  value: incidents.open ?? 0,     color: 'var(--critical)', cls: 'critical' },
          { label: 'Resolved Today',  value: incidents.resolved_today ?? 0, color: 'var(--accent)', cls: 'accent' },
          { label: 'SLA Breached',    value: incidents.sla_breached ?? 0,   color: 'var(--warn)',   cls: 'warn'   },
          { label: 'Events Today',    value: events.today ?? 0,       color: '#4d94ff',          cls: 'blue'   },
        ].map(({ label, value, color, cls }) => (
          <div key={label} className={`stat-card ${cls}`}>
            <div className="stat-label">{label}</div>
            <div className="stat-value" style={{ color }}>{value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 24 }}>
        <div className="card">
          <div className="stat-label" style={{ marginBottom: 14 }}>SLA Targets</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {Object.entries(targets).map(([k, v]) => (
              <div key={k} style={{ background: 'var(--bg)', borderRadius: 4, padding: '10px 12px' }}>
                <div style={{ fontSize: 11, color: 'var(--text2)', textTransform: 'uppercase', fontFamily: 'var(--mono)', marginBottom: 4 }}>{k.replace(/_/g, ' ')}</div>
                <div style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--accent)' }}>{String(v)}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="stat-label" style={{ marginBottom: 14 }}>Remediation</div>
          <div style={{ display: 'flex', gap: 14 }}>
            <div style={{ flex: 1, background: 'var(--bg)', borderRadius: 4, padding: '14px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 6, fontFamily: 'var(--mono)', textTransform: 'uppercase' }}>Pending Approval</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 28, fontWeight: 700, color: 'var(--warn)' }}>{remediation.pending_approval ?? 0}</div>
            </div>
            <div style={{ flex: 1, background: 'var(--bg)', borderRadius: 4, padding: '14px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 6, fontFamily: 'var(--mono)', textTransform: 'uppercase' }}>Auto Success</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 28, fontWeight: 700, color: 'var(--accent)' }}>{remediation.auto_success_rate ?? 0}%</div>
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', fontFamily: 'var(--mono)', fontSize: 12, textTransform: 'uppercase', color: 'var(--text2)', letterSpacing: '.08em' }}>Recent Incidents</div>
        <table className="table">
          <thead><tr><th>#</th><th>Title</th><th>Priority</th><th>Status</th><th>Team</th><th>Created</th></tr></thead>
          <tbody>
            {recent_incidents.map((i: any) => (
              <tr key={i.id}>
                <td className="mono" style={{ color: 'var(--text2)', fontSize: 12 }}>#{i.id}</td>
                <td>{i.title}</td>
                <td><Badge value={i.priority} /></td>
                <td><Badge value={i.status} /></td>
                <td style={{ color: 'var(--text2)' }}>{i.assigned_team || '—'}</td>
                <td style={{ color: 'var(--text2)', fontSize: 12 }}>{fmtDate(i.created_at)}</td>
              </tr>
            ))}
            {!recent_incidents.length && <tr><td colSpan={6}><Empty msg="No incidents yet" /></td></tr>}
          </tbody>
        </table>
      </div>
    </Wrap>
  )
}

// ─── INCIDENTS ────────────────────────────────────────────────────────────────

export function Incidents() {
  const [incidents, setIncidents] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [filters, setFilters] = useState({ status: '', priority: '' })

  const load = useCallback(() => {
    setLoading(true)
    const p: any = {}
    if (filters.status)   p.status   = filters.status
    if (filters.priority) p.priority = filters.priority
    api.incidents(p).then(setIncidents).finally(() => setLoading(false))
  }, [filters])

  useEffect(() => { load() }, [load])

  const del = async (id: number) => {
    if (!confirm('Delete this incident?')) return
    await api.deleteIncident(id); load()
  }
  const changeStatus = async (id: number, status: string) => {
    await api.updateIncident(id, { status }); load()
  }

  return (
    <Wrap>
      <PageHeader title="Incident Management" subtitle="ITIL-aligned incident tracking and resolution">
        <button className="btn btn-sm" onClick={load}><RefreshCw size={13} /> Refresh</button>
        <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}><Plus size={13} /> New Incident</button>
      </PageHeader>

      <div style={{ display: 'flex', gap: 10, marginBottom: 18 }}>
        {[
          { key: 'status',   opts: ['','new','assigned','in_progress','pending','resolved','closed'],    label: 'All Statuses'   },
          { key: 'priority', opts: ['','critical','high','medium','low'],                               label: 'All Priorities' },
        ].map(({ key, opts, label }) => (
          <select key={key} value={(filters as any)[key]}
            onChange={e => setFilters(f => ({ ...f, [key]: e.target.value }))}
            style={{ width: 160 }}>
            {opts.map(o => <option key={o} value={o}>{o || label}</option>)}
          </select>
        ))}
      </div>

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Empty msg="Loading..." /> : incidents.length === 0 ? <Empty msg="No incidents found." /> : (
          <table className="table">
            <thead><tr><th>#</th><th>Title</th><th>Priority</th><th>Status</th><th>Team</th><th>SLA</th><th>Auto?</th><th></th></tr></thead>
            <tbody>
              {incidents.map((inc: any) => (
                <tr key={inc.id} style={{ opacity: inc.sla_breached ? 1 : 1 }}>
                  <td className="mono" style={{ fontSize: 12, color: 'var(--text2)' }}>#{inc.id}</td>
                  <td style={{ maxWidth: 260 }}>
                    <div style={{ fontWeight: 500 }}>{inc.title}</div>
                    {inc.sla_breached && <span style={{ fontSize: 11, color: 'var(--critical)', fontFamily: 'var(--mono)' }}>⚠ SLA BREACHED</span>}
                  </td>
                  <td><Badge value={inc.priority} /></td>
                  <td>
                    <select value={inc.status} onChange={e => changeStatus(inc.id, e.target.value)}
                      style={{ width: 'auto', fontSize: 12, padding: '4px 8px' }}>
                      {['new','assigned','in_progress','pending','resolved','closed'].map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--text2)' }}>{inc.assigned_team || '—'}</td>
                  <td style={{ fontSize: 11, color: inc.sla_breached ? 'var(--critical)' : 'var(--text2)', fontFamily: 'var(--mono)' }}>
                    {inc.sla_deadline ? new Date(inc.sla_deadline).toLocaleString() : '—'}
                  </td>
                  <td style={{ fontSize: 12 }}>
                    {inc.auto_remediate ? <span style={{ color: 'var(--accent)' }}>✓ Auto</span> : <span style={{ color: 'var(--text2)' }}>Manual</span>}
                    {inc.requires_approval && <span style={{ color: 'var(--warn)', marginLeft: 6 }}>⚠ Approval</span>}
                  </td>
                  <td>
                    <button className="btn btn-danger btn-sm" onClick={() => del(inc.id)}><Trash2 size={12} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {showCreate && <CreateIncidentModal onClose={() => { setShowCreate(false); load() }} />}
    </Wrap>
  )
}

function CreateIncidentModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ title: '', description: '', priority: 'medium', source: 'manual', assigned_team: '' })
  const [saving, setSaving] = useState(false)
  const submit = async () => {
    if (!form.title) return
    setSaving(true)
    await api.createIncident(form).finally(() => setSaving(false))
    onClose()
  }
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Create Incident</div>
        <div className="form-group"><label className="form-label">Title *</label><input value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} placeholder="Describe the issue" /></div>
        <div className="form-group"><label className="form-label">Description</label><textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={3} /></div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="form-group"><label className="form-label">Priority</label>
            <select value={form.priority} onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}>
              {['critical','high','medium','low'].map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="form-group"><label className="form-label">Team</label><input value={form.assigned_team} onChange={e => setForm(f => ({ ...f, assigned_team: e.target.value }))} placeholder="server-ops" /></div>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
          <button className="btn btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary btn-sm" onClick={submit} disabled={saving}>{saving ? 'Creating...' : 'Create'}</button>
        </div>
      </div>
    </div>
  )
}

// ─── EVENTS ───────────────────────────────────────────────────────────────────

export function Events() {
  const [events, setEvents] = useState<any[]>([])
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [showIngest, setShowIngest] = useState(false)

  const load = () => {
    setLoading(true)
    Promise.all([api.rawEvents(), api.ingestStats()]).then(([evts, s]) => {
      setEvents(evts); setStats(s)
    }).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const sevColor: Record<string, string> = {
    critical: 'var(--critical)', major: 'var(--warn)', warning: '#ffd600', info: 'var(--accent)', unknown: 'var(--text2)',
  }

  return (
    <Wrap>
      <PageHeader title="Event Stream" subtitle="All ingested events from all sources">
        <button className="btn btn-sm" onClick={load}><RefreshCw size={13} /> Refresh</button>
        <button className="btn btn-primary btn-sm" onClick={() => setShowIngest(true)}><Plus size={13} /> Ingest Event</button>
      </PageHeader>

      {stats && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
          {Object.entries(stats.by_status || {}).map(([s, c]) => (
            <div key={s} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, padding: '8px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text2)', fontFamily: 'var(--mono)', textTransform: 'uppercase' }}>{s}</div>
              <div style={{ fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 18 }}>{String(c)}</div>
            </div>
          ))}
        </div>
      )}

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Empty msg="Loading..." /> : events.length === 0 ? <Empty msg="No events yet. Use 'Ingest Event' to test." /> : (
          <table className="table">
            <thead><tr><th>#</th><th>Source</th><th>Sev</th><th>Title</th><th>Host</th><th>Status</th><th>Received</th></tr></thead>
            <tbody>
              {events.map((ev: any) => (
                <tr key={ev.id}>
                  <td className="mono" style={{ fontSize: 12, color: 'var(--text2)' }}>#{ev.id}</td>
                  <td><span style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 3, padding: '2px 7px' }}>{ev.source}</span></td>
                  <td><span style={{ color: sevColor[ev.severity] || 'var(--text2)', fontFamily: 'var(--mono)', fontSize: 12, fontWeight: 700 }}>{ev.severity?.toUpperCase()}</span></td>
                  <td style={{ maxWidth: 300, fontSize: 13 }}>{ev.title}</td>
                  <td style={{ fontSize: 12, color: 'var(--text2)' }}>{ev.affected_host || '—'}</td>
                  <td><Badge value={ev.status} /></td>
                  <td style={{ fontSize: 12, color: 'var(--text2)', fontFamily: 'var(--mono)' }}>{fmtDate(ev.received_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {showIngest && <IngestEventModal onClose={() => { setShowIngest(false); load() }} />}
    </Wrap>
  )
}

function IngestEventModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ title: '', message: '', severity: 'warning', affected_host: '', affected_service: '' })
  const [saving, setSaving] = useState(false)
  const submit = async () => {
    if (!form.title) return
    setSaving(true)
    await api.ingestManual(form).finally(() => setSaving(false))
    onClose()
  }
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Ingest Manual Event</div>
        <div className="form-group"><label className="form-label">Title *</label><input value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} placeholder="e.g. High CPU on server01" /></div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="form-group"><label className="form-label">Severity</label>
            <select value={form.severity} onChange={e => setForm(f => ({ ...f, severity: e.target.value }))}>
              {['critical','major','minor','warning','info'].map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="form-group"><label className="form-label">Affected Host</label><input value={form.affected_host} onChange={e => setForm(f => ({ ...f, affected_host: e.target.value }))} placeholder="server01:9100" /></div>
        </div>
        <div className="form-group"><label className="form-label">Message</label><textarea value={form.message} onChange={e => setForm(f => ({ ...f, message: e.target.value }))} rows={3} /></div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
          <button className="btn btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary btn-sm" onClick={submit} disabled={saving}>{saving ? 'Ingesting...' : 'Ingest'}</button>
        </div>
      </div>
    </div>
  )
}

// ─── REMEDIATION ──────────────────────────────────────────────────────────────

export function Remediation() {
  const [jobs, setJobs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')

  const load = () => {
    setLoading(true)
    const p: any = {}
    if (filter) p.status = filter
    api.remediationJobs(p).then(setJobs).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [filter])

  const approve = async (id: number) => {
    const by = prompt('Approved by (your name):')
    if (!by) return
    await api.approveJob(id, by); load()
  }
  const reject = async (id: number) => {
    const reason = prompt('Rejection reason:')
    if (!reason) return
    await api.rejectJob(id, 'operator', reason); load()
  }
  const execute = async (id: number) => {
    await api.executeJob(id); load()
  }

  return (
    <Wrap>
      <PageHeader title="Remediation Jobs" subtitle="Auto-remediation execution, approval gates, and polling">
        <button className="btn btn-sm" onClick={load}><RefreshCw size={13} /> Refresh</button>
      </PageHeader>

      <select value={filter} onChange={e => setFilter(e.target.value)} style={{ width: 200, marginBottom: 18 }}>
        {['','pending','awaiting_approval','running','verifying','success','failed','rolled_back'].map(s => (
          <option key={s} value={s}>{s || 'All Statuses'}</option>
        ))}
      </select>

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Empty msg="Loading..." /> : jobs.length === 0 ? <Empty msg="No remediation jobs yet." /> : (
          <table className="table">
            <thead><tr><th>#</th><th>Incident</th><th>Action</th><th>Type</th><th>Target</th><th>Status</th><th>Attempts</th><th>Actions</th></tr></thead>
            <tbody>
              {jobs.map((j: any) => (
                <tr key={j.id}>
                  <td className="mono" style={{ fontSize: 12, color: 'var(--text2)' }}>#{j.id}</td>
                  <td className="mono" style={{ fontSize: 12 }}>INC-{j.incident_id}</td>
                  <td style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{j.action}</td>
                  <td><span style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 3, padding: '2px 7px' }}>{j.remediation_type}</span></td>
                  <td style={{ fontSize: 12, color: 'var(--text2)' }}>{j.target_host || '—'}</td>
                  <td><Badge value={j.status} /></td>
                  <td style={{ fontSize: 12 }}>{j.attempt_number}/{j.max_attempts || 3}</td>
                  <td>
                    <div style={{ display: 'flex', gap: 4 }}>
                      {j.status === 'awaiting_approval' && <>
                        <button className="btn btn-sm" style={{ color: 'var(--accent)', borderColor: 'rgba(0,229,160,.3)' }} onClick={() => approve(j.id)}><CheckCircle size={12} /> Approve</button>
                        <button className="btn btn-danger btn-sm" onClick={() => reject(j.id)}><XCircle size={12} /> Reject</button>
                      </>}
                      {j.status === 'pending' && (
                        <button className="btn btn-sm" onClick={() => execute(j.id)}><Play size={12} /> Run</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Wrap>
  )
}

// ─── CMDB ─────────────────────────────────────────────────────────────────────

export function CMDB() {
  const [cis, setCIs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)

  const load = () => {
    setLoading(true)
    api.cmdb().then(setCIs).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const del = async (ciId: string) => {
    if (!confirm('Delete this CI?')) return
    await api.deleteCI(ciId); load()
  }

  const critColor: Record<string, string> = {
    critical: 'var(--critical)', high: 'var(--warn)', medium: '#ffd600', low: 'var(--accent)',
  }

  return (
    <Wrap>
      <PageHeader title="CMDB" subtitle="Configuration items — servers, switches, services">
        <button className="btn btn-sm" onClick={load}><RefreshCw size={13} /> Refresh</button>
        <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}><Plus size={13} /> Add CI</button>
      </PageHeader>

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Empty msg="Loading..." /> : cis.length === 0 ? <Empty msg="No CIs. Add your servers to enable enrichment and SSH remediation." /> : (
          <table className="table">
            <thead><tr><th>CI ID</th><th>Hostname</th><th>IP</th><th>Type</th><th>Env</th><th>Criticality</th><th>Service</th><th>Team</th><th>SSH</th><th></th></tr></thead>
            <tbody>
              {cis.map((ci: any) => (
                <tr key={ci.ci_id}>
                  <td className="mono" style={{ fontSize: 12 }}>{ci.ci_id}</td>
                  <td style={{ fontWeight: 500 }}>{ci.hostname}</td>
                  <td className="mono" style={{ fontSize: 12, color: 'var(--text2)' }}>{ci.ip_address || '—'}</td>
                  <td style={{ fontSize: 12 }}>{ci.ci_type}</td>
                  <td><span style={{ fontFamily: 'var(--mono)', fontSize: 11, padding: '2px 6px', borderRadius: 3, background: ci.environment === 'prod' ? 'rgba(255,45,85,.1)' : 'rgba(0,229,160,.08)', color: ci.environment === 'prod' ? 'var(--critical)' : 'var(--accent)' }}>{ci.environment}</span></td>
                  <td><span style={{ color: critColor[ci.criticality] || 'var(--text2)', fontFamily: 'var(--mono)', fontSize: 12, fontWeight: 700 }}>{ci.criticality?.toUpperCase()}</span></td>
                  <td style={{ fontSize: 12, color: 'var(--text2)' }}>{ci.business_service || '—'}</td>
                  <td style={{ fontSize: 12, color: 'var(--text2)' }}>{ci.team || '—'}</td>
                  <td style={{ fontSize: 12 }}>{ci.ssh_user ? <span style={{ color: 'var(--accent)' }}>✓ {ci.ssh_user}</span> : <span style={{ color: 'var(--text2)' }}>—</span>}</td>
                  <td><button className="btn btn-danger btn-sm" onClick={() => del(ci.ci_id)}><Trash2 size={12} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {showCreate && <CreateCIModal onClose={() => { setShowCreate(false); load() }} />}
    </Wrap>
  )
}

function CreateCIModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({
    ci_id: '', hostname: '', ip_address: '', ci_type: 'server',
    environment: 'prod', criticality: 'medium', business_service: '',
    owner: '', team: '', ssh_user: '', ssh_key_path: '',
  })
  const [saving, setSaving] = useState(false)
  const submit = async () => {
    if (!form.ci_id || !form.hostname) return
    setSaving(true)
    await api.createCI(form).finally(() => setSaving(false))
    onClose()
  }
  const f = (key: string, val: string) => setForm(p => ({ ...p, [key]: val }))
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Add Configuration Item</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="form-group"><label className="form-label">CI ID *</label><input value={form.ci_id} onChange={e => f('ci_id', e.target.value)} placeholder="SERVER-001" /></div>
          <div className="form-group"><label className="form-label">Hostname *</label><input value={form.hostname} onChange={e => f('hostname', e.target.value)} placeholder="server01.example.com" /></div>
          <div className="form-group"><label className="form-label">IP Address</label><input value={form.ip_address} onChange={e => f('ip_address', e.target.value)} placeholder="10.0.0.10" /></div>
          <div className="form-group"><label className="form-label">Type</label>
            <select value={form.ci_type} onChange={e => f('ci_type', e.target.value)}>
              {['server','vm','switch','firewall','loadbalancer','storage','container'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="form-group"><label className="form-label">Environment</label>
            <select value={form.environment} onChange={e => f('environment', e.target.value)}>
              {['prod','staging','dev','test'].map(e => <option key={e} value={e}>{e}</option>)}
            </select>
          </div>
          <div className="form-group"><label className="form-label">Criticality</label>
            <select value={form.criticality} onChange={e => f('criticality', e.target.value)}>
              {['critical','high','medium','low'].map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="form-group"><label className="form-label">Business Service</label><input value={form.business_service} onChange={e => f('business_service', e.target.value)} placeholder="e-commerce, payments" /></div>
          <div className="form-group"><label className="form-label">Team</label><input value={form.team} onChange={e => f('team', e.target.value)} placeholder="server-ops" /></div>
          <div className="form-group"><label className="form-label">SSH User</label><input value={form.ssh_user} onChange={e => f('ssh_user', e.target.value)} placeholder="ubuntu" /></div>
          <div className="form-group"><label className="form-label">SSH Key Path</label><input value={form.ssh_key_path} onChange={e => f('ssh_key_path', e.target.value)} placeholder="/keys/server01.pem" /></div>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
          <button className="btn btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary btn-sm" onClick={submit} disabled={saving}>{saving ? 'Saving...' : 'Add CI'}</button>
        </div>
      </div>
    </div>
  )
}

// ─── PIPELINE VIEW ────────────────────────────────────────────────────────────

export function Pipeline() {
  const steps = [
    { n: '01', label: 'Event Ingestion',             detail: 'SNMP · Syslog · Alertmanager · Webhook', color: '#4d94ff' },
    { n: '02', label: 'Event Enrichment',             detail: 'CMDB lookup · Service map · Blast radius', color: '#a070ff' },
    { n: '03', label: 'Correlation & Dedup',          detail: 'Root cause · Suppress symptoms · Grouping', color: '#00e5a0' },
    { n: '04', label: 'Decision Engine',              detail: 'Path A: Ticket · B: Remediate · C: Notify · D: Escalate', color: '#ffd600' },
    { n: '05', label: 'Diagnostics L1/L2',            detail: 'Ping · SSH · Disk · Memory · CPU · Logs', color: '#ff9060' },
    { n: '06', label: 'Remediation Execution',        detail: 'Ansible · Python/SSH · Terraform · Manual', color: '#ff6b35' },
    { n: '07', label: 'Verification & Continuous Poll', detail: 'Health check · Retry · Rollback · SLA clock', color: '#ff2d55' },
    { n: '08', label: 'Feedback & Learning',          detail: 'MTTR · Success rate · Correlation refinement', color: '#00e5a0' },
  ]
  return (
    <Wrap>
      <div style={{ marginBottom: 28 }}>
        <div className="page-title">Automation Pipeline</div>
        <div className="page-subtitle">End-to-end flow: NMS Alert → Incident Resolved & Learned</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 13, background: 'rgba(0,229,160,.1)', border: '1px solid var(--accent)', borderRadius: 20, padding: '6px 20px', color: 'var(--accent)' }}>START — NMS Alert Triggered</span>
        </div>
        {steps.map((s, i) => (
          <div key={s.n}>
            <div style={{ display: 'flex', gap: 0 }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 40 }}>
                <div style={{ width: 2, height: i === 0 ? 16 : 24, background: 'var(--border)' }} />
                <div style={{ width: 36, height: 36, borderRadius: '50%', background: s.color, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--mono)', fontSize: 12, fontWeight: 700, color: '#000', flexShrink: 0 }}>{s.n}</div>
                {i < steps.length - 1 && <div style={{ width: 2, flex: 1, background: 'var(--border)', minHeight: 24 }} />}
              </div>
              <div style={{ paddingLeft: 16, paddingBottom: 24, paddingTop: 8, flex: 1 }}>
                <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, padding: '14px 18px', borderLeft: `3px solid ${s.color}` }}>
                  <div style={{ fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 14, marginBottom: 4 }}>{s.label}</div>
                  <div style={{ fontSize: 13, color: 'var(--text2)' }}>{s.detail}</div>
                </div>
              </div>
            </div>
          </div>
        ))}
        <div style={{ textAlign: 'center', marginTop: 8 }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 13, background: 'rgba(0,229,160,.1)', border: '1px solid var(--accent)', borderRadius: 20, padding: '6px 20px', color: 'var(--accent)' }}>END — Incident Resolved & Learned</span>
        </div>
      </div>
    </Wrap>
  )
}

// ─── LOGIN ────────────────────────────────────────────────────────────────────

export function Login() {
  const [form, setForm] = useState({ username: 'admin', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async () => {
    setError(''); setLoading(true)
    try {
      const data = await api.login(form.username, form.password)
      localStorage.setItem('amfi_token', data.access_token)
      window.location.href = '/'
    } catch (e: any) {
      setError(e.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
      <div style={{ width: 360 }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ width: 52, height: 52, borderRadius: 12, background: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px', fontSize: 24 }}>⚡</div>
          <div style={{ fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 22 }}>AMFI</div>
          <div style={{ color: 'var(--text2)', fontSize: 13, marginTop: 4 }}>IT Service Automation Platform</div>
        </div>
        <div className="card">
          <div className="form-group"><label className="form-label">Username</label><input value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))} autoFocus /></div>
          <div className="form-group"><label className="form-label">Password</label><input type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} onKeyDown={e => e.key === 'Enter' && submit()} /></div>
          {error && <div style={{ color: 'var(--critical)', fontSize: 13, marginBottom: 14 }}>{error}</div>}
          <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }} onClick={submit} disabled={loading}>
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
          <div style={{ marginTop: 14, fontSize: 12, color: 'var(--text2)', textAlign: 'center' }}>Default: admin / admin123</div>
        </div>
      </div>
    </div>
  )
}
