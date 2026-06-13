import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, RefreshCw, Search } from 'lucide-react'
import { api } from '../api/client'

export default function Incidents() {
  const navigate = useNavigate()
  const [incidents, setIncidents] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [search,    setSearch]    = useState('')
  const [filterP,   setFilterP]   = useState('')
  const [filterS,   setFilterS]   = useState('')
  const [modal,     setModal]     = useState(false)
  const [form,      setForm]      = useState({ title:'', description:'', affected_host:'', affected_service:'', auto_run:true })
  const [creating,  setCreating]  = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      let q = '?limit=100'
      if (filterP) q += `&priority=${filterP}`
      if (filterS) q += `&status=${filterS}`
      setIncidents(await api.incidents.list(q))
    } catch {}
    setLoading(false)
  }

  useEffect(() => { load() }, [filterP, filterS])
  useEffect(() => { const t = setInterval(load, 8000); return () => clearInterval(t) }, [filterP, filterS])

  const filtered = incidents.filter(i =>
    !search ||
    i.title?.toLowerCase().includes(search.toLowerCase()) ||
    i.number?.toLowerCase().includes(search.toLowerCase()) ||
    i.affected_host?.includes(search)
  )

  const create = async () => {
    setCreating(true)
    try {
      const inc = await api.incidents.create(form)
      setModal(false)
      navigate(`/incidents/${inc.id}`)
    } catch (e) { alert(e.message) }
    setCreating(false)
  }

  const slaInfo = (i) => {
    if (!i.sla_resolve_due) return null
    const now = Date.now()
    const due = new Date(i.sla_resolve_due).getTime()
    if (now > due) return { cls:'p1', txt:'BREACHED' }
    const mins = Math.floor((due - now) / 60000)
    if (mins < 30) return { cls:'p2', txt:`${mins}m left` }
    return { cls:'p4', txt: mins >= 60 ? `${Math.floor(mins/60)}h ${mins%60}m` : `${mins}m` }
  }

  return (
    <div className="page">
      <div className="ph">
        <div>
          <div className="ph-title">Incidents</div>
          <div className="ph-sub">{filtered.length} incidents</div>
        </div>
        <div className="ph-actions">
          <button className="btn btn-secondary btn-sm" onClick={load}><RefreshCw size={13} /></button>
          <button className="btn btn-primary" onClick={() => setModal(true)}><Plus size={14} /> New</button>
        </div>
      </div>

      {/* Filters */}
      <div className="card" style={{ marginBottom:16, padding:'12px 16px' }}>
        <div style={{ display:'flex', gap:10, flexWrap:'wrap', alignItems:'center' }}>
          <div style={{ display:'flex', alignItems:'center', gap:8, flex:1, minWidth:180 }}>
            <Search size={13} style={{ color:'var(--txt3)', flexShrink:0 }} />
            <input style={{ padding:'6px 10px' }} placeholder="Search title, host, number…" value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <select style={{ width:140, padding:'6px 10px' }} value={filterP} onChange={e => setFilterP(e.target.value)}>
            <option value="">All priorities</option>
            {['p1','p2','p3','p4'].map(p => <option key={p} value={p}>{p.toUpperCase()}</option>)}
          </select>
          <select style={{ width:180, padding:'6px 10px' }} value={filterS} onChange={e => setFilterS(e.target.value)}>
            <option value="">All statuses</option>
            {['new','triaging','l1_running','l2_running','l3_escalated','resolved','closed'].map(s =>
              <option key={s} value={s}>{s.replace(/_/g,' ')}</option>)}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="card" style={{ padding:0 }}>
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Number</th><th>Title</th><th>Host</th><th>Category</th>
                <th>Priority</th><th>Status</th><th>Source</th><th>SLA</th><th>Created</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9}><div className="loading"><div className="spinner"/>Loading…</div></td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={9}><div className="empty"><p>No incidents found</p></div></td></tr>
              ) : filtered.map(i => {
                const sla = slaInfo(i)
                return (
                  <tr key={i.id} onClick={() => navigate(`/incidents/${i.id}`)}>
                    <td><span className="chip">{i.number}</span></td>
                    <td className="pri" style={{ maxWidth:220 }}>
                      <div style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{i.title}</div>
                    </td>
                    <td><span style={{ fontFamily:'var(--mono)', fontSize:12 }}>{i.affected_host || '—'}</span></td>
                    <td>{i.fault_category ? <span className={`badge ${i.fault_category}`}>{i.fault_category.replace(/_/g,' ')}</span> : '—'}</td>
                    <td>{i.priority ? <span className={`badge ${i.priority}`}>{i.priority.toUpperCase()}</span> : '—'}</td>
                    <td><span className={`badge ${i.status}`}>{i.status?.replace(/_/g,' ')}</span></td>
                    <td><span style={{ fontSize:11, color:'var(--txt3)' }}>{i.source}</span></td>
                    <td>{sla ? <span className={`badge ${sla.cls}`} style={{ fontSize:10 }}>{sla.txt}</span> : '—'}</td>
                    <td><span style={{ fontFamily:'var(--mono)', fontSize:11, color:'var(--txt3)' }}>{String(i.created_at).slice(0,16).replace('T',' ')}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal */}
      {modal && (
        <div className="overlay" onClick={e => e.target === e.currentTarget && setModal(false)}>
          <div className="modal">
            <div className="modal-title">Create Incident</div>
            <div className="fg"><label className="fl">Title *</label>
              <input placeholder="High disk usage on web-server-01" value={form.title} onChange={e => setForm({...form,title:e.target.value})} />
            </div>
            <div className="f2">
              <div className="fg"><label className="fl">Host</label>
                <input placeholder="hostname or IP" value={form.affected_host} onChange={e => setForm({...form,affected_host:e.target.value})} />
              </div>
              <div className="fg"><label className="fl">Service</label>
                <input placeholder="nginx, mysql…" value={form.affected_service} onChange={e => setForm({...form,affected_service:e.target.value})} />
              </div>
            </div>
            <div className="fg"><label className="fl">Description</label>
              <textarea placeholder="Additional details…" value={form.description} onChange={e => setForm({...form,description:e.target.value})} />
            </div>
            <div className="fg">
              <label style={{ display:'flex', alignItems:'center', gap:8, cursor:'pointer' }}>
                <input type="checkbox" style={{ width:'auto' }} checked={form.auto_run} onChange={e => setForm({...form,auto_run:e.target.checked})} />
                <span style={{ fontSize:13, color:'var(--txt2)' }}>Run agent automatically</span>
              </label>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setModal(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={create} disabled={!form.title||creating}>
                {creating ? <><div className="spinner" style={{width:13,height:13}}/> Creating…</> : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
