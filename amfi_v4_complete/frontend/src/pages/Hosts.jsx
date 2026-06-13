import { useEffect, useState, useCallback } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { api } from '../api'

const DEVICE_TYPES = ['linux','windows','network','generic']
const DEVICE_ICON  = { linux:'🐧', windows:'🪟', network:'🔀', generic:'◈' }

function GaugeBar({ label, value, warn=80, crit=90 }) {
  if (value == null) return null
  const color = value >= crit ? 'var(--red)' : value >= warn ? 'var(--amber)' : 'var(--green)'
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display:'flex', justifyContent:'space-between', fontSize:11, marginBottom:2 }}>
        <span style={{ color:'var(--text3)' }}>{label}</span>
        <span style={{ color, fontWeight:600 }}>{value.toFixed(1)}%</span>
      </div>
      <div style={{ height:4, background:'var(--bg3)', borderRadius:2, overflow:'hidden' }}>
        <div style={{
          height:'100%', width:`${Math.min(100,value)}%`,
          background: color, borderRadius:2, transition:'width .3s',
        }} />
      </div>
    </div>
  )
}

function HostCard({ host, onSelect, onDelete, onPoll }) {
  const up   = host.status === 'up'
  const down = host.status === 'down'
  const lat  = host.latest || {}

  return (
    <div className="card" style={{
      cursor: 'pointer',
      borderColor: down ? 'var(--red-dim)' : up ? 'var(--border)' : 'var(--border)',
      transition: 'border-color .2s, box-shadow .2s',
    }}
      onClick={() => onSelect(host)}
      onMouseEnter={e => e.currentTarget.style.boxShadow='0 0 0 1px var(--blue)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow=''}
    >
      {/* Header */}
      <div style={{ display:'flex', alignItems:'flex-start', gap:8, marginBottom:12 }}>
        <span style={{ fontSize:18 }}>{DEVICE_ICON[host.device_type] || '◈'}</span>
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{ fontWeight:600, fontSize:13 }} className="ellipsis">
            {host.display_name || host.hostname}
          </div>
          <div style={{ fontSize:11, color:'var(--text3)' }} className="ellipsis">{host.ip_address}</div>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:5, flexShrink:0 }}>
          <span className={`pulse ${up ? 'pulse-green' : down ? 'pulse-red' : 'pulse-gray'}`} />
          <span style={{
            fontSize:10, fontWeight:700, color: up ? 'var(--green)' : down ? 'var(--red)' : 'var(--text3)',
          }}>{host.status?.toUpperCase() || 'UNKNOWN'}</span>
        </div>
      </div>

      {/* Metric gauges */}
      {up && (
        <div>
          <GaugeBar label="CPU"  value={lat.cpu_percent}  />
          <GaugeBar label="RAM"  value={lat.ram_percent}  />
          <GaugeBar label="Disk" value={lat.disk_percent} />
        </div>
      )}

      {/* Ping */}
      {lat.ping_ms != null && (
        <div style={{ fontSize:11, color:'var(--text3)', marginTop: up ? 6 : 0 }}>
          Ping {lat.ping_ms.toFixed(1)}ms
          {lat.load_1m != null && ` · Load ${lat.load_1m.toFixed(2)}`}
        </div>
      )}

      {down && (
        <div style={{
          background:'var(--red-dim)', borderRadius:4, padding:'6px 8px',
          fontSize:11, color:'var(--red)', marginTop:8,
        }}>⚠ Host unreachable {host.last_error ? `— ${host.last_error}` : ''}</div>
      )}

      {/* Footer */}
      <div style={{
        display:'flex', gap:6, marginTop:10, paddingTop:10,
        borderTop:'1px solid var(--border)', justifyContent:'space-between',
        alignItems:'center',
      }}>
        <span style={{ fontSize:10, color:'var(--text3)' }}>
          {host.last_polled_at
            ? `Polled ${new Date(host.last_polled_at).toLocaleTimeString('en-GB')}`
            : 'Not polled yet'}
        </span>
        <div style={{ display:'flex', gap:4 }} onClick={e => e.stopPropagation()}>
          <button className="btn-ghost btn-sm" onClick={() => onPoll(host.id)}>↻</button>
          <button className="btn-danger btn-sm" onClick={() => onDelete(host.id)}>✕</button>
        </div>
      </div>
    </div>
  )
}

function MetricsDrawer({ host, onClose }) {
  const [data,  setData]   = useState({})
  const [hours, setHours]  = useState(6)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!host) return
    setLoading(true)
    api.hostMetrics(host.id, { hours })
      .then(setData)
      .finally(() => setLoading(false))
  }, [host?.id, hours])

  const METRIC_CFG = [
    { key:'cpu_percent',  label:'CPU %',        color:'#58a6ff', warn:80 },
    { key:'ram_percent',  label:'RAM %',        color:'#3fb950', warn:85 },
    { key:'disk_percent', label:'Disk %',       color:'#f0883e', warn:80 },
    { key:'load_1m',      label:'Load (1m)',    color:'#bc8cff', warn:null },
    { key:'ping_ms',      label:'Latency (ms)', color:'#d29922', warn:null },
    { key:'net_rx_bps',   label:'Net RX bps',  color:'#58a6ff', warn:null },
    { key:'net_tx_bps',   label:'Net TX bps',  color:'#f85149', warn:null },
  ]

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <div className="drawer" style={{ width:580 }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:20 }}>
          <div>
            <h2>{host.display_name || host.hostname}</h2>
            <div style={{ color:'var(--text3)', fontSize:12, marginTop:2 }}>
              {host.ip_address} · {host.device_type} · {host.environment}
            </div>
          </div>
          <div style={{ display:'flex', gap:8, alignItems:'center' }}>
            <select value={hours} onChange={e => setHours(Number(e.target.value))} style={{ width:100 }}>
              <option value={1}>Last 1h</option>
              <option value={3}>Last 3h</option>
              <option value={6}>Last 6h</option>
              <option value={24}>Last 24h</option>
              <option value={72}>Last 3d</option>
            </select>
            <button className="btn-ghost btn-sm" onClick={onClose}>✕</button>
          </div>
        </div>

        {loading
          ? <div className="loading">Loading metrics…</div>
          : <div>
              {METRIC_CFG.map(({ key, label, color, warn }) => {
                const series = data[key]
                if (!series || series.length === 0) return null
                const pts = series.map(({ t, v }) => ({
                  t: new Date(t).toLocaleTimeString('en-GB', { hour:'2-digit', minute:'2-digit' }),
                  v: Number(v.toFixed(2)),
                }))
                const latest = pts[pts.length - 1]?.v
                return (
                  <div key={key} style={{ marginBottom:20 }}>
                    <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6 }}>
                      <span style={{ fontSize:12, color:'var(--text2)', fontWeight:600 }}>{label}</span>
                      {latest != null && (
                        <span style={{
                          fontSize:12, fontWeight:700,
                          color: warn && latest >= warn ? 'var(--amber)' : color,
                        }}>{latest}{key.includes('percent') ? '%' : key==='ping_ms' ? 'ms' : ''}</span>
                      )}
                    </div>
                    <ResponsiveContainer width="100%" height={80}>
                      <LineChart data={pts} margin={{ top:2, right:0, left:-30, bottom:0 }}>
                        <XAxis dataKey="t" tick={{ fill:'#484f58', fontSize:10 }} axisLine={false} tickLine={false}
                               interval="preserveStartEnd" />
                        <YAxis tick={{ fill:'#484f58', fontSize:10 }} axisLine={false} tickLine={false} />
                        <Tooltip
                          contentStyle={{ background:'var(--bg3)', border:'1px solid var(--border2)', borderRadius:6, fontSize:11 }}
                          labelStyle={{ color:'var(--text2)' }} itemStyle={{ color }}
                        />
                        {warn && <ReferenceLine y={warn} stroke={color} strokeDasharray="3 3" strokeOpacity={.4} />}
                        <Line type="monotone" dataKey="v" stroke={color} dot={false}
                              strokeWidth={1.5} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )
              })}
              {Object.keys(data).length === 0 && (
                <div className="empty">No metrics collected yet — trigger a poll to start</div>
              )}
            </div>
        }
      </div>
    </>
  )
}

export default function Hosts() {
  const [hosts,   setHosts]   = useState([])
  const [summary, setSummary] = useState([])
  const [loading, setLoading] = useState(true)
  const [sel,     setSel]     = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [form,    setForm]    = useState({
    hostname:'', ip_address:'', display_name:'',
    device_type:'linux', environment:'prod',
    ssh_user:'root', ssh_port:22, ssh_key_path:'',
    snmp_community:'public', snmp_port:161,
    poll_interval:60,
  })

  const load = useCallback(async () => {
    try {
      const s = await api.metricsSummary()
      setSummary(s); setHosts(s)
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [load])

  const addHost = async () => {
    await api.createMonitoredHost({
      ...form,
      ssh_port: Number(form.ssh_port),
      snmp_port: Number(form.snmp_port),
      poll_interval: Number(form.poll_interval),
      ssh_key_path: form.ssh_key_path || null,
    })
    setShowAdd(false)
    setForm({ hostname:'', ip_address:'', display_name:'', device_type:'linux', environment:'prod',
              ssh_user:'root', ssh_port:22, ssh_key_path:'', snmp_community:'public', snmp_port:161, poll_interval:60 })
    load()
  }

  const deleteHost = async (id) => {
    if (!confirm('Remove this monitored host?')) return
    await api.deleteMonitoredHost(id)
    load()
  }

  const pollHost = async (id) => {
    await api.pollHost(id)
    setTimeout(load, 5000)
  }

  const up   = hosts.filter(h => h.status === 'up').length
  const down = hosts.filter(h => h.status === 'down').length

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', overflow:'hidden' }}>
      {/* Header */}
      <div style={{
        padding:'0 24px', height:52, display:'flex', alignItems:'center',
        background:'var(--bg2)', borderBottom:'1px solid var(--border)',
        justifyContent:'space-between', flexShrink:0,
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          <h1 style={{ fontSize:16 }}>Monitored Hosts</h1>
          {hosts.length > 0 && (
            <>
              <span className="badge badge-green">{up} UP</span>
              {down > 0 && <span className="badge badge-red">{down} DOWN</span>}
            </>
          )}
        </div>
        <button className="btn-primary btn-sm" onClick={() => setShowAdd(true)}>+ Add Host</button>
      </div>

      {/* Grid */}
      <div style={{ flex:1, overflow:'auto', padding:20 }}>
        {loading
          ? <div className="loading">Loading hosts…</div>
          : hosts.length === 0
            ? <div className="empty">
                <div style={{ fontSize:32, marginBottom:12 }}>◈</div>
                <div>No hosts monitored yet</div>
                <div style={{ fontSize:12, marginTop:6 }}>Add a host to start collecting metrics</div>
                <button className="btn-primary" style={{ marginTop:16 }} onClick={() => setShowAdd(true)}>+ Add First Host</button>
              </div>
            : <div style={{
                display:'grid',
                gridTemplateColumns:'repeat(auto-fill, minmax(280px, 1fr))',
                gap:14,
              }}>
                {hosts.map(h => (
                  <HostCard key={h.id} host={h}
                    onSelect={setSel}
                    onDelete={deleteHost}
                    onPoll={pollHost}
                  />
                ))}
              </div>
        }
      </div>

      {/* Metrics drawer */}
      {sel && <MetricsDrawer host={sel} onClose={() => setSel(null)} />}

      {/* Add host modal */}
      {showAdd && (
        <div className="modal-overlay" onClick={() => setShowAdd(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-title">Add Monitored Host</div>

            <div className="form-grid-2">
              <div className="form-row">
                <label>Hostname *</label>
                <input value={form.hostname} onChange={e => setForm({...form,hostname:e.target.value})} placeholder="core-rtr-01" />
              </div>
              <div className="form-row">
                <label>IP Address *</label>
                <input value={form.ip_address} onChange={e => setForm({...form,ip_address:e.target.value})} placeholder="10.0.0.1" />
              </div>
            </div>

            <div className="form-grid-2">
              <div className="form-row">
                <label>Display Name</label>
                <input value={form.display_name} onChange={e => setForm({...form,display_name:e.target.value})} placeholder="Optional friendly name" />
              </div>
              <div className="form-row">
                <label>Device Type</label>
                <select value={form.device_type} onChange={e => setForm({...form,device_type:e.target.value})}>
                  {DEVICE_TYPES.map(t => <option key={t} value={t}>{DEVICE_ICON[t]} {t}</option>)}
                </select>
              </div>
            </div>

            <div className="form-grid-2">
              <div className="form-row">
                <label>Environment</label>
                <select value={form.environment} onChange={e => setForm({...form,environment:e.target.value})}>
                  <option value="prod">Production</option>
                  <option value="staging">Staging</option>
                  <option value="dev">Development</option>
                </select>
              </div>
              <div className="form-row">
                <label>Poll Interval (seconds)</label>
                <input type="number" value={form.poll_interval} onChange={e => setForm({...form,poll_interval:e.target.value})} min={30} />
              </div>
            </div>

            {(form.device_type === 'linux' || form.device_type === 'windows') && (
              <div className="form-grid-2">
                <div className="form-row">
                  <label>SSH User</label>
                  <input value={form.ssh_user} onChange={e => setForm({...form,ssh_user:e.target.value})} />
                </div>
                <div className="form-row">
                  <label>SSH Port</label>
                  <input type="number" value={form.ssh_port} onChange={e => setForm({...form,ssh_port:e.target.value})} />
                </div>
              </div>
            )}

            {form.device_type === 'linux' || form.device_type === 'windows' ? (
              <div className="form-row">
                <label>SSH Key Path (leave blank to use agent keys)</label>
                <input value={form.ssh_key_path} onChange={e => setForm({...form,ssh_key_path:e.target.value})} placeholder="/home/user/.ssh/id_rsa" />
              </div>
            ) : null}

            {form.device_type === 'network' && (
              <div className="form-grid-2">
                <div className="form-row">
                  <label>SNMP Community</label>
                  <input value={form.snmp_community} onChange={e => setForm({...form,snmp_community:e.target.value})} />
                </div>
                <div className="form-row">
                  <label>SNMP Port</label>
                  <input type="number" value={form.snmp_port} onChange={e => setForm({...form,snmp_port:e.target.value})} />
                </div>
              </div>
            )}

            <div className="modal-footer">
              <button className="btn-ghost" onClick={() => setShowAdd(false)}>Cancel</button>
              <button className="btn-primary" onClick={addHost}
                disabled={!form.hostname.trim() || !form.ip_address.trim()}>
                Add Host
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
