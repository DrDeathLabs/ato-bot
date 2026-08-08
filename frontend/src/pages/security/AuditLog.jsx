import { useState, useCallback, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Download, Search, Filter, ChevronDown, ChevronRight,
  RefreshCw, ShieldAlert, X, User, Globe, File, Hash, Terminal
} from 'lucide-react'
import api from '../../api/client'

// ── Severity config ─────────────────────────────────────────────────────────
const SEV = {
  critical: { label: 'CRITICAL', dot: 'bg-red-500',    text: 'text-red-600',    badge: 'bg-red-50 text-red-700 border border-red-200' },
  high:     { label: 'HIGH',     dot: 'bg-orange-500', text: 'text-orange-600', badge: 'bg-orange-50 text-orange-700 border border-orange-200' },
  medium:   { label: 'MEDIUM',   dot: 'bg-yellow-500', text: 'text-yellow-600', badge: 'bg-yellow-50 text-yellow-700 border border-yellow-200' },
  low:      { label: 'LOW',      dot: 'bg-blue-500',   text: 'text-blue-600',   badge: 'bg-blue-50 text-blue-700 border border-blue-200' },
  info:     { label: 'INFO',     dot: 'bg-gray-400',   text: 'text-gray-500',   badge: 'bg-gray-100 text-gray-600 border border-gray-300' },
}

const CAT_BADGE = {
  AUTH:   'bg-purple-50 text-purple-700 border border-purple-200',
  ACCESS: 'bg-cyan-50 text-cyan-700 border border-cyan-200',
  DATA:   'bg-green-50 text-green-700 border border-green-200',
  ADMIN:  'bg-red-50 text-red-700 border border-red-200',
  SYSTEM: 'bg-gray-100 text-gray-600 border border-gray-300',
}

const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info']
const CATEGORIES = ['AUTH', 'ACCESS', 'DATA', 'ADMIN', 'SYSTEM']
const PAGE_SIZES = [25, 50, 100, 200]

// ── Helpers ──────────────────────────────────────────────────────────────────
function fmtTs(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-US', {
    month: '2-digit', day: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  })
}

function StatusCode({ code }) {
  if (!code) return <span className="text-gray-400">—</span>
  const color = code >= 500 ? 'text-red-600' : code >= 400 ? 'text-orange-600' : 'text-green-600'
  return <span className={`font-mono ${color}`}>{code}</span>
}

// ── Sub-components ───────────────────────────────────────────────────────────
function SeverityDot({ sev }) {
  const s = SEV[sev] || SEV.info
  return (
    <div className="flex items-center gap-1.5">
      <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${s.dot}`} />
      <span className={`text-xs font-bold tracking-wide ${s.text}`}>{s.label}</span>
    </div>
  )
}

function CatBadge({ cat }) {
  const cls = CAT_BADGE[cat] || CAT_BADGE.SYSTEM
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold tracking-wider ${cls}`}>
      {cat}
    </span>
  )
}

function MetaBlock({ data }) {
  if (!data) return <span className="text-gray-400 text-xs italic">none</span>
  let display = data
  if (typeof data === 'object') {
    try { display = JSON.stringify(data, null, 2) } catch { display = String(data) }
  } else if (typeof data === 'string') {
    try {
      const parsed = JSON.parse(data)
      display = JSON.stringify(parsed, null, 2)
    } catch { display = data }
  }
  return (
    <pre className="text-xs font-mono text-green-700 bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto whitespace-pre-wrap break-words max-h-32">
      {display}
    </pre>
  )
}

function ExpandedRow({ log }) {
  return (
    <tr className="bg-gray-50 border-b border-gray-200">
      <td colSpan={7} className="px-4 py-4">
        <div className="grid grid-cols-2 gap-x-8 gap-y-4 text-xs max-w-5xl">

          {/* EVENT ID */}
          <div className="col-span-2 flex items-center gap-2 pb-2 border-b border-gray-200">
            <Hash size={12} className="text-gray-400" />
            <span className="text-gray-400 uppercase tracking-wider text-[10px] font-semibold">Event ID</span>
            <span className="font-mono text-gray-700">{log.id}</span>
            <span className="text-gray-300">·</span>
            <span className="text-gray-400 text-[10px]">{log.timestamp}</span>
          </div>

          {/* USER */}
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <User size={12} className="text-blue-500" />
              <span className="text-blue-600 uppercase tracking-wider text-[10px] font-semibold">User</span>
            </div>
            <div className="pl-4 space-y-1">
              <div className="flex gap-2">
                <span className="text-gray-400 w-16">Name</span>
                <span className="text-gray-700">{log.username || '—'}</span>
              </div>
              <div className="flex gap-2">
                <span className="text-gray-400 w-16">Email</span>
                <span className="text-gray-700">{log.email || '—'}</span>
              </div>
              <div className="flex gap-2">
                <span className="text-gray-400 w-16">User ID</span>
                <span className="font-mono text-gray-500">{log.user_id ?? '—'}</span>
              </div>
            </div>
          </div>

          {/* NETWORK */}
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Globe size={12} className="text-cyan-500" />
              <span className="text-cyan-600 uppercase tracking-wider text-[10px] font-semibold">Network</span>
            </div>
            <div className="pl-4 space-y-1">
              <div className="flex gap-2">
                <span className="text-gray-400 w-16">IP</span>
                <span className="font-mono text-gray-700">{log.ip_address || '—'}</span>
              </div>
              <div className="flex gap-2">
                <span className="text-gray-400 w-16">Method</span>
                <span className="font-mono text-blue-600">{log.method || '—'}</span>
              </div>
              <div className="flex gap-2">
                <span className="text-gray-400 w-16">Endpoint</span>
                <span className="font-mono text-gray-500 break-all">{log.endpoint || '—'}</span>
              </div>
            </div>
          </div>

          {/* RESOURCE */}
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <File size={12} className="text-green-500" />
              <span className="text-green-600 uppercase tracking-wider text-[10px] font-semibold">Resource</span>
            </div>
            <div className="pl-4 space-y-1">
              <div className="flex gap-2">
                <span className="text-gray-400 w-16">Type</span>
                <span className="text-gray-700">{log.resource_type || '—'}</span>
              </div>
              <div className="flex gap-2">
                <span className="text-gray-400 w-16">ID</span>
                <span className="font-mono text-gray-500">{log.resource_id ?? '—'}</span>
              </div>
              <div className="flex gap-2">
                <span className="text-gray-400 w-16">Status</span>
                <StatusCode code={log.status_code} />
              </div>
            </div>
          </div>

          {/* USER AGENT */}
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Terminal size={12} className="text-yellow-500" />
              <span className="text-yellow-600 uppercase tracking-wider text-[10px] font-semibold">User Agent</span>
            </div>
            <div className="pl-4">
              <span className="text-gray-500 break-all leading-relaxed">{log.user_agent || '—'}</span>
            </div>
          </div>

          {/* METADATA */}
          <div className="col-span-2">
            <div className="flex items-center gap-1.5 mb-2">
              <Terminal size={12} className="text-orange-500" />
              <span className="text-orange-600 uppercase tracking-wider text-[10px] font-semibold">Metadata / Request Summary</span>
            </div>
            <div className="pl-4">
              <MetaBlock data={log.metadata} />
            </div>
          </div>

        </div>
      </td>
    </tr>
  )
}

function LogRow({ log }) {
  const [expanded, setExpanded] = useState(false)
  const sev = log.severity || 'info'
  const leftBorder =
    sev === 'critical' ? 'border-l-2 border-l-red-500' :
    sev === 'high'     ? 'border-l-2 border-l-orange-500' :
    sev === 'medium'   ? 'border-l-2 border-l-yellow-500' :
    sev === 'low'      ? 'border-l-2 border-l-blue-500' : ''

  return (
    <>
      <tr
        className={`border-b border-gray-100 hover:bg-blue-50/40 cursor-pointer transition-colors ${leftBorder} ${expanded ? 'bg-blue-50/30' : 'bg-white'}`}
        onClick={() => setExpanded(e => !e)}
      >
        <td className="pl-4 pr-1 py-3 w-8">
          {expanded
            ? <ChevronDown size={14} className="text-gray-500" />
            : <ChevronRight size={14} className="text-gray-300" />}
        </td>
        <td className="px-3 py-3 text-xs font-mono text-gray-500 whitespace-nowrap">
          {fmtTs(log.timestamp)}
        </td>
        <td className="px-3 py-3 whitespace-nowrap">
          <SeverityDot sev={sev} />
        </td>
        <td className="px-3 py-3 whitespace-nowrap">
          <CatBadge cat={log.category || 'SYSTEM'} />
        </td>
        <td className="px-3 py-3 text-xs font-mono text-gray-700 max-w-[220px] truncate" title={log.action}>
          {log.action || '—'}
        </td>
        <td className="px-3 py-3 text-xs text-gray-600">
          {log.username
            ? log.username
            : <span className="text-gray-300 italic">anonymous</span>}
        </td>
        <td className="px-3 py-3 text-xs font-mono text-gray-500 whitespace-nowrap">
          {log.ip_address || '—'}
        </td>
      </tr>
      {expanded && <ExpandedRow log={log} />}
    </>
  )
}

function SeverityLegend({ counts, activeSev, onToggle }) {
  return (
    <div className="flex items-center gap-3 px-5 py-2.5 bg-white border-b border-gray-200">
      <span className="text-gray-400 text-[10px] uppercase tracking-wider font-semibold mr-1">Severity</span>
      {SEVERITIES.map(s => {
        const cfg = SEV[s]
        const active = activeSev === s
        return (
          <button
            key={s}
            onClick={() => onToggle(s)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-all ${
              active ? cfg.badge : 'text-gray-400 hover:text-gray-600'
            }`}
          >
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
            {cfg.label}
            <span className="ml-1 font-mono text-[10px] opacity-70">
              {(counts?.[s] ?? 0).toLocaleString()}
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function AuditLog() {
  const [filters, setFilters] = useState({
    severity: '',
    category: '',
    start: '',
    end: '',
    user_id: '',
  })
  const [search, setSearch] = useState('')
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const searchTimeout = useRef(null)

  const buildParams = useCallback((extraOffset = offset) => {
    const p = new URLSearchParams()
    if (filters.severity) p.set('severity', filters.severity)
    if (filters.category) p.set('category', filters.category)
    if (search) p.set('action', search)
    if (filters.start) p.set('start', new Date(filters.start).toISOString())
    if (filters.end)   p.set('end',   new Date(filters.end).toISOString())
    if (filters.user_id) p.set('user_id', filters.user_id)
    p.set('limit', limit)
    p.set('offset', extraOffset)
    return p.toString()
  }, [filters, search, limit, offset])

  const { data, isLoading, isFetching, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['audit-logs', filters, search, limit, offset],
    queryFn: async () => {
      const r = await api.get(`/security/audit-logs?${buildParams()}`)
      return r.data
    },
    refetchInterval: 30000,
    keepPreviousData: true,
  })

  const items = data?.items || []
  const total = data?.total ?? 0
  const totalAll = data?.total_all ?? 0
  const sevCounts = data?.severity_counts || {}
  const totalPages = Math.max(1, Math.ceil(total / limit))
  const currentPage = Math.floor(offset / limit) + 1

  const handleSearch = (val) => {
    setSearch(val)
    clearTimeout(searchTimeout.current)
    searchTimeout.current = setTimeout(() => setOffset(0), 400)
  }

  const setFilter = (key, val) => {
    setFilters(f => ({ ...f, [key]: val }))
    setOffset(0)
  }

  const toggleSeverity = (s) => setFilter('severity', filters.severity === s ? '' : s)

  const clearFilters = () => {
    setFilters({ severity: '', category: '', start: '', end: '', user_id: '' })
    setSearch('')
    setOffset(0)
  }

  const hasFilters = Object.values(filters).some(Boolean) || search

  const handleExport = () => {
    const p = new URLSearchParams()
    if (filters.severity) p.set('severity', filters.severity)
    if (filters.category) p.set('category', filters.category)
    if (search) p.set('action', search)
    if (filters.start) p.set('start', new Date(filters.start).toISOString())
    if (filters.end)   p.set('end',   new Date(filters.end).toISOString())
    window.open(`/api/security/audit-logs/export/csv?${p.toString()}`, '_blank')
  }

  const lastUpdate = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : '—'

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-gray-800 flex items-center gap-2">
              <ShieldAlert size={20} className="text-red-500" />
              SOC Audit Log
            </h1>
            <p className="text-gray-400 text-xs mt-0.5">
              NIST AU-2 · AU-3 · AU-6 · AU-12
              <span className="mx-2 text-gray-200">·</span>
              {totalAll.toLocaleString()} total events
              {hasFilters && <> <span className="text-gray-200 mx-1">·</span> <span className="text-blue-600">{total.toLocaleString()} matching</span></>}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-gray-400 text-xs">Updated {lastUpdate}</span>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white hover:bg-gray-50 text-gray-600 rounded border border-gray-300 transition-colors"
            >
              <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
              Refresh
            </button>
            <button
              onClick={handleExport}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors font-medium"
            >
              <Download size={12} />
              Export CSV
            </button>
          </div>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 flex-shrink-0">
        <div className="flex flex-wrap items-end gap-3">

          {/* Search action */}
          <div className="relative flex-1 min-w-[180px]">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            <input
              type="text"
              placeholder="Search by action…"
              value={search}
              onChange={e => handleSearch(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs bg-white border border-gray-300 rounded text-gray-700 placeholder-gray-400 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400/30"
            />
          </div>

          {/* Category */}
          <div>
            <label className="block text-[10px] text-gray-400 uppercase tracking-wider mb-1">Category</label>
            <select
              value={filters.category}
              onChange={e => setFilter('category', e.target.value)}
              className="text-xs bg-white border border-gray-300 rounded px-2 py-1.5 text-gray-700 focus:outline-none focus:border-blue-400"
            >
              <option value="">All categories</option>
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          {/* From */}
          <div>
            <label className="block text-[10px] text-gray-400 uppercase tracking-wider mb-1">From</label>
            <input
              type="datetime-local"
              value={filters.start}
              onChange={e => setFilter('start', e.target.value)}
              className="text-xs bg-white border border-gray-300 rounded px-2 py-1.5 text-gray-700 focus:outline-none focus:border-blue-400"
            />
          </div>

          {/* To */}
          <div>
            <label className="block text-[10px] text-gray-400 uppercase tracking-wider mb-1">To</label>
            <input
              type="datetime-local"
              value={filters.end}
              onChange={e => setFilter('end', e.target.value)}
              className="text-xs bg-white border border-gray-300 rounded px-2 py-1.5 text-gray-700 focus:outline-none focus:border-blue-400"
            />
          </div>

          {/* User ID */}
          <div>
            <label className="block text-[10px] text-gray-400 uppercase tracking-wider mb-1">User ID</label>
            <input
              type="number"
              placeholder="e.g. 3"
              value={filters.user_id}
              onChange={e => setFilter('user_id', e.target.value)}
              className="w-24 text-xs bg-white border border-gray-300 rounded px-2 py-1.5 text-gray-700 placeholder-gray-400 focus:outline-none focus:border-blue-400"
            />
          </div>

          {hasFilters && (
            <button
              onClick={clearFilters}
              className="flex items-center gap-1 text-xs text-red-500 hover:text-red-600 px-2 py-1.5 border border-red-200 rounded bg-red-50 hover:bg-red-100 transition-colors self-end"
            >
              <X size={11} /> Clear all
            </button>
          )}

          <div className="ml-auto">
            <label className="block text-[10px] text-gray-400 uppercase tracking-wider mb-1">Rows / page</label>
            <select
              value={limit}
              onChange={e => { setLimit(Number(e.target.value)); setOffset(0) }}
              className="text-xs bg-white border border-gray-300 rounded px-2 py-1.5 text-gray-700 focus:outline-none focus:border-blue-400"
            >
              {PAGE_SIZES.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>

        </div>
      </div>

      {/* Severity legend / quick-filter */}
      <SeverityLegend counts={sevCounts} activeSev={filters.severity} onToggle={toggleSeverity} />

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
            Loading audit events…
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-gray-400 gap-2">
            <Filter size={32} className="opacity-30" />
            <p className="text-sm">No events match the current filters</p>
            {hasFilters && (
              <button onClick={clearFilters} className="text-xs text-blue-500 hover:text-blue-600 underline mt-1">
                Clear filters
              </button>
            )}
          </div>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead className="sticky top-0 z-10">
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="w-8 pl-4 py-2.5" />
                {['Timestamp', 'Sev', 'Cat', 'Action', 'User', 'IP Address'].map(h => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] text-gray-400 uppercase tracking-wider font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map(log => (
                <LogRow key={log.id} log={log} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {total > 0 && (
        <div className="bg-white border-t border-gray-200 px-6 py-3 flex items-center justify-between text-xs text-gray-400 flex-shrink-0">
          <span>
            Showing {(offset + 1).toLocaleString()}–{Math.min(offset + limit, total).toLocaleString()} of{' '}
            <span className="text-gray-700">{total.toLocaleString()}</span> events
            {hasFilters && (
              <span className="text-gray-400 ml-1">(from {totalAll.toLocaleString()} total)</span>
            )}
          </span>
          <div className="flex items-center gap-2">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
              className="px-3 py-1 rounded border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors text-gray-600"
            >
              ← Prev
            </button>
            <span className="px-2 font-mono text-gray-500">
              {currentPage} / {totalPages}
            </span>
            <button
              disabled={offset + limit >= total}
              onClick={() => setOffset(offset + limit)}
              className="px-3 py-1 rounded border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors text-gray-600"
            >
              Next →
            </button>
          </div>
        </div>
      )}

    </div>
  )
}
