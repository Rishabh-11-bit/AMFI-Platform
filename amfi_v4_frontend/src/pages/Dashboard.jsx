import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Plus } from 'lucide-react'
import { api } from '../api/client'

function SLABar({ created, due }) {
  if (!due) return null
  const now  = Date.now()
  const start = new Date(created).getTime()
  const end   = new Date(due).getTime()
  const pct   = Math.min(((now - start) / (end - start)) * 100, 110)
  const cls   = pct >= 100 ? 'crit' : pct >= 80 ? 'warn' : 'ok'
  return <div className="sla-bar"><div className={`sla-fill ${cls}`} style={{ width: `${Math.min(pct,100)}%` }} /></div>
}

function PBadge({ p }) {
  if (!p) return <span className="badge unknown">—</span>
  return <span className={`badge ${p}`}>{p.toUpperCase()}</span>
}

function SBadge({ s }) {
  return <span className={`badge ${s?.replace(/ /g,'_')}`}>{s?.replace(/_/g,' ')}</span>
}

export default function Dashboard({ stats, health }) {
  const navigate = useNavigate()
  const [steps,    setSteps]   = useState([])
  const [modal,    setModal]   = useState(false)
  const [form,     setForm]    = useState({ title:'', description:'', affected_host:'', affected_service:'', auto_run: true })
  const [creating, setCreating]= useState(false)

  useEffect(() => {
    const loadSteps = async () => {
      try {
        const incs = await api.incidents.list('?limit=5')
        const all  = await Promise.all(incs.slice(0,3).map(i => api.incidents.steps(i.id).catch(() => [])))
        setSteps(all.flat().slice(-15).reverse())
      } catch {}
    }
    loadSteps()
    const t = setInterval(loadSteps, 7000)
    return () => clearInterval(t)
  }, [])

  const create = async () => {
    if (!form.title) return
    setCreating(true)
    try {
      const inc = await api.incidents.create(form)
      setModal(false)
      setForm({ title:'', description:'', affected_host:'', affected_service:'', auto_run: true })
      navigate(`/incidents/${inc.id}`)
    } catch (e) { alert(e.message) }
    setCreating(false)
  }

  const s = stats?.incidents || {}
  const agent = stats?.agent || {}

  function stepIcon(step) {
    if (step.status === 'success') return { cls:'ok',   icon:'✓' }
    if (step.status === 'failed')  return { cls:'fail',  icon:'✗' }
    if (step.type === 'escalation')return { cls:'esc',  icon:'↑' }
    if (step.ai_interpret)         return { cls:'ai',   icon:'🤖' }
    if (step.type === 'action')    return { cls:'ok',   icon:'⚡' }
    return { cls:'diag', icon:'◎' }
  }

  return (
    <div className="page">
      <div className="ph">
        <div>
          <div className="ph-title">NOC Dashboard</div>
          <div className="ph-sub">Real-time autonomous incident management</div>
        </div>
        <div className="ph-actions">
          <button className="btn btn-primary" onClick={() => setModal(true)}>
            <Plus size={14} /> New Incident
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="stats">
        <div className="stat blue">
          <div className="stat-val">{s.total ?? 0}</div>
          <div className="stat-lbl">Total</div>
        </div>
        <div className="stat orange">
          <div className="stat-val">{s.open ?? 0}</div>
          <div className="stat-lbl">Open</div>
        </div>
        <div className="stat green">
          <div className="stat-val">{s.resolved ?? 0}</div>
          <div className="stat-lbl">Resolved</div>
        </div>
        <div className="stat red">
          <div className="stat-val">{s.sla_breached ?? 0}</div>
          <div className="stat-lbl">SLA Breached</div>
        </div>
        <div className="stat green">
          <div className="stat-val">{s.auto_resolution_rate ?? '0%'}</div>
          <div className="stat-lbl">Auto-resolved</div>
        </div>
        <div className="stat yellow">
          <div className="stat-val">{stats?.pending_approvals ?? 0}</div>
          <div className="stat-lbl">Pending Approvals</div>
        </div>
      </div>

      <div className="g2">
        {/* Recent incidents */}
        <div className="card">
          <div className="card-title">Recent Incidents</div>
          {stats?.recent_incidents?.length > 0 ? (
            <div className="tbl-wrap">
              <table>
                <thead><tr><th>Number</th><th>Title</th><th>Priority</th><th>Status</th><th>SLA</th></tr></thead>
                <tbody>
                  {stats.recent_incidents.map(i => (
                    <tr key={i.id} onClick={() => navigate(`/incidents/${i.id}`)}>
                      <td><span className="chip">{i.number}</span></td>
                      <td className="pri" style={{ maxWidth: 160 }}>
                        <div style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{i.title}</div>
                      </td>
                      <td><PBadge p={i.priority} /></td>
                      <td><SBadge s={i.status} /></td>
                      <td style={{ width: 70 }}><SLABar created={i.created_at} due={i.sla_resolve_due} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty">
              <AlertTriangle size={32} />
              <p style={{ marginTop:8 }}>No incidents yet</p>
              <p style={{ fontSize:12, marginTop:4 }}>Create one to start the agent</p>
            </div>
          )}
        </div>

        {/* Live agent feed */}
        <div className="feed">
          <div className="feed-hd">
            <div className="dot on" />
            <div className="feed-title">Live Agent Feed</div>
            <div style={{ marginLeft:'auto', fontSize:11, color:'var(--txt3)' }}>
              {agent.ai_engine === 'claude' ? '🤖 Claude AI' : agent.ollama_model ? `🦙 ${agent.ollama_model}` : '⚙️ No AI'}
            </div>
          </div>
          <div className="feed-list">
            {steps.length > 0 ? steps.map((s, i) => {
              const { cls, icon } = stepIcon(s)
              return (
                <div key={i} className="feed-item">
                  <div className={`feed-ic ${cls}`}>{icon}</div>
                  <div className="feed-body">
                    <div className="feed-action">{s.action || s.type}</div>
                    {s.ai_interpret && <div className="feed-text">{s.ai_interpret.slice(0,90)}</div>}
                    {!s.ai_interpret && s.result?.issues?.[0] && <div className="feed-text">{s.result.issues[0]}</div>}
                    <div className="feed-time">{String(s.created_at).slice(0,19).replace('T',' ')}</div>
                  </div>
                </div>
              )
            }) : (
              <div className="empty" style={{ padding:'30px 20px' }}>
                <p>No agent activity yet</p>
                <p style={{ fontSize:11, marginTop:4 }}>Create an incident to start</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Agent config */}
      <div className="card" style={{ marginTop:18 }}>
        <div className="card-title">Agent Configuration</div>
        <div style={{ display:'flex', gap:32, flexWrap:'wrap' }}>
          {[
            { lbl:'AI ENGINE',    val: agent.ai_engine === 'claude' ? 'Claude API' : `Ollama · ${agent.ollama_model || 'not configured'}` },
            { lbl:'MODEL READY',  val: health?.agent?.model_ready ? '✓ Yes' : '✗ Run: ollama pull llama3.1' },
            { lbl:'MAX ATTEMPTS', val: `${agent.max_attempts ?? 3} per incident` },
            { lbl:'AUTO EXECUTE', val: agent.auto_execute ? '✓ Low-risk actions' : '✗ Manual only' },
          ].map(({ lbl, val }) => (
            <div key={lbl}>
              <div style={{ fontSize:10, color:'var(--txt3)', marginBottom:3 }}>{lbl}</div>
              <div style={{ fontSize:13, color:'var(--txt2)' }}>{val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Create incident modal */}
      {modal && (
        <div className="overlay" onClick={e => e.target === e.currentTarget && setModal(false)}>
          <div className="modal">
            <div className="modal-title">Create New Incident</div>
            <div className="fg">
              <label className="fl">Title *</label>
              <input placeholder="e.g. High disk usage on web-server-01" value={form.title} onChange={e => setForm({...form, title:e.target.value})} />
            </div>
            <div className="f2">
              <div className="fg">
                <label className="fl">Affected Host</label>
                <input placeholder="hostname or IP" value={form.affected_host} onChange={e => setForm({...form, affected_host:e.target.value})} />
              </div>
              <div className="fg">
                <label className="fl">Affected Service</label>
                <input placeholder="nginx, mysql, app…" value={form.affected_service} onChange={e => setForm({...form, affected_service:e.target.value})} />
              </div>
            </div>
            <div className="fg">
              <label className="fl">Description</label>
              <textarea placeholder="Additional details…" value={form.description} onChange={e => setForm({...form, description:e.target.value})} />
            </div>
            <div className="fg">
              <label style={{ display:'flex', alignItems:'center', gap:8, cursor:'pointer' }}>
                <input type="checkbox" style={{ width:'auto' }} checked={form.auto_run} onChange={e => setForm({...form, auto_run:e.target.checked})} />
                <span style={{ fontSize:13, color:'var(--txt2)' }}>Run agent automatically</span>
              </label>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setModal(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={create} disabled={!form.title || creating}>
                {creating ? <><div className="spinner" style={{width:13,height:13}} /> Creating…</> : 'Create Incident'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
