import { useEffect, useState, useCallback } from 'react'
import { api } from '../api'

const RISK_COLOR = { high: '#f85149', critical: '#ff6e6e', medium: '#f0883e', low: '#d29922' }

const parseUTC = (ts) => ts ? new Date(ts.endsWith('Z') ? ts : ts + 'Z') : null
const TS = (ts) => parseUTC(ts)?.toLocaleString() ?? '—'
const elapsed = (ts) => {
  const d = parseUTC(ts)
  if (!d) return ''
  const s = Math.floor((Date.now() - d) / 1000)
  if (s < 60)  return `${s}s ago`
  if (s < 3600) return `${Math.floor(s/60)}m ago`
  return `${Math.floor(s/3600)}h ago`
}

export default function Approvals() {
  const [tab,       setTab]       = useState('pending')   // 'pending' | 'history'
  const [items,     setItems]     = useState([])
  const [loading,   setLoading]   = useState(true)
  const [selected,  setSelected]  = useState(null)       // full approval object
  const [note,      setNote]      = useState('')
  const [acting,    setActing]    = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const status = tab === 'pending' ? 'pending' : undefined
      const data   = await api.approvals(status)
      setItems(Array.isArray(data) ? data : [])
    } catch { setItems([]) }
    finally { setLoading(false) }
  }, [tab])

  useEffect(() => { load() }, [load])

  // Re-poll pending every 15s
  useEffect(() => {
    if (tab !== 'pending') return
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [tab, load])

  // WS live update
  useEffect(() => {
    const handler = () => load()
    window.addEventListener('amfi:ws', handler)
    return () => window.removeEventListener('amfi:ws', handler)
  }, [load])

  const act = async (action) => {
    if (!selected) return
    setActing(true)
    try {
      if (action === 'approve') await api.approve(selected.token, note)
      else                      await api.reject(selected.token, note)
      setSelected(null); setNote(''); load()
    } catch (e) {
      alert(`Failed: ${e.message}`)
    } finally { setActing(false) }
  }

  const pending = items.filter(i => i.status === 'pending')
  const history = items.filter(i => i.status !== 'pending')

  const display = tab === 'pending' ? pending : history

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', overflow:'hidden' }}>

      {/* Header */}
      <div style={{
        padding:'0 24px', height:52, display:'flex', alignItems:'center',
        background:'var(--bg2)', borderBottom:'1px solid var(--border)',
        justifyContent:'space-between', flexShrink:0,
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          <h1 style={{ fontSize:16 }}>Action Approvals</h1>
          {pending.length > 0 && (
            <span className="badge badge-red">{pending.length} pending</span>
          )}
        </div>

        {/* Tab switcher */}
        <div style={{ display:'flex', gap:4 }}>
          {['pending','history'].map(t => (
            <button key={t}
              className={tab === t ? 'btn-primary btn-sm' : 'btn-ghost btn-sm'}
              onClick={() => setTab(t)}
              style={{ textTransform:'capitalize' }}
            >{t}</button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div style={{ flex:1, overflow:'auto', padding:'16px 24px', display:'flex', gap:16 }}>

        {/* List */}
        <div style={{ flex:1, minWidth:0 }}>
          {loading ? (
            <div className="loading">Loading approvals…</div>
          ) : display.length === 0 ? (
            <div className="empty" style={{ marginTop:64 }}>
              {tab === 'pending' ? '✓ No pending approvals — all clear' : 'No approval history yet'}
            </div>
          ) : (
            <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
              {display.map(a => {
                const rc = RISK_COLOR[a.risk_level] || '#6e7681'
                const isPending = a.status === 'pending'
                const isSelected = selected?.id === a.id
                return (
                  <div key={a.id} onClick={() => setSelected(isSelected ? null : a)}
                    style={{
                      background: isSelected ? 'var(--bg3)' : 'var(--bg2)',
                      border:`1px solid ${isSelected ? 'var(--blue)' : 'var(--border)'}`,
                      borderLeft:`3px solid ${rc}`,
                      borderRadius:'var(--radius)', padding:'14px 16px',
                      cursor:'pointer', transition:'all .15s',
                    }}>
                    <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:6 }}>
                      <span className="badge" style={{ background:rc+'22', color:rc, fontWeight:700 }}>
                        {a.risk_level?.toUpperCase()}
                      </span>
                      <span style={{ fontSize:13, fontWeight:600 }}>{a.action}</span>
                      {!isPending && (
                        <span className={`badge badge-${a.status === 'approved' ? 'green' : 'gray'}`}
                          style={{ marginLeft:'auto' }}>
                          {a.status === 'approved' ? '✓ Approved' : '✕ Rejected'}
                        </span>
                      )}
                      {isPending && (
                        <span className="badge badge-yellow" style={{ marginLeft:'auto' }}>
                          ⏳ Awaiting
                        </span>
                      )}
                    </div>

                    <div style={{ display:'flex', gap:16, fontSize:12, color:'var(--text3)' }}>
                      <span>Incident #{a.incident_id}</span>
                      {a.host && <span>Host: <span style={{ color:'var(--text2)' }}>{a.host}</span></span>}
                      <span>Created {elapsed(a.created_at)}</span>
                      {a.decided_at && <span>Decided {elapsed(a.decided_at)}</span>}
                    </div>

                    {a.reason && (
                      <div style={{ fontSize:12, color:'var(--text2)', marginTop:6, lineHeight:1.5 }}>
                        {a.reason}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Detail panel */}
        {selected && (
          <div style={{
            width:380, flexShrink:0,
            background:'var(--bg2)', border:'1px solid var(--border)',
            borderRadius:'var(--radius)', padding:'20px',
            display:'flex', flexDirection:'column', gap:14,
            height:'fit-content', position:'sticky', top:0,
          }}>
            <div style={{ fontSize:15, fontWeight:700 }}>Approval Detail</div>

            <InfoRow label="Action"      value={selected.action} mono />
            <InfoRow label="Host"        value={selected.host || '—'} />
            <InfoRow label="Risk Level"  value={selected.risk_level?.toUpperCase()}
              color={RISK_COLOR[selected.risk_level]} />
            <InfoRow label="Incident #"  value={`#${selected.incident_id}`} />
            <InfoRow label="Status"      value={selected.status} />

            {selected.incident_summary && (
              <div>
                <div style={{ fontSize:11, color:'var(--text3)', textTransform:'uppercase', marginBottom:4 }}>Incident Summary</div>
                <div style={{
                  background:'var(--bg3)', borderRadius:'var(--radius-sm)',
                  padding:'10px 12px', fontSize:12, color:'var(--text2)', lineHeight:1.6,
                }}>
                  {selected.incident_summary}
                </div>
              </div>
            )}

            {selected.reason && (
              <div>
                <div style={{ fontSize:11, color:'var(--text3)', textTransform:'uppercase', marginBottom:4 }}>Reason</div>
                <div style={{
                  background:'var(--bg3)', borderRadius:'var(--radius-sm)',
                  padding:'10px 12px', fontSize:12, color:'var(--text2)', lineHeight:1.6,
                }}>
                  {selected.reason}
                </div>
              </div>
            )}

            {selected.rollback && (
              <div>
                <div style={{ fontSize:11, color:'var(--text3)', textTransform:'uppercase', marginBottom:4 }}>Rollback Plan</div>
                <div style={{
                  background:'var(--bg3)', borderRadius:'var(--radius-sm)',
                  padding:'10px 12px', fontSize:12, color:'var(--text2)', lineHeight:1.6,
                  fontFamily:'monospace',
                }}>
                  {selected.rollback}
                </div>
              </div>
            )}

            {/* Decision note */}
            {selected.status === 'pending' && (
              <div className="form-row" style={{ marginBottom:0 }}>
                <label>Decision Note (optional)</label>
                <input
                  value={note}
                  onChange={e => setNote(e.target.value)}
                  placeholder="Add context for audit trail…"
                />
              </div>
            )}

            {/* Approve / Reject */}
            {selected.status === 'pending' ? (
              <div style={{ display:'flex', gap:8 }}>
                <button className="btn-primary" disabled={acting}
                  onClick={() => act('approve')}
                  style={{ flex:1, justifyContent:'center' }}>
                  {acting ? '…' : '✓ Approve'}
                </button>
                <button className="btn-danger" disabled={acting}
                  onClick={() => act('reject')}
                  style={{ flex:1, justifyContent:'center' }}>
                  {acting ? '…' : '✕ Reject'}
                </button>
              </div>
            ) : (
              <div>
                <InfoRow label="Decided By" value={selected.decided_by || '—'} />
                {selected.decision_note && (
                  <InfoRow label="Note" value={selected.decision_note} />
                )}
                <InfoRow label="Decided At" value={TS(selected.decided_at)} />
              </div>
            )}

            <div style={{ fontSize:11, color:'var(--text3)', textAlign:'right' }}>
              Created {TS(selected.created_at)}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function InfoRow({ label, value, mono, color }) {
  return (
    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:8 }}>
      <span style={{ fontSize:12, color:'var(--text3)', flexShrink:0, paddingTop:1 }}>{label}</span>
      <span style={{
        fontSize:12, color: color || 'var(--text)', fontWeight:500,
        fontFamily: mono ? 'monospace' : undefined,
        textAlign:'right', wordBreak:'break-all',
      }}>{value}</span>
    </div>
  )
}
