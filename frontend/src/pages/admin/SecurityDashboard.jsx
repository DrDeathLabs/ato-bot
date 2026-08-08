import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ShieldAlert, ShieldCheck, AlertTriangle, Lock, Users, Activity,
  CheckCircle2, XCircle, AlertCircle, RefreshCw, Database,
  Server, Cpu, ChevronRight, ChevronDown, X, Clock,
  ArrowRight, Info,
} from 'lucide-react'
import api from '../../api/client'

// ── Constants ────────────────────────────────────────────────────────────────
const REFRESH_INTERVAL = 60 // seconds
const STATUS_LABELS = {
  implemented: 'PASS',
  inherited: 'PASS',
  not_applicable: 'PASS',
  partially_implemented: 'WARN',
  planned: 'WARN',
  not_implemented: 'FAIL',
}
const BUCKET_COLORS = {
  pass: { badge: 'bg-green-100 text-green-700 border-green-300', icon: 'text-green-600', dot: 'bg-green-500' },
  warn: { badge: 'bg-yellow-100 text-yellow-700 border-yellow-300', icon: 'text-yellow-500', dot: 'bg-yellow-500' },
  fail: { badge: 'bg-red-100 text-red-700 border-red-300', icon: 'text-red-600', dot: 'bg-red-500' },
}

// ── Fetch ────────────────────────────────────────────────────────────────────
const fetchMetrics = () => api.get('/admin/metrics').then(r => r.data)
const fetchControl = id => api.get(`/admin/controls/${id}`).then(r => r.data)
const fetchData = type => api.get(`/admin/data/${type}`).then(r => r.data)

// ── Countdown hook ────────────────────────────────────────────────────────────
function useCountdown(seconds, onZero) {
  const [remaining, setRemaining] = useState(seconds)
  const ref = useRef(null)
  const reset = useCallback(() => setRemaining(seconds), [seconds])

  useEffect(() => {
    ref.current = setInterval(() => {
      setRemaining(prev => {
        if (prev <= 1) { onZero?.(); return seconds }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(ref.current)
  }, [seconds, onZero])

  return { remaining, reset }
}

// ── Status badge ─────────────────────────────────────────────────────────────
function StatusBadge({ bucket, status }) {
  const c = BUCKET_COLORS[bucket] || BUCKET_COLORS.warn
  const label = STATUS_LABELS[status] || bucket.toUpperCase()
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded border ${c.badge}`}>
      {label}
    </span>
  )
}

function BucketIcon({ bucket, size = 18 }) {
  const c = BUCKET_COLORS[bucket] || BUCKET_COLORS.warn
  if (bucket === 'pass') return <CheckCircle2 size={size} className={c.icon} />
  if (bucket === 'fail') return <XCircle size={size} className={c.icon} />
  return <AlertCircle size={size} className={c.icon} />
}

// ── Component tag chip ────────────────────────────────────────────────────────
function Tag({ label }) {
  return (
    <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 border border-gray-200 rounded">
      {label}
    </span>
  )
}

// ── Severity badge ────────────────────────────────────────────────────────────
function SeverityBadge({ severity }) {
  const map = {
    critical: 'bg-red-100 text-red-700 border-red-300',
    high: 'bg-orange-100 text-orange-700 border-orange-300',
    medium: 'bg-yellow-100 text-yellow-700 border-yellow-300',
    low: 'bg-blue-100 text-blue-700 border-blue-300',
  }
  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded border uppercase ${map[severity] || 'bg-gray-100 text-gray-600 border-gray-200'}`}>
      {severity}
    </span>
  )
}

// ── Control detail drawer ─────────────────────────────────────────────────────
function ControlDrawer({ controlId, onClose }) {
  const { data, isLoading } = useQuery({
    queryKey: ['control-detail', controlId],
    queryFn: () => fetchControl(controlId),
    enabled: !!controlId,
    staleTime: 30000,
  })

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white shadow-2xl flex flex-col h-full overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-gray-200 sticky top-0 bg-white z-10">
          <div className="flex items-center gap-3">
            {data && <BucketIcon bucket={data.bucket} size={20} />}
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-gray-800">{controlId}</span>
                {data && <StatusBadge bucket={data.bucket} status={data.status} />}
              </div>
              {data && <p className="text-sm text-gray-500 mt-0.5">{data.family_name}</p>}
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600">
            <X size={20} />
          </button>
        </div>

        {isLoading && (
          <div className="flex items-center justify-center h-48">
            <RefreshCw size={20} className="animate-spin text-blue-500" />
          </div>
        )}

        {data && (
          <div className="p-5 space-y-5">
            {/* Title */}
            <div>
              <h2 className="text-lg font-semibold text-gray-800">{data.title}</h2>
            </div>

            {/* Implementation statement */}
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2 flex items-center gap-1.5">
                <Info size={12} /> Implementation Statement
              </h3>
              <p className="text-sm text-gray-700 leading-relaxed bg-gray-50 rounded-lg p-3 border border-gray-200">
                {data.description || 'No implementation statement recorded.'}
              </p>
            </div>

            {/* Components */}
            {data.components?.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
                  Components / Evidence Sources
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {data.components.map(c => <Tag key={c} label={c} />)}
                </div>
              </div>
            )}

            {/* Status */}
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
                Control Status
              </h3>
              <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
                <BucketIcon bucket={data.bucket} size={18} />
                <div>
                  <p className="text-sm font-medium text-gray-800 capitalize">
                    {data.status.replace(/_/g, ' ')}
                  </p>
                  {data.last_checked && (
                    <p className="text-xs text-gray-400">
                      Last checked: {new Date(data.last_checked).toLocaleString()}
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Failing — show what needs to be fixed */}
            {data.bucket === 'fail' && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <XCircle size={16} className="text-red-600" />
                  <span className="text-sm font-semibold text-red-700">Remediation Required</span>
                </div>
                <p className="text-xs text-red-600">
                  This control is not implemented. Review the implementation statement above, address the identified gaps, and update the control status when remediated.
                </p>
              </div>
            )}

            {/* Recent security events */}
            {data.recent_events?.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
                  Recent Security Events
                </h3>
                <div className="space-y-2">
                  {data.recent_events.map(ev => (
                    <div key={ev.id} className="flex items-start gap-2 p-2.5 bg-gray-50 rounded border border-gray-200">
                      <SeverityBadge severity={ev.severity} />
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium text-gray-700">{ev.type.replace(/_/g, ' ')}</p>
                        <p className="text-xs text-gray-500 truncate">{ev.description}</p>
                        <p className="text-xs text-gray-400 mt-0.5">{new Date(ev.timestamp).toLocaleString()}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Security alert banner ─────────────────────────────────────────────────────
function AlertBanner({ failing, generatedAt, onOpenControl }) {
  const [expanded, setExpanded] = useState(false)
  if (!failing) return null

  const count = failing.length
  if (count === 0) {
    return (
      <div className="flex items-center gap-3 bg-green-50 border border-green-200 rounded-xl px-5 py-3.5 mb-5">
        <CheckCircle2 size={20} className="text-green-600 shrink-0" />
        <div className="flex-1">
          <p className="text-sm font-semibold text-green-700">All controls passing</p>
          <p className="text-xs text-green-600">No remediation required.</p>
        </div>
        {generatedAt && (
          <p className="text-xs text-gray-400 shrink-0">
            Last assessed {new Date(generatedAt).toLocaleString()}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="bg-red-50 border border-red-300 rounded-xl mb-5 overflow-hidden">
      <button
        className="w-full flex items-center gap-3 px-5 py-3.5 text-left hover:bg-red-100/50 transition-colors"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center justify-center w-9 h-9 bg-red-100 border border-red-300 rounded-lg shrink-0">
          <ShieldAlert size={18} className="text-red-600" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-bold text-red-700">SECURITY ALERT</p>
          <p className="text-xs text-red-600">
            {count} control{count > 1 ? 's' : ''} failing · Click to {expanded ? 'collapse' : 'expand all issues'}
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {generatedAt && (
            <div className="text-right">
              <p className="text-xs text-gray-500">Last assessed</p>
              <p className="text-xs text-gray-600">{new Date(generatedAt).toLocaleString()}</p>
            </div>
          )}
          {expanded ? <ChevronDown size={16} className="text-red-500" /> : <ChevronRight size={16} className="text-red-500" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-red-200 px-5 py-3 space-y-1">
          <p className="text-xs text-gray-500 mb-2">DB metrics — live on refresh · Infra probes — live on refresh · {failing.length} controls failing</p>
          {failing.map(c => (
            <button
              key={c.id}
              onClick={() => onOpenControl(c.id)}
              className="w-full flex items-center gap-3 p-2.5 bg-white border border-red-200 rounded-lg hover:bg-red-50 transition-colors text-left"
            >
              <XCircle size={16} className="text-red-600 shrink-0" />
              <span className="font-mono text-xs font-bold text-gray-700 w-12 shrink-0">{c.id}</span>
              <span className="text-xs text-gray-700 flex-1">{c.title}</span>
              <ArrowRight size={14} className="text-gray-400 shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Data drill-down drawer ────────────────────────────────────────────────────
function DataDrawer({ dataType, onClose }) {
  const { data, isLoading } = useQuery({
    queryKey: ['admin-data', dataType],
    queryFn: () => fetchData(dataType),
    enabled: !!dataType,
    staleTime: 30000,
  })

  const formatCell = (col, val) => {
    if (val === null || val === undefined) return <span className="text-gray-300">—</span>
    if (col === 'mfa_enabled') return val
      ? <span className="text-xs font-medium text-green-700 bg-green-100 px-1.5 py-0.5 rounded">Enabled</span>
      : <span className="text-xs font-medium text-red-600 bg-red-50 px-1.5 py-0.5 rounded">Disabled</span>
    if (col === 'status_code') return (
      <span className={`text-xs font-mono font-bold ${val >= 400 ? 'text-red-600' : 'text-green-600'}`}>{val}</span>
    )
    if (col === 'last_seen' || col === 'last_login' || col === 'locked_until' || col === 'timestamp')
      return <span className="text-xs text-gray-600">{new Date(val).toLocaleString()}</span>
    if (col === 'role') return <span className="text-xs font-mono text-blue-700">{val}</span>
    if (col === 'action_count') return <span className="font-medium">{val}</span>
    return <span>{String(val)}</span>
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-2xl bg-white shadow-2xl flex flex-col h-full">
        <div className="flex items-center justify-between p-5 border-b border-gray-200 sticky top-0 bg-white z-10">
          <h2 className="text-base font-semibold text-gray-800">{data?.title || 'Loading…'}</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600">
            <X size={20} />
          </button>
        </div>

        {isLoading && (
          <div className="flex items-center justify-center h-48">
            <RefreshCw size={20} className="animate-spin text-blue-500" />
          </div>
        )}

        {data && (
          <div className="flex-1 overflow-auto">
            {data.rows.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-gray-400">
                <CheckCircle2 size={32} className="text-green-400 mb-2" />
                <p className="text-sm">No records found</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200 sticky top-0">
                  <tr>
                    {Object.keys(data.rows[0]).map(col => (
                      <th key={col} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                        {col.replace(/_/g, ' ')}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.rows.map((row, i) => (
                    <tr key={i} className="hover:bg-gray-50 transition-colors">
                      {Object.entries(row).map(([col, val]) => (
                        <td key={col} className="px-4 py-2.5 text-gray-700 whitespace-nowrap">
                          {formatCell(col, val)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {data && (
          <div className="p-3 border-t border-gray-100 bg-gray-50 text-xs text-gray-400 text-right">
            {data.rows.length} record{data.rows.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Stat card ─────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, icon: Icon, color, controlId, onOpenControl, dataType, onOpenData }) {
  const colors = {
    red:    'border-red-200 bg-white hover:border-red-300',
    yellow: 'border-yellow-200 bg-white hover:border-yellow-300',
    green:  'border-green-200 bg-white hover:border-green-300',
    blue:   'border-blue-200 bg-white hover:border-blue-300',
    gray:   'border-gray-200 bg-white hover:border-gray-300',
  }
  const iconColors = {
    red: 'text-red-500', yellow: 'text-yellow-500',
    green: 'text-green-500', blue: 'text-blue-500', gray: 'text-gray-400',
  }
  const valueColors = {
    red: 'text-red-600', yellow: 'text-yellow-600',
    green: 'text-gray-800', blue: 'text-gray-800', gray: 'text-gray-800',
  }
  return (
    <button
      onClick={() => dataType && onOpenData(dataType)}
      className={`rounded-xl border p-5 text-left w-full transition-all ${colors[color]} ${dataType ? 'cursor-pointer' : 'cursor-default'}`}
    >
      <div className="flex items-start justify-between mb-3">
        <Icon size={20} className={iconColors[color]} />
        <div className="flex items-center gap-2">
          {controlId && (
            <button
              onClick={e => { e.stopPropagation(); onOpenControl(controlId) }}
              className="text-xs font-mono text-blue-600 hover:text-blue-800 flex items-center gap-0.5 hover:underline"
            >
              {controlId} <ChevronRight size={12} />
            </button>
          )}
          {dataType && <ChevronRight size={14} className="text-gray-300" />}
        </div>
      </div>
      <p className={`text-3xl font-bold ${valueColors[color]}`}>{value}</p>
      <p className="text-sm text-gray-500 mt-1">{label}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </button>
  )
}

// ── Infrastructure row ────────────────────────────────────────────────────────
function InfraRow({ name, icon: Icon, health, onOpenControl }) {
  if (!health) return null
  const ok = health.status === 'healthy'
  const unknown = health.status === 'unknown'
  const dot = ok ? 'bg-green-500' : unknown ? 'bg-gray-400' : 'bg-red-500'
  const badge = ok
    ? 'bg-green-100 text-green-700 border-green-200'
    : unknown
    ? 'bg-gray-100 text-gray-600 border-gray-200'
    : 'bg-red-100 text-red-700 border-red-200'

  return (
    <div className="flex items-center gap-3 py-3.5 border-b border-gray-100 last:border-0">
      <Icon size={18} className="text-gray-400 shrink-0" />
      <div className="flex items-center gap-2 w-28 shrink-0">
        <span className="text-sm font-medium text-gray-700">{name}</span>
        <span className={`text-xs px-1.5 py-0.5 rounded border font-medium flex items-center gap-1 ${badge}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
          {health.status === 'healthy' ? 'Healthy' : health.status === 'unknown' ? 'Unknown' : 'Degraded'}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-gray-600 truncate">{health.detail}</p>
      </div>
      {health.nist_control && (
        <button
          onClick={() => onOpenControl(health.nist_control)}
          className="text-xs font-mono text-blue-600 hover:text-blue-800 flex items-center gap-0.5 hover:underline shrink-0"
        >
          {health.nist_control} <ChevronRight size={12} />
        </button>
      )}
    </div>
  )
}

// ── Control row ───────────────────────────────────────────────────────────────
function ControlRow({ control, onClick }) {
  return (
    <button
      className="w-full flex items-start gap-3 py-3 px-1 border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors text-left group"
      onClick={() => onClick(control.id)}
    >
      <div className="shrink-0 mt-0.5">
        <BucketIcon bucket={control.bucket} size={18} />
      </div>
      <div className="flex items-start gap-2 w-28 shrink-0">
        <span className="font-mono text-sm font-bold text-gray-700">{control.id}</span>
        <StatusBadge bucket={control.bucket} status={control.status} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-700">{control.title}</p>
        {control.description && (
          <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{control.description}</p>
        )}
        {control.components?.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {control.components.map(c => <Tag key={c} label={c} />)}
          </div>
        )}
      </div>
      <ChevronRight size={16} className="text-gray-300 group-hover:text-gray-500 shrink-0 mt-1 transition-colors" />
    </button>
  )
}

// ── Control family section ────────────────────────────────────────────────────
function FamilySection({ family, data, onOpenControl }) {
  const [open, setOpen] = useState(true)
  const hasFailures = data.fail > 0

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-3">
      <button
        className="w-full flex items-center gap-3 px-4 py-3 bg-gray-50 border-b border-gray-200 hover:bg-gray-100 transition-colors text-left"
        onClick={() => setOpen(o => !o)}
      >
        <span className="text-xs font-mono font-bold text-gray-500 w-8">{family}</span>
        <span className="text-sm font-semibold text-gray-700 flex-1">{data.name}</span>
        <div className="flex items-center gap-2">
          {data.pass > 0 && <span className="text-xs text-green-600 font-medium">{data.pass} Pass</span>}
          {data.warn > 0 && <span className="text-xs text-yellow-600 font-medium">{data.warn} Warn</span>}
          {data.fail > 0 && <span className="text-xs text-red-600 font-bold">{data.fail} Fail</span>}
          {open ? <ChevronDown size={14} className="text-gray-400" /> : <ChevronRight size={14} className="text-gray-400" />}
        </div>
      </button>
      {open && (
        <div className="px-4">
          {data.controls.map(c => (
            <ControlRow key={c.id} control={c} onClick={onOpenControl} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main dashboard ────────────────────────────────────────────────────────────
export default function SecurityDashboard() {
  const [selectedControl, setSelectedControl] = useState(null)
  const [selectedData, setSelectedData] = useState(null)

  const { data, isLoading, isError, dataUpdatedAt, refetch, isFetching } = useQuery({
    queryKey: ['admin-metrics'],
    queryFn: fetchMetrics,
    refetchInterval: REFRESH_INTERVAL * 1000,
    staleTime: (REFRESH_INTERVAL - 5) * 1000,
  })

  const { remaining, reset } = useCountdown(REFRESH_INTERVAL, () => {})

  // Reset countdown when data refreshes
  useEffect(() => { if (dataUpdatedAt) reset() }, [dataUpdatedAt, reset])

  const handleRefresh = () => { refetch(); reset() }
  const openControl = id => { setSelectedControl(id); setSelectedData(null) }
  const closeControl = () => setSelectedControl(null)
  const openData = type => { setSelectedData(type); setSelectedControl(null) }
  const closeData = () => setSelectedData(null)

  const metrics = data?.metrics
  const controls = data?.controls
  const infra = data?.infrastructure
  const events = data?.security_events

  const mfaColor = !metrics ? 'gray'
    : metrics.mfa_adoption_pct >= 80 ? 'green'
    : metrics.mfa_adoption_pct >= 50 ? 'yellow'
    : 'red'

  const failedColor = !metrics ? 'gray'
    : metrics.failed_logins_24h > 10 ? 'red'
    : metrics.failed_logins_24h > 0 ? 'yellow'
    : 'green'

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-6 py-6">
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-800 flex items-center gap-2">
              <ShieldCheck size={24} className="text-blue-600" />
              Security Dashboard
            </h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Security posture monitoring · SOC audit log · NIST SP 800-53 Rev 5 · cATO
            </p>
          </div>
          <div className="flex items-center gap-3 mt-1">
            {dataUpdatedAt && (
              <span className="text-xs text-gray-400 flex items-center gap-1">
                <Clock size={12} />
                {new Date(dataUpdatedAt).toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={handleRefresh}
              disabled={isFetching}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-white border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>
        </div>

        {isLoading && (
          <div className="flex items-center justify-center h-64">
            <RefreshCw size={24} className="animate-spin text-blue-500" />
            <span className="ml-3 text-gray-500">Loading metrics…</span>
          </div>
        )}

        {isError && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-8 text-center">
            <XCircle size={32} className="text-red-400 mx-auto mb-2" />
            <p className="text-red-700 font-semibold">Failed to load metrics</p>
            <p className="text-gray-500 text-sm mt-1">Ensure you are signed in as system_admin.</p>
            <button onClick={handleRefresh} className="mt-3 text-sm text-blue-600 hover:underline">Try again</button>
          </div>
        )}

        {data && (
          <>
            {/* Alert banner */}
            <AlertBanner
              failing={controls?.failing || []}
              generatedAt={data.generated_at}
              onOpenControl={openControl}
            />

            {/* Stat cards */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              <StatCard
                label="Failed Logins (24h)"
                value={metrics.failed_logins_24h}
                icon={ShieldAlert}
                color={failedColor}
                controlId={metrics.control_links?.failed_logins}
                onOpenControl={openControl}
                dataType="failed-logins"
                onOpenData={openData}
              />
              <StatCard
                label="Locked Accounts"
                value={metrics.locked_accounts}
                icon={Lock}
                color={metrics.locked_accounts > 0 ? 'red' : 'green'}
                controlId={metrics.control_links?.locked_accounts}
                onOpenControl={openControl}
                dataType="locked-accounts"
                onOpenData={openData}
              />
              <StatCard
                label="MFA Adoption"
                value={`${metrics.mfa_adoption_pct}%`}
                sub={`${metrics.mfa_enabled}/${metrics.total_active_users} users`}
                icon={Users}
                color={mfaColor}
                controlId={metrics.control_links?.mfa_adoption}
                onOpenControl={openControl}
                dataType="mfa-status"
                onOpenData={openData}
              />
              <StatCard
                label="Active Users (24h)"
                value={metrics.active_users_24h}
                icon={Activity}
                color="blue"
                controlId={null}
                onOpenControl={openControl}
                dataType="active-users"
                onOpenData={openData}
              />
            </div>

            {/* Infrastructure */}
            <div className="bg-white border border-gray-200 rounded-xl px-5 py-1 mb-4">
              <InfraRow name="PostgreSQL" icon={Database} health={infra?.postgres} onOpenControl={openControl} />
              <InfraRow name="Redis" icon={Cpu} health={infra?.redis} onOpenControl={openControl} />
              <InfraRow name="Nginx" icon={Server} health={infra?.nginx} onOpenControl={openControl} />
            </div>

            {/* Controls summary + countdown */}
            <div className="flex items-center gap-4 bg-white border border-gray-200 rounded-xl px-5 py-3 mb-5">
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Controls</span>
              <div className="flex items-center gap-1.5 text-sm">
                <CheckCircle2 size={14} className="text-green-600" />
                <span className="font-bold text-gray-700">{controls?.summary?.pass || 0}</span>
                <span className="text-gray-400">Pass</span>
              </div>
              <div className="flex items-center gap-1.5 text-sm">
                <AlertCircle size={14} className="text-yellow-500" />
                <span className="font-bold text-gray-700">{controls?.summary?.warn || 0}</span>
                <span className="text-gray-400">Warn</span>
              </div>
              <div className="flex items-center gap-1.5 text-sm">
                <XCircle size={14} className="text-red-600" />
                <span className="font-bold text-gray-700">{controls?.summary?.fail || 0}</span>
                <span className="text-gray-400">Fail</span>
              </div>
              <div className="flex-1" />
              <div className="flex items-center gap-2">
                <div className="relative w-8 h-8">
                  <svg className="w-8 h-8 -rotate-90" viewBox="0 0 32 32">
                    <circle cx="16" cy="16" r="13" fill="none" stroke="#e5e7eb" strokeWidth="3" />
                    <circle
                      cx="16" cy="16" r="13" fill="none" stroke="#3b82f6" strokeWidth="3"
                      strokeDasharray={`${2 * Math.PI * 13}`}
                      strokeDashoffset={`${2 * Math.PI * 13 * (1 - remaining / REFRESH_INTERVAL)}`}
                      strokeLinecap="round"
                    />
                  </svg>
                  <span className="absolute inset-0 flex items-center justify-center text-[9px] font-bold text-blue-600">
                    {remaining}
                  </span>
                </div>
                <div className="text-right">
                  <p className="text-xs text-gray-600 font-medium">Next refresh in {remaining}s</p>
                  <p className="text-xs text-gray-400">Auto every {REFRESH_INTERVAL}s</p>
                </div>
              </div>
            </div>

            {/* NIST Control Matrix */}
            <div className="mb-2">
              <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3">
                NIST SP 800-53 Rev 5 — Control Matrix
              </h2>
              {Object.entries(controls?.families || {})
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([fam, d]) => (
                  <FamilySection key={fam} family={fam} data={d} onOpenControl={openControl} />
                ))}
            </div>

            {/* Recent security events */}
            {events?.recent?.length > 0 && (
              <div className="bg-white border border-gray-200 rounded-xl p-5 mt-4">
                <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3 flex items-center gap-2">
                  <AlertTriangle size={13} className="text-orange-500" />
                  Recent Security Events
                </h2>
                <div className="space-y-2">
                  {events.recent.map(ev => (
                    <div key={ev.id} className="flex items-start gap-3 p-3 bg-gray-50 border border-gray-200 rounded-lg">
                      <SeverityBadge severity={ev.severity} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-semibold text-gray-700">{ev.type.replace(/_/g, ' ')}</p>
                        <p className="text-xs text-gray-500 truncate">{ev.description}</p>
                      </div>
                      <p className="text-xs text-gray-400 shrink-0">{new Date(ev.created_at).toLocaleString()}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Control detail drawer */}
      {selectedControl && (
        <ControlDrawer controlId={selectedControl} onClose={closeControl} />
      )}

      {/* Stat data drawer */}
      {selectedData && (
        <DataDrawer dataType={selectedData} onClose={closeData} />
      )}
    </div>
  )
}
