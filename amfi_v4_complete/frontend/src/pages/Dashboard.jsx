import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, Legend,
} from 'recharts'
import { api } from '../api'

// ── helpers ──────────────────────────────────────────────────────────────────

const PRIORITY_COLOR = { p1: '#f85149', p2: '#f0883e', p3: '#d29922', p4: '#6e7681' }
const STATUS_LABEL = {
  new: 'NEW', triaging: 'TRIAGING',
  l1_running: 'L1 RUN', l1_waiting: 'L1 WAIT', l1_failed: 'L1 FAIL',
  l2_running: 'L2 RUN', l2_waiting: 'L2 WAIT', l2_failed: 'L2 FAIL',
  l3_escalated: 'L3 ESC', resolved: 'RESOLVED', closed: 'CLOSED', false_positive: 'FALSE POS',
}
const STATUS_COLOR = {
  new: '#58a6ff', triaging: '#58a6ff',
  l1_running: '#3fb950', l1_waiting: '#d29922', l1_failed: '#f85149',
  l2_running: '#3fb950', l2_waiting: '#d29922', l2_failed: '#f85149',
  l3_escalated: '#bc8cff', resolved: '#6e7681', closed: '#484f58', false_positive: '#484f58',
}

function fmtAge(iso) {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return '<1m'
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ${m % 60}m`
  return `${Math.floor(h / 24)}d`
}

function SLACountdown({ iso }) {
  const [label, setLabel] = useState('')
  const [color, setColor] = useState('var(--text2)')

  useEffect(() => {
    const update = () => {
      if (!iso) { setLabel('—'); return }
      const diff = new Date(iso).getTime() - Date.now()
      if (diff <= 0) { setLabel('BREACHED'); setColor('var(--red)'); return }
      const m = Math.floor(diff / 60000)
      const h = Math.floor(m / 60)
      const pct = diff / (4 * 3600 * 1000)  // rough gauge
      setColor(pct < 0.2 ? 'var(--red)' : pct < 0.5 ? 'var(--amber)' : 'var(--text2)')
      setLabel(h >= 1 ? `${h}h ${m % 60}m` : `${m}m`)
    }
    update()
    const t = setInterval(update, 30000)
    return () => clearInterval(t)
  }, [iso])

  return <span style={{ color, fontVariantNumeric: 'tabular-nums', fontSize: 12 }}>{label}</span>
}

// ── Stat tile ─────────────────────────────────────────────────────────────────
function Tile({ label, value, sub, color = 'var(--text)', icon }) {
  return (
    <div className="card" style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 6 }}>
        {icon && <span style={{ marginRight: 5 }}>{icon}</span>}{label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums', lineHeight: 1.2 }}>
        {value ?? '—'}
      </div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

// ── Incident row ──────────────────────────────────────────────────────────────
function IncRow({ inc, onClick }) {
  const pc = PRIORITY_COLOR[inc.priority] || '#6e7681'
  const sc = STATUS_COLOR[inc.status] || 'var(--text2)'
  return (
    <tr onClick={() => onClick(inc)}>
      <td>
        <span style={{
          display: 'inline-block', width: 3, height: 16, borderRadius: 2,
          background: pc, marginRight: 8, verticalAlign: 'middle',
        }} />
        <span className="badge" style={{ background: pc + '22', color: pc }}>
          {inc.priority?.toUpperCase()}
        </span>
      </td>
      <td className="mono" style={{ color: 'var(--blue)', fontSize: 12 }}>{inc.number}</td>
      <td className="ellipsis" style={{ maxWidth: 280 }}>{inc.title}</td>
      <td style={{ color: 'var(--text2)', fontSize: 12 }}>{inc.affected_host || '—'}</td>
      <td>
        <span className="badge" style={{ background: sc + '22', color: sc }}>
          {STATUS_LABEL[inc.status] || inc.status}
        </span>
      </td>
      <td><SLACountdown iso={inc.sla_resolve_due} /></td>
      <td style={{ color: 'var(--text3)', fontSize: 12 }}>{fmtAge(inc.created_at)}</td>
    </tr>
  )
}

// ── Agent feed entry ─────────────────────────────────────────────────────────
function FeedEntry({ inc }) {
  const sc = STATUS_COLOR[inc.status] || 'var(--text2)'
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 10,
      padding: '8px 0', borderBottom: '1px solid var(--border)',
      fontSize: 12,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', background: sc,
        marginTop: 5, flexShrink: 0,
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <span className="mono" style={{ color: 'var(--blue)', marginRight: 6 }}>{inc.number}</span>
        <span style={{ color: 'var(--text2)' }}>{inc.affected_host || inc.title}</span>
        <span className="badge" style={{
          marginLeft: 8, background: sc + '22', color: sc, fontSize: 10,
        }}>{STATUS_LABEL[inc.status] || inc.status}</span>
      </div>
      <span style={{ color: 'var(--text3)', flexShrink: 0 }}>{fmtAge(inc.created_at)}</span>
    </div>
  )
}

// ── Main Dashboard ─────────────────────────────────────────────────────────────
export default function Dashboard() {
  const navigate    = useNavigate()
  const [dash,  setDash]  = useState(null)
  const [incs,  setIncs]  = useState([])
  const [hosts, setHosts] = useState([])
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState(null)

  const load = useCallback(async () => {
    try {
      const [d, i, h] = await Promise.all([
        api.dashboard(),
        api.incidents({ limit: 20 }),
        api.metricsSummary(),
      ])
      setDash(d); setIncs(i); setHosts(h)
      setLastRefresh(new Date())
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [load])

  if (loading) return <div className="loading">Loading NOC dashboard…</div>

  const stats = dash?.incidents || {}
  const agent = dash?.agent || {}

  // Incident rate chart — group by hour over last 24h
  const hourMap = {}
  incs.forEach(inc => {
    if (!inc.created_at) return
    const d = new Date(inc.created_at.endsWith('Z') ? inc.created_at : inc.created_at + 'Z')
    const key = `${String(d.getHours()).padStart(2,'0')}:00`
    hourMap[key] = (hourMap[key] || 0) + 1
  })
  const rateData = Object.entries(hourMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([time, count]) => ({ time, count }))

  // Fault category breakdown
  const catMap = {}
  incs.forEach(inc => {
    const c = inc.fault_category || 'unknown'
    catMap[c] = (catMap[c] || 0) + 1
  })
  const catData   = Object.entries(catMap).map(([name, value]) => ({ name, value }))
  const PIE_COLORS = ['#58a6ff','#3fb950','#f0883e','#bc8cff','#f85149','#d29922','#6e7681']

  // Active incidents sorted by priority
  const active = incs
    .filter(i => !['resolved','closed','false_positive'].includes(i.status))
    .sort((a, b) => (a.priority || 'p4').localeCompare(b.priority || 'p4'))
    .slice(0, 12)

  // Feed — most recently updated
  const feed = [...incs].slice(0, 15)

  // Hosts up/down
  const hostsUp   = hosts.filter(h => h.status === 'up').length
  const hostsDown = hosts.filter(h => h.status === 'down').length
  const hostsTotal = hosts.length

  const openP1 = incs.filter(i => i.priority === 'p1' && !['resolved','closed'].includes(i.status)).length

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', overflow:'hidden' }}>

      {/* ── Header ────────────────────────────────────────────────── */}
      <div style={{
        padding: '0 24px',
        borderBottom: '1px solid var(--border)',
        height: 52, display: 'flex', alignItems: 'center',
        background: 'var(--bg2)', flexShrink: 0,
        justifyContent: 'space-between',
      }}>
        <div style={{ display:'flex', alignItems:'center', gap: 12 }}>
          <h1 style={{ fontSize: 16 }}>NOC Overview</h1>
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>
            {lastRefresh ? `Updated ${lastRefresh.toLocaleTimeString('en-GB')}` : ''}
          </span>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap: 8, fontSize: 12 }}>
          <span className="pulse pulse-green" />
          <span style={{ color: 'var(--green)' }}>LIVE — auto-refresh 15s</span>
        </div>
      </div>

      {/* ── Scrollable body ───────────────────────────────────────── */}
      <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>

        {/* ── Stat tiles ─────────────────────────────────────────── */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <Tile label="Open P1s"        value={openP1}               color={openP1 > 0 ? 'var(--red)' : 'var(--green)'} icon="🔴" />
          <Tile label="Active Agents"   value={stats.open ?? '—'}    color="var(--blue)"   icon="⚡" sub={`${agent.ollama_model || ''} running`} />
          <Tile label="SLA Breached"    value={stats.sla_breached}   color={stats.sla_breached > 0 ? 'var(--amber)' : 'var(--green)'} icon="⏱" />
          <Tile label="Hosts Up"        value={hostsTotal > 0 ? `${hostsUp}/${hostsTotal}` : '—'}
                                        color={hostsDown > 0 ? 'var(--amber)' : 'var(--green)'} icon="◈" />
          <Tile label="Resolved Today"  value={stats.resolved_today} color="var(--green)"  icon="✓" />
          <Tile label="Auto-Resolution" value={stats.auto_resolution_rate} color="var(--purple)" icon="⬡" sub="of all incidents" />
        </div>

        {/* ── Charts row ─────────────────────────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 260px', gap: 12, marginBottom: 16 }}>

          {/* Incident rate */}
          <div className="card">
            <h3 style={{ marginBottom: 12 }}>Incident Rate (last 20)</h3>
            {rateData.length > 0 ? (
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={rateData} margin={{ top:0, right:0, left:-20, bottom:0 }}>
                  <XAxis dataKey="time" tick={{ fill:'#484f58', fontSize:10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill:'#484f58', fontSize:10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background:'var(--bg3)', border:'1px solid var(--border2)', borderRadius:6, fontSize:12 }}
                    labelStyle={{ color:'var(--text2)' }} itemStyle={{ color:'var(--blue)' }}
                  />
                  <Bar dataKey="count" fill="#1f6feb" radius={[3,3,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="empty">No incidents yet</div>}
          </div>

          {/* Host metrics sparklines */}
          <div className="card">
            <h3 style={{ marginBottom: 12 }}>Host Health</h3>
            {hosts.length === 0
              ? <div className="empty" style={{ padding: 20 }}>No monitored hosts yet<br/><span style={{fontSize:11}}>Add hosts in the Hosts page</span></div>
              : <div style={{ overflowY: 'auto', maxHeight: 140 }}>
                  {hosts.map(h => (
                    <div key={h.id} style={{
                      display:'flex', alignItems:'center', gap: 10,
                      padding: '6px 0', borderBottom: '1px solid var(--border)',
                      fontSize: 12,
                    }}>
                      <span className={`pulse ${h.status==='up' ? 'pulse-green' : h.status==='down' ? 'pulse-red' : 'pulse-gray'}`} />
                      <span className="ellipsis" style={{ flex: 1 }}>{h.display_name || h.hostname}</span>
                      {h.latest?.cpu_percent != null && (
                        <span style={{ color: h.latest.cpu_percent > 85 ? 'var(--red)' : 'var(--text2)' }}>
                          CPU {h.latest.cpu_percent.toFixed(0)}%
                        </span>
                      )}
                      {h.latest?.ram_percent != null && (
                        <span style={{ color: h.latest.ram_percent > 90 ? 'var(--red)' : 'var(--text2)' }}>
                          RAM {h.latest.ram_percent.toFixed(0)}%
                        </span>
                      )}
                      {h.latest?.ping_ms != null && (
                        <span style={{ color: 'var(--text3)' }}>{h.latest.ping_ms.toFixed(0)}ms</span>
                      )}
                    </div>
                  ))}
                </div>
            }
          </div>

          {/* Fault category donut */}
          <div className="card" style={{ display:'flex', flexDirection:'column' }}>
            <h3 style={{ marginBottom: 8 }}>Fault Types</h3>
            {catData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={120}>
                  <PieChart>
                    <Pie data={catData} cx="50%" cy="50%" innerRadius={30} outerRadius={52}
                         dataKey="value" paddingAngle={2}>
                      {catData.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background:'var(--bg3)', border:'1px solid var(--border2)', borderRadius:6, fontSize:11 }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ fontSize: 10, lineHeight: 1.8 }}>
                  {catData.slice(0,5).map((d, i) => (
                    <div key={d.name} style={{ display:'flex', alignItems:'center', gap: 5 }}>
                      <span style={{ width:8, height:8, borderRadius:'50%', background: PIE_COLORS[i % PIE_COLORS.length], flexShrink:0 }} />
                      <span className="ellipsis" style={{ color:'var(--text2)', flex:1 }}>{d.name}</span>
                      <span style={{ color:'var(--text3)' }}>{d.value}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : <div className="empty" style={{ padding:10, fontSize:12 }}>No data</div>}
          </div>
        </div>

        {/* ── Active incidents + Agent feed ──────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 12 }}>

          {/* Incident table */}
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{
              padding: '12px 16px',
              borderBottom: '1px solid var(--border)',
              display:'flex', alignItems:'center', justifyContent:'space-between',
            }}>
              <h3>Active Incidents</h3>
              <button className="btn-ghost btn-sm" onClick={() => navigate('/incidents')}>View All →</button>
            </div>
            <div style={{ overflowY: 'auto', maxHeight: 340 }}>
              {active.length === 0
                ? <div className="empty">No active incidents</div>
                : <table className="tbl">
                    <thead>
                      <tr>
                        <th>PRI</th><th>INC#</th><th>TITLE</th>
                        <th>HOST</th><th>STATUS</th><th>SLA</th><th>AGE</th>
                      </tr>
                    </thead>
                    <tbody>
                      {active.map(inc => (
                        <IncRow key={inc.id} inc={inc} onClick={() => navigate(`/incidents?id=${inc.id}`)} />
                      ))}
                    </tbody>
                  </table>
              }
            </div>
          </div>

          {/* Agent activity feed */}
          <div className="card" style={{ padding: 0, overflow: 'hidden', display:'flex', flexDirection:'column' }}>
            <div style={{
              padding: '12px 16px',
              borderBottom: '1px solid var(--border)',
              display:'flex', alignItems:'center', gap: 8,
            }}>
              <h3 style={{ flex:1 }}>Agent Activity</h3>
              <span className="pulse pulse-green" style={{ width:6, height:6 }} />
            </div>
            <div style={{ flex:1, overflowY:'auto', padding: '0 16px', maxHeight: 340 }}>
              {feed.length === 0
                ? <div className="empty">No activity yet</div>
                : feed.map(inc => <FeedEntry key={inc.id} inc={inc} />)
              }
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
