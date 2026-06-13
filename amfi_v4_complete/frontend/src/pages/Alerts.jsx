import { useEffect, useState, useCallback } from 'react'
import { api } from '../api'

const METRICS = [
  'cpu_percent','ram_percent','disk_percent','load_1m',
  'ping_up','ping_ms','net_rx_bps','net_tx_bps','if_up_pct','uptime_seconds',
]
const OPERATORS = [
  { v:'gt', l:'> (greater than)' }, { v:'gte', l:'≥ (greater or equal)' },
  { v:'lt', l:'< (less than)' },    { v:'lte', l:'≤ (less or equal)' },
  { v:'eq', l:'= (equal)' },
]
const FAULT_CATS = [
  'high_cpu','high_memory','disk_full','service_down','network_down',
  'high_latency','database_issue','security_alert','hardware_failure',
  'application_error','unknown',
]
const PRIO_COLOR = { p1:'#f85149', p2:'#f0883e', p3:'#d29922', p4:'#6e7681' }
const OP_SYMBOL  = { gt:'>', gte:'≥', lt:'<', lte:'≤', eq:'=' }

export default function Alerts() {
  const [rules,   setRules]   = useState([])
  const [hosts,   setHosts]   = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [editRule, setEditRule] = useState(null)
  const [form,    setForm]    = useState({
    name:'', host_id:null, device_type:'',
    metric:'cpu_percent', operator:'gt', threshold:80,
    priority:'p3', fault_category:'high_cpu', cooldown_minutes:30, enabled:true,
  })

  const load = useCallback(async () => {
    try {
      const [r, h] = await Promise.all([api.thresholdRules(), api.monitoredHosts()])
      setRules(r); setHosts(h)
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const openAdd = () => {
    setEditRule(null)
    setForm({ name:'', host_id:null, device_type:'', metric:'cpu_percent', operator:'gt',
              threshold:80, priority:'p3', fault_category:'high_cpu', cooldown_minutes:30, enabled:true })
    setShowAdd(true)
  }
  const openEdit = (r) => {
    setEditRule(r)
    setForm({ ...r, host_id: r.host_id || null, device_type: r.device_type || '' })
    setShowAdd(true)
  }

  const save = async () => {
    const body = {
      ...form,
      threshold: Number(form.threshold),
      cooldown_minutes: Number(form.cooldown_minutes),
      host_id: form.host_id ? Number(form.host_id) : null,
      device_type: form.device_type || null,
    }
    if (editRule) await api.updateThresholdRule(editRule.id, body)
    else          await api.createThresholdRule(body)
    setShowAdd(false); load()
  }

  const del = async (id) => {
    if (!confirm('Delete this threshold rule?')) return
    await api.deleteThresholdRule(id)
    load()
  }

  const toggle = async (rule) => {
    await api.updateThresholdRule(rule.id, { ...rule, enabled: !rule.enabled })
    load()
  }

  const enabled  = rules.filter(r => r.enabled).length
  const disabled = rules.filter(r => !r.enabled).length

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', overflow:'hidden' }}>
      {/* Header */}
      <div style={{
        padding:'0 24px', height:52, display:'flex', alignItems:'center',
        background:'var(--bg2)', borderBottom:'1px solid var(--border)',
        justifyContent:'space-between', flexShrink:0,
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          <h1 style={{ fontSize:16 }}>Threshold Rules</h1>
          <span className="badge badge-green">{enabled} active</span>
          {disabled > 0 && <span className="badge badge-gray">{disabled} disabled</span>}
        </div>
        <button className="btn-primary btn-sm" onClick={openAdd}>+ Add Rule</button>
      </div>

      {/* Table */}
      <div style={{ flex:1, overflow:'auto', padding:'0 24px' }}>
        {loading
          ? <div className="loading">Loading rules…</div>
          : rules.length === 0
            ? <div className="empty">No threshold rules yet</div>
            : <table className="tbl">
                <thead>
                  <tr>
                    <th style={{width:36}}>ON</th>
                    <th>NAME</th>
                    <th>CONDITION</th>
                    <th>PRIORITY</th>
                    <th>FAULT CATEGORY</th>
                    <th>COOLDOWN</th>
                    <th>SCOPE</th>
                    <th>ACTIONS</th>
                  </tr>
                </thead>
                <tbody>
                  {rules.map(r => {
                    const pc = PRIO_COLOR[r.priority] || '#6e7681'
                    return (
                      <tr key={r.id} style={{ opacity: r.enabled ? 1 : .45 }}>
                        <td onClick={e => { e.stopPropagation(); toggle(r) }}>
                          <div style={{
                            width:32, height:18, borderRadius:9,
                            background: r.enabled ? 'var(--green)' : 'var(--bg3)',
                            border: r.enabled ? 'none' : '1px solid var(--border2)',
                            cursor:'pointer', transition:'background .2s',
                            display:'flex', alignItems:'center',
                            padding: r.enabled ? '0 2px 0 14px' : '0 14px 0 2px',
                          }}>
                            <div style={{ width:14, height:14, borderRadius:'50%', background:'#fff' }} />
                          </div>
                        </td>
                        <td style={{ fontWeight:500 }}>{r.name}</td>
                        <td className="mono" style={{ fontSize:12, color:'var(--text2)' }}>
                          {r.metric} {OP_SYMBOL[r.operator] || r.operator} {r.threshold}
                        </td>
                        <td>
                          <span className="badge" style={{ background:pc+'22', color:pc }}>
                            {r.priority?.toUpperCase()}
                          </span>
                        </td>
                        <td style={{ color:'var(--text3)', fontSize:12 }}>{r.fault_category}</td>
                        <td style={{ color:'var(--text2)', fontSize:12 }}>{r.cooldown_minutes}m</td>
                        <td style={{ fontSize:11, color:'var(--text3)' }}>
                          {r.host_id
                            ? hosts.find(h => h.id === r.host_id)?.hostname || `host #${r.host_id}`
                            : r.device_type ? `All ${r.device_type}` : 'All hosts'
                          }
                        </td>
                        <td onClick={e => e.stopPropagation()}>
                          <div style={{ display:'flex', gap:4 }}>
                            <button className="btn-ghost btn-sm" onClick={() => openEdit(r)}>Edit</button>
                            <button className="btn-danger btn-sm"  onClick={() => del(r.id)}>✕</button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
        }
      </div>

      {/* Add / Edit modal */}
      {showAdd && (
        <div className="modal-overlay" onClick={() => setShowAdd(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-title">{editRule ? 'Edit Rule' : 'New Threshold Rule'}</div>

            <div className="form-row">
              <label>Rule Name *</label>
              <input value={form.name} onChange={e => setForm({...form,name:e.target.value})} placeholder="e.g. CPU Critical on DB servers" />
            </div>

            <div className="form-grid-2">
              <div className="form-row">
                <label>Metric *</label>
                <select value={form.metric} onChange={e => setForm({...form,metric:e.target.value})}>
                  {METRICS.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div className="form-row">
                <label>Operator</label>
                <select value={form.operator} onChange={e => setForm({...form,operator:e.target.value})}>
                  {OPERATORS.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
                </select>
              </div>
            </div>

            <div className="form-grid-2">
              <div className="form-row">
                <label>Threshold Value *</label>
                <input type="number" value={form.threshold} onChange={e => setForm({...form,threshold:e.target.value})} />
              </div>
              <div className="form-row">
                <label>Cooldown (minutes)</label>
                <input type="number" value={form.cooldown_minutes} onChange={e => setForm({...form,cooldown_minutes:e.target.value})} min={1} />
              </div>
            </div>

            <div className="form-grid-2">
              <div className="form-row">
                <label>Incident Priority</label>
                <select value={form.priority} onChange={e => setForm({...form,priority:e.target.value})}>
                  <option value="p1">P1 — Critical</option>
                  <option value="p2">P2 — High</option>
                  <option value="p3">P3 — Medium</option>
                  <option value="p4">P4 — Low</option>
                </select>
              </div>
              <div className="form-row">
                <label>Fault Category</label>
                <select value={form.fault_category} onChange={e => setForm({...form,fault_category:e.target.value})}>
                  {FAULT_CATS.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>

            <div className="form-grid-2">
              <div className="form-row">
                <label>Apply to Host (blank = all)</label>
                <select value={form.host_id || ''} onChange={e => setForm({...form,host_id:e.target.value||null})}>
                  <option value="">All hosts</option>
                  {hosts.map(h => <option key={h.id} value={h.id}>{h.display_name||h.hostname}</option>)}
                </select>
              </div>
              <div className="form-row">
                <label>Device Type Filter (blank = all)</label>
                <select value={form.device_type||''} onChange={e => setForm({...form,device_type:e.target.value||''})}>
                  <option value="">All types</option>
                  <option value="linux">Linux</option>
                  <option value="windows">Windows</option>
                  <option value="network">Network</option>
                  <option value="generic">Generic</option>
                </select>
              </div>
            </div>

            <div className="form-row" style={{ flexDirection:'row', alignItems:'center', gap:10 }}>
              <input type="checkbox" id="enabled-cb" checked={form.enabled}
                onChange={e => setForm({...form,enabled:e.target.checked})} style={{ width:'auto' }} />
              <label htmlFor="enabled-cb" style={{ color:'var(--text)', fontWeight:400, cursor:'pointer' }}>Rule enabled</label>
            </div>

            <div style={{
              background:'var(--bg3)', borderRadius:6, padding:'10px 14px',
              fontSize:12, color:'var(--text2)', marginBottom:4,
            }}>
              Preview: <span className="mono" style={{ color:'var(--blue)' }}>
                {form.metric} {OP_SYMBOL[form.operator]||form.operator} {form.threshold}
              </span>
              {' → '}create <span style={{ color: PRIO_COLOR[form.priority] }}>{form.priority?.toUpperCase()}</span>{' '}
              <span style={{ color:'var(--text3)' }}>{form.fault_category}</span> incident,
              cooldown {form.cooldown_minutes}m
            </div>

            <div className="modal-footer">
              <button className="btn-ghost" onClick={() => setShowAdd(false)}>Cancel</button>
              <button className="btn-primary" onClick={save} disabled={!form.name.trim()}>
                {editRule ? 'Save Changes' : 'Create Rule'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
