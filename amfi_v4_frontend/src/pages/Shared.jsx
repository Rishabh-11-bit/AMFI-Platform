// ── APPROVALS ──────────────────────────────────────────────────────────────────
import { useEffect, useState } from 'react'
import { CheckCircle, XCircle, RefreshCw, Clock, Plus, Trash2, Wifi } from 'lucide-react'
import { api } from '../api/client'

export function Approvals() {
  const [approvals, setApprovals] = useState([])
  const [filter,    setFilter]    = useState('pending')
  const [loading,   setLoading]   = useState(true)
  const [acting,    setActing]    = useState(null)

  const load = async () => {
    setLoading(true)
    try { setApprovals(await api.approvals.list(filter)) } catch {}
    setLoading(false)
  }

  useEffect(() => { load() }, [filter])
  useEffect(() => { const t = setInterval(load, 6000); return () => clearInterval(t) }, [filter])

  const approve = async (token) => {
    setActing(token)
    try { await api.approvals.approve(token); await load() } catch (e) { alert(e.message) }
    setActing(null)
  }

  const reject = async (token) => {
    const reason = prompt('Rejection reason (optional):') ?? 'Rejected'
    setActing(token)
    try { await api.approvals.reject(token, reason); await load() } catch (e) { alert(e.message) }
    setActing(null)
  }

  const minsLeft = (a) => {
    if (!a.expires_at) return null
    const m = Math.floor((new Date(a.expires_at).getTime() - Date.now()) / 60000)
    return m > 0 ? m : null
  }

  return (
    <div className="page">
      <div className="ph">
        <div>
          <div className="ph-title">Approval Inbox</div>
          <div className="ph-sub">Agent requests approval before risky actions</div>
        </div>
        <div className="ph-actions">
          <select style={{ padding:'7px 12px', width:150 }} value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="all">All</option>
          </select>
          <button className="btn btn-secondary btn-sm" onClick={load}><RefreshCw size={13}/></button>
        </div>
      </div>

      {loading ? <div className="loading"><div className="spinner"/>Loading…</div>
      : approvals.length === 0 ? (
        <div className="empty" style={{ marginTop:60 }}>
          <CheckCircle size={48}/>
          <p style={{ marginTop:12 }}>No {filter} approvals</p>
          <p style={{ fontSize:12, marginTop:4 }}>
            {filter === 'pending' ? 'The agent will ask here before taking risky actions' : 'Nothing here'}
          </p>
        </div>
      ) : approvals.map(a => (
        <div key={a.id} className="appr-card">
          <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', gap:12 }}>
            <div style={{ flex:1 }}>
              <div className="appr-title">
                {a.action}
                {a.risk_level && (
                  <span className={`badge ${a.risk_level === 'high' ? 'p1' : a.risk_level === 'medium' ? 'p2' : 'p4'}`} style={{ marginLeft:8, fontSize:10 }}>
                    {a.risk_level} risk
                  </span>
                )}
              </div>
              <div className="appr-meta">
                <span><strong>Incident:</strong> #{a.incident_id}</span>
                <span><strong>Host:</strong> {a.host || '—'}</span>
                <span><strong>Status:</strong> {a.status}</span>
                {a.status === 'pending' && minsLeft(a) && (
                  <span style={{ color:'var(--p3)' }}>
                    <Clock size={11} style={{ verticalAlign:'middle', marginRight:3 }}/>
                    Expires in {minsLeft(a)}m
                  </span>
                )}
              </div>
            </div>
            {a.status === 'pending' && (
              <div style={{ display:'flex', gap:8, flexShrink:0 }}>
                <button className="btn btn-danger btn-sm" onClick={() => reject(a.token)} disabled={acting === a.token}>
                  <XCircle size={13}/> Reject
                </button>
                <button className="btn btn-primary btn-sm" onClick={() => approve(a.token)} disabled={acting === a.token}>
                  {acting === a.token ? <div className="spinner" style={{width:12,height:12}}/> : <CheckCircle size={13}/>}
                  Approve
                </button>
              </div>
            )}
            {a.status === 'approved' && <span style={{ color:'var(--p4)', fontSize:13 }}>✓ Approved</span>}
            {a.status === 'rejected' && <span style={{ color:'var(--p1)', fontSize:13 }}>✗ Rejected</span>}
          </div>

          <div className="appr-section">
            <div className="appr-lbl">Why the agent wants to do this</div>
            <div className="appr-val">{a.reason}</div>
          </div>

          {a.rollback && (
            <div className="appr-section">
              <div className="appr-lbl">Rollback plan if it fails</div>
              <div className="appr-val">{a.rollback}</div>
            </div>
          )}

          {a.incident_summary && (
            <div className="appr-section">
              <div className="appr-lbl">Incident context</div>
              <div className="appr-val" style={{ fontFamily:'var(--mono)', fontSize:12, whiteSpace:'pre-wrap' }}>{a.incident_summary}</div>
            </div>
          )}

          {a.decision_note && (
            <div className="appr-section">
              <div className="appr-lbl">Decision note</div>
              <div className="appr-val">{a.decision_note}</div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── HOSTS (CMDB) ───────────────────────────────────────────────────────────────

export function Hosts() {
  const [hosts,   setHosts]   = useState([])
  const [loading, setLoading] = useState(true)
  const [modal,   setModal]   = useState(false)
  const [form,    setForm]    = useState({
    hostname:'', ip_address:'', os:'', environment:'prod', criticality:'medium',
    business_service:'', owner_email:'', ssh_user:'', ssh_port:22,
    auto_remediate:true, known_issues:''
  })

  const load = async () => {
    setLoading(true)
    try { setHosts(await api.hosts.list()) } catch {}
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const create = async () => {
    try { await api.hosts.create(form); setModal(false); await load() } catch (e) { alert(e.message) }
  }

  const del = async (id, name) => {
    if (!confirm(`Delete host ${name}?`)) return
    try { await api.hosts.delete(id); await load() } catch (e) { alert(e.message) }
  }

  const critColor = { critical:'var(--p1)', high:'var(--p2)', medium:'var(--p3)', low:'var(--p4)' }

  return (
    <div className="page">
      <div className="ph">
        <div>
          <div className="ph-title">Hosts (CMDB)</div>
          <div className="ph-sub">{hosts.length} hosts — add SSH credentials to enable diagnostics and remediation</div>
        </div>
        <div className="ph-actions">
          <button className="btn btn-secondary btn-sm" onClick={load}><RefreshCw size={13}/></button>
          <button className="btn btn-primary" onClick={() => setModal(true)}><Plus size={14}/> Add Host</button>
        </div>
      </div>

      <div className="card" style={{ padding:0 }}>
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr><th>Hostname</th><th>IP</th><th>OS</th><th>Env</th><th>Criticality</th><th>Service</th><th>SSH</th><th>Auto-remediate</th><th></th></tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9}><div className="loading"><div className="spinner"/>Loading…</div></td></tr>
              ) : hosts.length === 0 ? (
                <tr><td colSpan={9}>
                  <div className="empty">
                    <p>No hosts yet</p>
                    <p style={{ fontSize:12, marginTop:4 }}>Add your servers with SSH credentials to enable remote diagnostics and automated fixes</p>
                  </div>
                </td></tr>
              ) : hosts.map(h => (
                <tr key={h.id} style={{ cursor:'default' }}>
                  <td className="pri"><span style={{ fontFamily:'var(--mono)', fontSize:12 }}>{h.hostname}</span></td>
                  <td><span style={{ fontFamily:'var(--mono)', fontSize:12 }}>{h.ip_address || '—'}</span></td>
                  <td style={{ fontSize:12 }}>{h.os || '—'}</td>
                  <td style={{ fontSize:12 }}>{h.environment}</td>
                  <td><span style={{ fontSize:12, fontWeight:600, color:critColor[h.criticality] }}>{h.criticality?.toUpperCase()}</span></td>
                  <td style={{ fontSize:12 }}>{h.business_service || '—'}</td>
                  <td>
                    {h.ssh_available
                      ? <span style={{ color:'var(--accent)', fontSize:11 }}>✓ {h.ssh_user}</span>
                      : <span style={{ color:'var(--txt3)', fontSize:11 }}>—</span>}
                  </td>
                  <td>
                    {h.auto_remediate
                      ? <span style={{ color:'var(--p4)', fontSize:11 }}>✓ Enabled</span>
                      : <span style={{ color:'var(--p1)', fontSize:11 }}>✗ Manual only</span>}
                  </td>
                  <td>
                    <button className="btn btn-danger btn-sm" style={{ padding:'3px 8px' }} onClick={() => del(h.id, h.hostname)}>
                      <Trash2 size={12}/>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {modal && (
        <div className="overlay" onClick={e => e.target === e.currentTarget && setModal(false)}>
          <div className="modal">
            <div className="modal-title">Add Host</div>
            <div className="f2">
              <div className="fg"><label className="fl">Hostname *</label>
                <input placeholder="web-server-01" value={form.hostname} onChange={e => setForm({...form,hostname:e.target.value})} />
              </div>
              <div className="fg"><label className="fl">IP Address</label>
                <input placeholder="10.0.1.10" value={form.ip_address} onChange={e => setForm({...form,ip_address:e.target.value})} />
              </div>
            </div>
            <div className="f2">
              <div className="fg"><label className="fl">Criticality</label>
                <select value={form.criticality} onChange={e => setForm({...form,criticality:e.target.value})}>
                  {['critical','high','medium','low'].map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="fg"><label className="fl">Environment</label>
                <select value={form.environment} onChange={e => setForm({...form,environment:e.target.value})}>
                  {['prod','staging','dev','test'].map(e => <option key={e} value={e}>{e}</option>)}
                </select>
              </div>
            </div>
            <div className="f2">
              <div className="fg"><label className="fl">SSH User</label>
                <input placeholder="ubuntu" value={form.ssh_user} onChange={e => setForm({...form,ssh_user:e.target.value})} />
              </div>
              <div className="fg"><label className="fl">SSH Port</label>
                <input type="number" value={form.ssh_port} onChange={e => setForm({...form,ssh_port:+e.target.value})} />
              </div>
            </div>
            <div className="fg"><label className="fl">OS</label>
              <input placeholder="Ubuntu 22.04" value={form.os} onChange={e => setForm({...form,os:e.target.value})} />
            </div>
            <div className="fg"><label className="fl">Business Service</label>
              <input placeholder="Payment Gateway, Auth Service…" value={form.business_service} onChange={e => setForm({...form,business_service:e.target.value})} />
            </div>
            <div className="fg"><label className="fl">Owner Email</label>
              <input type="email" value={form.owner_email} onChange={e => setForm({...form,owner_email:e.target.value})} />
            </div>
            <div className="fg"><label className="fl">Known Issues / Notes</label>
              <textarea placeholder="e.g. Disk fills every 2-3 weeks on /var/log, safe to auto-clean" value={form.known_issues} onChange={e => setForm({...form,known_issues:e.target.value})} />
            </div>
            <div className="fg">
              <label style={{ display:'flex', alignItems:'center', gap:8, cursor:'pointer' }}>
                <input type="checkbox" style={{ width:'auto' }} checked={form.auto_remediate} onChange={e => setForm({...form,auto_remediate:e.target.checked})} />
                <span style={{ fontSize:13, color:'var(--txt2)' }}>Enable auto-remediation (agent can act on this host)</span>
              </label>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setModal(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={create} disabled={!form.hostname}>Add Host</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── NMS SOURCES ────────────────────────────────────────────────────────────────

export function NMSSources() {
  const [sources, setSources] = useState([])
  const [modal,   setModal]   = useState(false)
  const [form,    setForm]    = useState({ name:'', nms_type:'prometheus', base_url:'', username:'', password:'', api_token:'', poll_interval:300 })

  const load = async () => { try { setSources(await api.nms.list()) } catch {} }
  useEffect(() => { load() }, [])

  const create = async () => {
    try { await api.nms.create(form); setModal(false); await load() } catch (e) { alert(e.message) }
  }

  const typeColor = { prometheus:'var(--p2)', zabbix:'var(--accent2)', solarwinds:'var(--accent)', prtg:'var(--p3)' }

  return (
    <div className="page">
      <div className="ph">
        <div>
          <div className="ph-title">NMS Sources</div>
          <div className="ph-sub">Connected monitoring tools — alerts flow into the agent automatically</div>
        </div>
        <button className="btn btn-primary" onClick={() => setModal(true)}><Plus size={14}/> Add Source</button>
      </div>

      {/* Webhook info */}
      <div className="card" style={{ marginBottom:18, borderLeft:'3px solid var(--accent2)' }}>
        <div className="card-title">Prometheus / Alertmanager Webhook</div>
        <div style={{ fontSize:13, color:'var(--txt2)', marginBottom:8 }}>
          Add to your <span style={{ fontFamily:'var(--mono)', background:'var(--hover)', padding:'1px 6px', borderRadius:4 }}>alertmanager.yml</span>:
        </div>
        <div style={{ background:'var(--bg)', border:'1px solid var(--border)', borderRadius:8, padding:'10px 14px', fontFamily:'var(--mono)', fontSize:12, color:'var(--accent)' }}>
          {`receivers:\n  - name: amfi\n    webhook_configs:\n      - url: http://YOUR-SERVER:8000/api/webhook/alertmanager`}
        </div>
      </div>

      {sources.length === 0 ? (
        <div className="empty" style={{ marginTop:40 }}>
          <Wifi size={48}/>
          <p style={{ marginTop:12 }}>No NMS sources connected</p>
          <p style={{ fontSize:12, marginTop:4 }}>Add Prometheus, Zabbix, SolarWinds, or PRTG</p>
          <button className="btn btn-primary" style={{ marginTop:16 }} onClick={() => setModal(true)}><Plus size={14}/> Add First Source</button>
        </div>
      ) : (
        <div className="g2">
          {sources.map(s => (
            <div key={s.id} className="card" style={{ borderLeft:`3px solid ${typeColor[s.nms_type] || 'var(--border)'}` }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start' }}>
                <div>
                  <div style={{ fontSize:15, fontWeight:600, marginBottom:4 }}>{s.name}</div>
                  <div style={{ display:'flex', gap:8, alignItems:'center' }}>
                    <span style={{ fontSize:11, fontWeight:700, color:typeColor[s.nms_type], textTransform:'uppercase', letterSpacing:'.8px' }}>{s.nms_type}</span>
                    <div className={`dot ${s.status === 'active' ? 'on' : 'off'}`}/>
                    <span style={{ fontSize:11, color:'var(--txt3)' }}>{s.status}</span>
                  </div>
                </div>
                <div style={{ textAlign:'right' }}>
                  <div style={{ fontSize:10, color:'var(--txt3)' }}>Enabled</div>
                  <div style={{ fontSize:13, color: s.enabled ? 'var(--accent)' : 'var(--p1)' }}>{s.enabled ? 'Yes' : 'No'}</div>
                </div>
              </div>
              <div style={{ marginTop:12, fontSize:12, color:'var(--txt3)' }}>
                {s.base_url && <div>URL: <span style={{ color:'var(--txt2)', fontFamily:'var(--mono)' }}>{s.base_url}</span></div>}
                <div>Last polled: {s.last_polled_at ? String(s.last_polled_at).slice(0,16).replace('T',' ') : 'Never'}</div>
                {s.last_error && <div style={{ color:'var(--p1)', marginTop:4 }}>Error: {s.last_error.slice(0,80)}</div>}
              </div>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <div className="overlay" onClick={e => e.target === e.currentTarget && setModal(false)}>
          <div className="modal">
            <div className="modal-title">Add NMS Source</div>
            <div className="f2">
              <div className="fg"><label className="fl">Name *</label>
                <input placeholder="Production Prometheus" value={form.name} onChange={e => setForm({...form,name:e.target.value})} />
              </div>
              <div className="fg"><label className="fl">Type *</label>
                <select value={form.nms_type} onChange={e => setForm({...form,nms_type:e.target.value})}>
                  <option value="prometheus">Prometheus / Alertmanager</option>
                  <option value="zabbix">Zabbix</option>
                  <option value="solarwinds">SolarWinds</option>
                  <option value="prtg">PRTG</option>
                </select>
              </div>
            </div>
            <div className="fg"><label className="fl">Base URL</label>
              <input placeholder="http://prometheus:9093" value={form.base_url} onChange={e => setForm({...form,base_url:e.target.value})} />
            </div>
            <div className="f2">
              <div className="fg"><label className="fl">Username</label>
                <input value={form.username} onChange={e => setForm({...form,username:e.target.value})} />
              </div>
              <div className="fg"><label className="fl">Password</label>
                <input type="password" value={form.password} onChange={e => setForm({...form,password:e.target.value})} />
              </div>
            </div>
            <div className="fg"><label className="fl">API Token</label>
              <input placeholder="Bearer token or API key" value={form.api_token} onChange={e => setForm({...form,api_token:e.target.value})} />
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setModal(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={create} disabled={!form.name}>Add Source</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── ANALYTICS ──────────────────────────────────────────────────────────────────

export function Analytics() {
  const [stats,     setStats]     = useState(null)
  const [incidents, setIncidents] = useState([])
  const [resolutions, setRes]     = useState([])
  const [loading,   setLoading]   = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        const [s, i, r] = await Promise.all([
          api.dashboard(), api.incidents.list('?limit=500'), api.resolutions()
        ])
        setStats(s); setIncidents(i); setRes(r)
      } catch {}
      setLoading(false)
    }
    load()
  }, [])

  if (loading) return <div className="loading"><div className="spinner"/>Loading…</div>

  const s = stats?.incidents || {}
  const byP = incidents.reduce((a,i) => { a[i.priority||'unknown']=(a[i.priority||'unknown']||0)+1; return a }, {})
  const byC = incidents.reduce((a,i) => { a[i.fault_category||'unknown']=(a[i.fault_category||'unknown']||0)+1; return a }, {})
  const byStatus = incidents.reduce((a,i) => { a[i.status]=(a[i.status]||0)+1; return a }, {})
  const total = incidents.length || 1
  const resolved = incidents.filter(i => i.status === 'resolved')
  const avgAttempts = resolved.length ? (resolved.reduce((a,i) => a+(i.attempt_count||0),0)/resolved.length).toFixed(1) : 0

  const pColors = { p1:'var(--p1)', p2:'var(--p2)', p3:'var(--p3)', p4:'var(--p4)', unknown:'var(--txt3)' }
  const sColors = { resolved:'var(--accent)', l1_running:'var(--accent2)', l2_running:'var(--p3)', l3_escalated:'var(--p2)', new:'var(--p4)', false_positive:'var(--txt3)' }

  function Bar({ label, value, color }) {
    const pct = Math.round((value / total) * 100)
    return (
      <div className="bar-row">
        <div className="bar-hd">
          <span className="bar-lbl">{label.replace(/_/g,' ')}</span>
          <span className="bar-val">{value} ({pct}%)</span>
        </div>
        <div className="bar-track"><div className="bar-fill" style={{ width:`${pct}%`, background:color }} /></div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="ph"><div><div className="ph-title">Analytics</div><div className="ph-sub">Agent performance and incident trends</div></div></div>

      <div className="stats" style={{ marginBottom:22 }}>
        <div className="stat green"><div className="stat-val">{s.auto_resolution_rate||'0%'}</div><div className="stat-lbl">Auto-resolved</div></div>
        <div className="stat blue"> <div className="stat-val">{avgAttempts}</div><div className="stat-lbl">Avg attempts</div></div>
        <div className="stat red">  <div className="stat-val">{s.sla_breached??0}</div><div className="stat-lbl">SLA Breaches</div></div>
        <div className="stat orange"><div className="stat-val">{s.false_positives??0}</div><div className="stat-lbl">False Positives</div></div>
        <div className="stat green"><div className="stat-val">{s.resolved??0}</div><div className="stat-lbl">Resolved</div></div>
        <div className="stat purple"><div className="stat-val">{resolutions.length}</div><div className="stat-lbl">Agent Memory</div></div>
      </div>

      <div className="g3" style={{ marginBottom:18 }}>
        <div className="card">
          <div className="card-title">By Priority</div>
          {Object.entries(byP).sort(([a],[b])=>a>b?1:-1).map(([p,v]) =>
            <Bar key={p} label={p.toUpperCase()} value={v} color={pColors[p]||'var(--txt3)'} />
          )}
        </div>
        <div className="card">
          <div className="card-title">By Fault Category</div>
          {Object.entries(byC).sort(([,a],[,b])=>b-a).map(([c,v]) =>
            <Bar key={c} label={c} value={v} color={'var(--accent2)'} />
          )}
        </div>
        <div className="card">
          <div className="card-title">By Status</div>
          {Object.entries(byStatus).sort(([,a],[,b])=>b-a).map(([st,v]) =>
            <Bar key={st} label={st} value={v} color={sColors[st]||'var(--txt3)'} />
          )}
        </div>
      </div>

      {/* ROI */}
      <div className="card">
        <div className="card-title">ROI Estimator</div>
        <div style={{ fontSize:12, color:'var(--txt3)', marginBottom:14 }}>Based on {s.resolved??0} auto-resolved incidents</div>
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))', gap:12 }}>
          {[
            { lbl:'Engineer hours saved', val:`~${Math.round((s.resolved??0)*0.75)}h`,      sub:'at 45 min avg per L1/L2' },
            { lbl:'Cost saved (est.)',    val:`₹${Math.round((s.resolved??0)*0.75*500).toLocaleString()}`, sub:'at ₹500/hr engineer cost' },
            { lbl:'SLA compliance',      val: total > 1 ? `${Math.round(((total-(s.sla_breached??0))/total)*100)}%` : '—', sub:'incidents within SLA' },
            { lbl:'Agent memory',        val:`${resolutions.length} records`, sub:'past resolutions stored' },
          ].map(m => (
            <div key={m.lbl} style={{ padding:'14px', background:'var(--hover)', borderRadius:8 }}>
              <div style={{ fontSize:22, fontWeight:700, fontFamily:'var(--mono)', color:'var(--accent)' }}>{m.val}</div>
              <div style={{ fontSize:13, fontWeight:600, color:'var(--txt)', marginTop:4 }}>{m.lbl}</div>
              <div style={{ fontSize:11, color:'var(--txt3)', marginTop:2 }}>{m.sub}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Agent memory */}
      {resolutions.length > 0 && (
        <div className="card" style={{ marginTop:18, padding:0 }}>
          <div style={{ padding:'16px 20px 12px' }}><div className="card-title" style={{ marginBottom:0 }}>Agent Memory — Past Resolutions</div></div>
          <div className="tbl-wrap">
            <table>
              <thead><tr><th>Host</th><th>Fault</th><th>Fix Applied</th><th>Time</th><th>Level</th><th>Date</th></tr></thead>
              <tbody>
                {resolutions.slice(0,20).map(r => (
                  <tr key={r.id} style={{ cursor:'default' }}>
                    <td><span style={{ fontFamily:'var(--mono)', fontSize:12 }}>{r.host||'—'}</span></td>
                    <td><span className={`badge ${r.fault}`} style={{ fontSize:10 }}>{r.fault?.replace(/_/g,' ')}</span></td>
                    <td className="pri" style={{ maxWidth:200 }}><div style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{r.fix||'—'}</div></td>
                    <td style={{ fontSize:12 }}>{r.time_min ? `${Math.round(r.time_min)}m` : '—'}</td>
                    <td><span className={`badge ${r.level === 'l1' ? 'p4' : r.level === 'l2' ? 'p3' : 'p2'}`}>{r.level?.toUpperCase()||'—'}</span></td>
                    <td style={{ fontFamily:'var(--mono)', fontSize:11, color:'var(--txt3)' }}>{r.date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

export default Approvals
