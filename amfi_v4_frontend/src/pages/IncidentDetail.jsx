import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Play, RefreshCw } from 'lucide-react'
import { api } from '../api/client'

function TLIcon({ step }) {
  if (step.status === 'success' && step.type === 'action') return <div className="tl-icon action">⚡</div>
  if (step.status === 'success') return <div className="tl-icon ok">✓</div>
  if (step.status === 'failed')  return <div className="tl-icon fail">✗</div>
  if (step.status === 'skipped') return <div className="tl-icon skip">—</div>
  if (step.status === 'waiting') return <div className="tl-icon wait">⏳</div>
  if (step.type === 'escalation')return <div className="tl-icon esc">↑</div>
  if (step.type === 'action')    return <div className="tl-icon action">⚡</div>
  return <div className="tl-icon diag">◎</div>
}

export default function IncidentDetail() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const [inc,     setInc]     = useState(null)
  const [steps,   setSteps]   = useState([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)

  const load = async () => {
    try {
      const [i, s] = await Promise.all([api.incidents.get(+id), api.incidents.steps(+id)])
      setInc(i); setSteps(s)
    } catch {}
    setLoading(false)
  }

  useEffect(() => { load() }, [id])
  useEffect(() => {
    if (!inc || ['resolved','closed','false_positive'].includes(inc.status)) return
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [inc?.status])

  const runAgent = async () => {
    setRunning(true)
    try { await api.incidents.run(+id); await load() } catch (e) { alert(e.message) }
    setRunning(false)
  }

  if (loading) return <div className="loading"><div className="spinner"/>Loading…</div>
  if (!inc)    return <div className="page"><p style={{color:'var(--txt3)'}}>Incident not found</p></div>

  const active = !['resolved','closed','false_positive'].includes(inc.status)

  return (
    <div className="page">
      {/* Top bar */}
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:22 }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/incidents')} style={{padding:'5px 8px'}}><ArrowLeft size={14}/></button>
        <span className="chip" style={{ fontSize:13 }}>{inc.number}</span>
        <div style={{ flex:1 }}/>
        <button className="btn btn-secondary btn-sm" onClick={load}><RefreshCw size={13}/></button>
        {active && (
          <button className="btn btn-primary btn-sm" onClick={runAgent} disabled={running}>
            {running ? <><div className="spinner" style={{width:12,height:12}}/> Running…</> : <><Play size={13}/> Run Agent</>}
          </button>
        )}
      </div>

      {/* Incident header */}
      <div className="card" style={{ marginBottom:18, borderLeft:`4px solid ${inc.priority === 'p1' ? 'var(--p1)' : inc.priority === 'p2' ? 'var(--p2)' : inc.priority === 'p3' ? 'var(--p3)' : 'var(--p4)'}` }}>
        <div className="chip" style={{ fontSize:12, marginBottom:6 }}>{inc.number}</div>
        <div style={{ fontSize:20, fontWeight:700, marginBottom:10 }}>{inc.title}</div>
        {inc.description && <div style={{ fontSize:13, color:'var(--txt3)', marginBottom:12 }}>{inc.description}</div>}

        <div style={{ display:'flex', gap:20, flexWrap:'wrap' }}>
          {[
            { lbl:'Status',    val:<span className={`badge ${inc.status}`}>{inc.status?.replace(/_/g,' ')}</span> },
            { lbl:'Priority',  val: inc.priority ? <span className={`badge ${inc.priority}`}>{inc.priority.toUpperCase()}</span> : '—' },
            { lbl:'Category',  val: inc.fault_category ? <span className={`badge ${inc.fault_category}`}>{inc.fault_category.replace(/_/g,' ')}</span> : '—' },
            { lbl:'Host',      val:<span style={{fontFamily:'var(--mono)',fontSize:12}}>{inc.affected_host || '—'}</span> },
            { lbl:'Service',   val: inc.affected_service || '—' },
            { lbl:'Source',    val: inc.source },
            { lbl:'Attempts',  val: inc.attempt_count ?? 0 },
            { lbl:'Created',   val:<span style={{fontFamily:'var(--mono)',fontSize:12}}>{String(inc.created_at).slice(0,16).replace('T',' ')}</span> },
          ].map(({ lbl, val }) => (
            <div key={lbl}>
              <div style={{ fontSize:10, fontWeight:600, color:'var(--txt3)', textTransform:'uppercase', letterSpacing:'.8px', marginBottom:3 }}>{lbl}</div>
              <div style={{ fontSize:13, color:'var(--txt2)' }}>{val}</div>
            </div>
          ))}
        </div>

        {/* SLA */}
        {inc.sla_resolve_due && (
          <div style={{ marginTop:14, padding:'10px 14px', background:'var(--hover)', borderRadius:8 }}>
            <div style={{ display:'flex', justifyContent:'space-between', marginBottom:4 }}>
              <span style={{ fontSize:11, color:'var(--txt3)' }}>SLA Resolve Due</span>
              <span style={{ fontSize:12, fontFamily:'var(--mono)', color: inc.sla_breached ? 'var(--p1)' : 'var(--txt2)' }}>
                {String(inc.sla_resolve_due).slice(0,16).replace('T',' ')}
                {inc.sla_breached && <span style={{ color:'var(--p1)', marginLeft:8 }}>BREACHED</span>}
              </span>
            </div>
          </div>
        )}

        {/* Resolution */}
        {inc.resolution && (
          <div style={{ marginTop:14, padding:'10px 14px', background:'rgba(0,212,170,.07)', border:'1px solid rgba(0,212,170,.2)', borderRadius:8 }}>
            <div style={{ fontSize:10, fontWeight:600, color:'var(--accent)', textTransform:'uppercase', letterSpacing:'.8px', marginBottom:4 }}>Resolution</div>
            <div style={{ fontSize:13, color:'var(--txt2)', lineHeight:1.5 }}>{inc.resolution}</div>
          </div>
        )}
      </div>

      {/* Steps + info */}
      <div className="g2">
        {/* Timeline */}
        <div className="card">
          <div className="card-title">Agent Timeline — {steps.length} steps</div>
          {steps.length === 0 ? (
            <div className="empty">
              <p>No steps yet</p>
              <p style={{ fontSize:12, marginTop:4 }}>Click "Run Agent" to start</p>
            </div>
          ) : (
            <div className="timeline">
              {steps.map((s, i) => (
                <div key={i} className="tl-item">
                  <TLIcon step={s} />
                  <div className="tl-body">
                    <div className="tl-head">
                      <span className="tl-type">{s.type?.replace(/_/g,' ')}</span>
                      {s.action && <span className="tl-action">{s.action}</span>}
                      <span className="tl-time">{String(s.created_at).slice(11,19)}</span>
                    </div>

                    {/* AI interpretation — most important, show prominently */}
                    {s.ai_interpret && (
                      <div style={{ fontSize:13, color:'var(--txt)', background:'rgba(168,85,247,.08)', border:'1px solid rgba(168,85,247,.2)', borderRadius:6, padding:'7px 10px', marginBottom:5, lineHeight:1.5 }}>
                        🤖 {s.ai_interpret}
                      </div>
                    )}

                    {/* Issues found */}
                    {s.result?.issues?.length > 0 && (
                      <div className="tl-text">
                        {s.result.issues.map((iss, j) => (
                          <div key={j} style={{ color: iss.includes('CRITICAL') ? 'var(--p1)' : iss.includes('WARNING') ? 'var(--p2)' : 'var(--txt2)' }}>{iss}</div>
                        ))}
                      </div>
                    )}

                    {/* Verification result */}
                    {s.result?.verified !== undefined && (
                      <div style={{ fontSize:12, color: s.result.verified ? 'var(--p4)' : 'var(--p1)', marginTop:3 }}>
                        {s.result.verified ? '✓ Verified OK' : '✗ Verification failed'}
                        {s.result.verification && ` — ${s.result.verification}`}
                      </div>
                    )}

                    {/* Raw output for diagnostics */}
                    {s.output && s.type === 'diagnostic' && !s.ai_interpret && (
                      <div className="tl-output">{String(s.output).slice(0,400)}</div>
                    )}

                    {/* Error */}
                    {s.error && <div style={{ fontSize:12, color:'var(--p1)', marginTop:3 }}>Error: {s.error}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Info panel */}
        <div>
          <div className="card" style={{ marginBottom:14 }}>
            <div className="card-title">ITIL Info</div>
            <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
              {[
                { lbl:'Incident Number', val: inc.number },
                { lbl:'Priority',        val: inc.priority?.toUpperCase() || 'Not set' },
                { lbl:'Category',        val: inc.fault_category?.replace(/_/g,' ') || 'Not set' },
                { lbl:'Current Level',   val: inc.resolved_by || (inc.status?.includes('l1') ? 'L1' : inc.status?.includes('l2') ? 'L2' : inc.status?.includes('l3') ? 'L3' : '—') },
                { lbl:'SLA Response Due',val: inc.sla_response_due ? String(inc.sla_response_due).slice(0,16).replace('T',' ') : 'Not set' },
                { lbl:'SLA Resolve Due', val: inc.sla_resolve_due  ? String(inc.sla_resolve_due).slice(0,16).replace('T',' ')  : 'Not set' },
                { lbl:'SLA Status',      val: inc.sla_breached ? 'BREACHED' : 'OK' },
              ].map(({ lbl, val }) => (
                <div key={lbl} style={{ display:'flex', justifyContent:'space-between', borderBottom:'1px solid var(--border)', paddingBottom:8 }}>
                  <span style={{ fontSize:12, color:'var(--txt3)' }}>{lbl}</span>
                  <span style={{ fontSize:12, color: lbl === 'SLA Status' && inc.sla_breached ? 'var(--p1)' : 'var(--txt2)', fontFamily: lbl.includes('Due') || lbl.includes('Number') ? 'var(--mono)' : 'inherit' }}>{val}</span>
                </div>
              ))}
            </div>
          </div>

          {inc.root_cause && (
            <div className="card">
              <div className="card-title">Root Cause</div>
              <div style={{ fontSize:13, color:'var(--txt2)', lineHeight:1.6 }}>{inc.root_cause}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
