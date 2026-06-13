import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'

const STATUSES = ['','new','triaging','l1_running','l2_running','l3_escalated','resolved','closed']
const STATUS_LABEL = {
  new:'NEW', triaging:'TRIAGING',
  l1_running:'L1 RUN', l1_waiting:'L1 WAIT', l1_failed:'L1 FAIL',
  l2_running:'L2 RUN', l2_waiting:'L2 WAIT', l2_failed:'L2 FAIL',
  l3_escalated:'L3 ESC', resolved:'RESOLVED', closed:'CLOSED', false_positive:'FALSE+',
}
const STATUS_COLOR = {
  new:'#58a6ff', triaging:'#58a6ff',
  l1_running:'#3fb950', l1_waiting:'#d29922', l1_failed:'#f85149',
  l2_running:'#3fb950', l2_waiting:'#d29922', l2_failed:'#f85149',
  l3_escalated:'#bc8cff', resolved:'#6e7681', closed:'#484f58', false_positive:'#484f58',
}
const PRIO_COLOR = { p1:'#f85149', p2:'#f0883e', p3:'#d29922', p4:'#6e7681' }

function parseUTC(iso) {
  if (!iso) return null
  // Append Z if missing so JS treats the timestamp as UTC, not local time
  return new Date(iso.endsWith('Z') ? iso : iso + 'Z')
}
function fmtTime(iso) {
  if (!iso) return '—'
  return parseUTC(iso).toLocaleString('en-GB',{dateStyle:'short',timeStyle:'short'})
}
function fmtAge(iso) {
  if (!iso) return '—'
  const m = Math.floor((Date.now() - parseUTC(iso)) / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  if (m < 1440) return `${Math.floor(m/60)}h ago`
  return `${Math.floor(m/1440)}d ago`
}

function StepBadge({ step }) {
  const s = step.success === true ? '#3fb950' : step.success === false ? '#f85149' : '#d29922'
  return (
    <div style={{
      display:'flex', gap:10, padding:'10px 0',
      borderBottom:'1px solid var(--border)', fontSize:12,
    }}>
      <div style={{
        width:6, height:6, borderRadius:'50%', background:s,
        marginTop:4, flexShrink:0,
      }} />
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ display:'flex', gap:8, alignItems:'center', marginBottom:3 }}>
          <span style={{ color:'var(--text2)' }}>#{step.sequence}</span>
          <span style={{ fontWeight:500 }}>{step.action || step.step_type}</span>
          <span className="badge" style={{
            background: s + '22', color: s,
            fontSize:10, padding:'1px 6px',
          }}>{step.success === true ? 'OK' : step.success === false ? 'FAIL' : 'PENDING'}</span>
          {step.duration_ms && (
            <span style={{ color:'var(--text3)', marginLeft:'auto' }}>{step.duration_ms}ms</span>
          )}
        </div>
        {step.command && (
          <div className="mono" style={{
            background:'var(--bg3)', padding:'4px 8px', borderRadius:4,
            color:'var(--text2)', marginBottom:4, wordBreak:'break-all',
          }}>{step.command}</div>
        )}
        {step.ai_interpretation && (
          <div style={{
            background:'var(--purple-dim)', border:'1px solid var(--purple)',
            borderRadius:4, padding:'6px 8px', color:'var(--purple)',
            fontSize:11, marginTop:4,
          }}>⬡ {step.ai_interpretation}</div>
        )}
        {step.error && (
          <div style={{ color:'var(--red)', fontSize:11, marginTop:3 }}>⚠ {step.error}</div>
        )}
      </div>
    </div>
  )
}

function Drawer({ incId, onClose }) {
  const [inc,   setInc]   = useState(null)
  const [steps, setSteps] = useState([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    if (!incId) return
    setLoading(true)
    Promise.all([api.incident(incId), api.incidentSteps(incId)])
      .then(([i, s]) => { setInc(i); setSteps(s) })
      .finally(() => setLoading(false))
  }, [incId])

  const runAgent = async () => {
    setRunning(true)
    try {
      await api.runAgent(incId)
      setTimeout(() => {
        api.incident(incId).then(setInc)
        api.incidentSteps(incId).then(setSteps)
      }, 2000)
    } finally {
      setRunning(false)
    }
  }

  if (!incId) return null

  const pc = PRIO_COLOR[inc?.priority] || '#6e7681'
  const sc = STATUS_COLOR[inc?.status] || 'var(--text2)'

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <div className="drawer">
        {loading
          ? <div className="loading">Loading…</div>
          : inc && <>
            {/* Header */}
            <div style={{ display:'flex', alignItems:'flex-start', gap:10, marginBottom:20 }}>
              <div style={{ flex:1 }}>
                <div style={{ display:'flex', gap:8, alignItems:'center', marginBottom:6 }}>
                  <span className="badge" style={{ background:pc+'22', color:pc }}>{inc.priority?.toUpperCase()}</span>
                  <span className="mono" style={{ color:'var(--blue)' }}>{inc.number}</span>
                  <span className="badge" style={{ background:sc+'22', color:sc }}>{STATUS_LABEL[inc.status]||inc.status}</span>
                </div>
                <div style={{ fontWeight:600, fontSize:15, lineHeight:1.4 }}>{inc.title}</div>
              </div>
              <button className="btn-ghost btn-sm" onClick={onClose}>✕</button>
            </div>

            {/* Meta grid */}
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:16 }}>
              {[
                ['Host',     inc.affected_host || '—'],
                ['Service',  inc.affected_service || '—'],
                ['Source',   inc.source],
                ['Category', inc.fault_category || '—'],
                ['Created',  fmtTime(inc.created_at)],
                ['SLA Due',  fmtTime(inc.sla_resolve_due)],
              ].map(([k,v]) => (
                <div key={k} style={{ background:'var(--bg3)', borderRadius:6, padding:'8px 12px' }}>
                  <div style={{ fontSize:10, color:'var(--text3)', textTransform:'uppercase', letterSpacing:'.05em', marginBottom:2 }}>{k}</div>
                  <div style={{ fontSize:12, color:'var(--text2)', wordBreak:'break-word' }}>{v}</div>
                </div>
              ))}
            </div>

            {/* Actions */}
            <div style={{ display:'flex', gap:8, marginBottom:16 }}>
              {!['resolved','closed','l3_escalated'].includes(inc.status) && (
                <button className="btn-primary btn-sm" onClick={runAgent} disabled={running}>
                  {running ? '…Running' : '▶ Run Agent'}
                </button>
              )}
            </div>

            {/* AI brief / resolution */}
            {inc.resolution && (
              <div style={{
                background:'var(--green-dim)', border:'1px solid var(--green)',
                borderRadius:6, padding:12, marginBottom:16, fontSize:12,
              }}>
                <div style={{ color:'var(--green)', fontWeight:600, marginBottom:4 }}>✓ Resolution</div>
                <div style={{ color:'var(--text2)' }}>{inc.resolution}</div>
              </div>
            )}
            {inc.root_cause && (
              <div style={{
                background:'var(--blue-dim)', border:'1px solid var(--blue)',
                borderRadius:6, padding:12, marginBottom:16, fontSize:12,
              }}>
                <div style={{ color:'var(--blue)', fontWeight:600, marginBottom:4 }}>Root Cause</div>
                <div style={{ color:'var(--text2)' }}>{inc.root_cause}</div>
              </div>
            )}

            {/* Steps */}
            <h3 style={{ marginBottom:8 }}>Agent Steps ({steps.length})</h3>
            {steps.length === 0
              ? <div style={{ color:'var(--text3)', fontSize:12 }}>No steps yet</div>
              : steps.map(s => <StepBadge key={s.id} step={s} />)
            }
          </>
        }
      </div>
    </>
  )
}

export default function Incidents() {
  const [incs,    setIncs]    = useState([])
  const [loading, setLoading] = useState(true)
  const [search,  setSearch]  = useState('')
  const [status,  setStatus]  = useState('')
  const [prio,    setPrio]    = useState('')
  const [selId,   setSelId]   = useState(null)
  const [showNew, setShowNew] = useState(false)
  const [params, setParams]   = useSearchParams()

  const load = useCallback(async () => {
    try {
      const data = await api.incidents({ status: status||undefined, priority: prio||undefined, search: search||undefined, limit: 100 })
      setIncs(data)
    } finally { setLoading(false) }
  }, [status, prio, search])

  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t) }, [load])

  // Open drawer from query param ?id=
  useEffect(() => {
    const id = params.get('id')
    if (id) setSelId(Number(id))
  }, [params])

  // New incident form
  const [form, setForm] = useState({ title:'', affected_host:'', priority:'p3', fault_category:'' })
  const createInc = async () => {
    await api.createIncident(form)
    setShowNew(false)
    setForm({ title:'', affected_host:'', priority:'p3', fault_category:'' })
    load()
  }

  const active = incs.filter(i => !['resolved','closed','false_positive'].includes(i.status)).length

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', overflow:'hidden' }}>
      {/* Header */}
      <div style={{
        padding:'0 24px', height:52, display:'flex', alignItems:'center',
        background:'var(--bg2)', borderBottom:'1px solid var(--border)',
        justifyContent:'space-between', flexShrink:0,
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          <h1 style={{ fontSize:16 }}>Incidents</h1>
          <span className="badge badge-red">{active} active</span>
        </div>
        <button className="btn-primary btn-sm" onClick={() => setShowNew(true)}>+ New Incident</button>
      </div>

      {/* Filters */}
      <div style={{
        padding:'10px 24px', display:'flex', gap:10, alignItems:'center',
        borderBottom:'1px solid var(--border)', flexShrink:0, flexWrap:'wrap',
      }}>
        <input placeholder="Search title, INC#, host…" value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ width:240 }} />
        <select value={status} onChange={e => setStatus(e.target.value)} style={{ width:140 }}>
          <option value="">All statuses</option>
          {STATUSES.filter(Boolean).map(s => <option key={s} value={s}>{STATUS_LABEL[s]||s}</option>)}
        </select>
        <select value={prio} onChange={e => setPrio(e.target.value)} style={{ width:120 }}>
          <option value="">All priorities</option>
          {['p1','p2','p3','p4'].map(p => <option key={p} value={p}>{p.toUpperCase()}</option>)}
        </select>
        <span style={{ color:'var(--text3)', fontSize:12, marginLeft:'auto' }}>{incs.length} results</span>
      </div>

      {/* Table */}
      <div style={{ flex:1, overflow:'auto', padding:'0 24px' }}>
        {loading
          ? <div className="loading">Loading…</div>
          : incs.length === 0
            ? <div className="empty">No incidents match your filters</div>
            : <table className="tbl">
                <thead>
                  <tr>
                    <th>PRI</th><th>INC#</th><th>TITLE</th><th>HOST</th>
                    <th>CATEGORY</th><th>STATUS</th><th>SLA RESOLVE</th><th>CREATED</th>
                  </tr>
                </thead>
                <tbody>
                  {incs.map(inc => {
                    const pc = PRIO_COLOR[inc.priority] || '#6e7681'
                    const sc = STATUS_COLOR[inc.status] || 'var(--text2)'
                    return (
                      <tr key={inc.id} onClick={() => { setSelId(inc.id); setParams({ id: inc.id }) }}>
                        <td>
                          <span style={{
                            display:'inline-block', width:3, height:16, borderRadius:2,
                            background:pc, marginRight:8, verticalAlign:'middle',
                          }} />
                          <span className="badge" style={{ background:pc+'22', color:pc }}>
                            {inc.priority?.toUpperCase()}
                          </span>
                        </td>
                        <td className="mono" style={{ color:'var(--blue)', fontSize:12 }}>{inc.number}</td>
                        <td className="ellipsis" style={{ maxWidth:300 }}>{inc.title}</td>
                        <td style={{ color:'var(--text2)', fontSize:12 }}>{inc.affected_host||'—'}</td>
                        <td style={{ color:'var(--text3)', fontSize:11 }}>{inc.fault_category||'—'}</td>
                        <td>
                          <span className="badge" style={{ background:sc+'22', color:sc }}>
                            {STATUS_LABEL[inc.status]||inc.status}
                          </span>
                        </td>
                        <td style={{ fontSize:11, color:'var(--text2)' }}>
                          {inc.sla_resolve_due ? new Date(inc.sla_resolve_due).toLocaleString('en-GB',{dateStyle:'short',timeStyle:'short'}) : '—'}
                        </td>
                        <td style={{ fontSize:11, color:'var(--text3)' }}>{fmtAge(inc.created_at)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
        }
      </div>

      {/* Drawer */}
      {selId && <Drawer incId={selId} onClose={() => { setSelId(null); setParams({}) }} />}

      {/* New incident modal */}
      {showNew && (
        <div className="modal-overlay" onClick={() => setShowNew(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-title">Create Incident</div>
            <div className="form-row">
              <label>Title *</label>
              <input value={form.title} onChange={e => setForm({...form, title:e.target.value})} placeholder="Describe the incident…" />
            </div>
            <div className="form-grid-2">
              <div className="form-row">
                <label>Affected Host</label>
                <input value={form.affected_host} onChange={e => setForm({...form, affected_host:e.target.value})} placeholder="hostname or IP" />
              </div>
              <div className="form-row">
                <label>Priority</label>
                <select value={form.priority} onChange={e => setForm({...form, priority:e.target.value})}>
                  <option value="p1">P1 — Critical</option>
                  <option value="p2">P2 — High</option>
                  <option value="p3">P3 — Medium</option>
                  <option value="p4">P4 — Low</option>
                </select>
              </div>
            </div>
            <div className="form-row">
              <label>Fault Category</label>
              <select value={form.fault_category} onChange={e => setForm({...form, fault_category:e.target.value})}>
                <option value="">Auto-detect from title</option>
                {['high_cpu','high_memory','disk_full','service_down','network_down',
                  'high_latency','database_issue','security_alert','hardware_failure','application_error'].map(c =>
                  <option key={c} value={c}>{c}</option>
                )}
              </select>
            </div>
            <div className="modal-footer">
              <button className="btn-ghost" onClick={() => setShowNew(false)}>Cancel</button>
              <button className="btn-primary" onClick={createInc} disabled={!form.title.trim()}>Create & Run Agent</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
