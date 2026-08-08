import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, AlertOctagon, Info, CheckCircle } from 'lucide-react'
import api from '../../api/client'

const SEV_CFG = {
  critical: { color: 'bg-red-100 text-red-800', icon: AlertOctagon, iconColor: 'text-red-600' },
  high: { color: 'bg-orange-100 text-orange-800', icon: AlertTriangle, iconColor: 'text-orange-500' },
  medium: { color: 'bg-yellow-100 text-yellow-800', icon: AlertTriangle, iconColor: 'text-yellow-500' },
  low: { color: 'bg-blue-100 text-blue-700', icon: Info, iconColor: 'text-blue-500' },
  info: { color: 'bg-gray-100 text-gray-600', icon: Info, iconColor: 'text-gray-400' },
}

export default function SecurityEvents() {
  const qc = useQueryClient()
  const [sevFilter, setSevFilter] = useState('')
  const [resolvedFilter, setResolvedFilter] = useState('open')
  const [page, setPage] = useState(1)
  const limit = 50

  const { data, isLoading } = useQuery({
    queryKey: ['security-events', page, sevFilter, resolvedFilter],
    queryFn: () => api.get('/security/events', {
      params: {
        skip: (page - 1) * limit,
        limit,
        ...(sevFilter && { severity: sevFilter }),
        ...(resolvedFilter === 'open' && { resolved: false }),
        ...(resolvedFilter === 'resolved' && { resolved: true }),
      }
    }).then((r) => r.data),
    refetchInterval: 15000,
  })

  const events = data?.items || []
  const total = data?.total || 0
  const pages = Math.ceil(total / limit)

  const resolve = useMutation({
    mutationFn: (id) => api.patch(`/security/events/${id}`, { resolved: true }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries(['security-events']),
  })

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Security Events</h1>
          <p className="text-sm text-gray-500 mt-1">Real-time security event feed — NIST IR-6 / SI-4</p>
        </div>
        <span className="text-xs text-gray-400">Auto-refreshes every 15s</span>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select value={sevFilter} onChange={(e) => { setSevFilter(e.target.value); setPage(1) }}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm">
          <option value="">All Severities</option>
          {['critical', 'high', 'medium', 'low', 'info'].map((s) => (
            <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
          {[['open', 'Open'], ['resolved', 'Resolved'], ['', 'All']].map(([v, l]) => (
            <button key={v} onClick={() => { setResolvedFilter(v); setPage(1) }}
              className={`px-3 py-1.5 ${resolvedFilter === v ? 'bg-blue-700 text-white' : 'hover:bg-gray-50 text-gray-600'}`}>
              {l}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-40">Timestamp</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-24">Severity</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-36">Type</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Description</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-28">User / IP</th>
              <th className="w-24"></th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
            )}
            {events.map((ev) => {
              const cfg = SEV_CFG[ev.severity] || SEV_CFG.info
              const Icon = cfg.icon
              return (
                <tr key={ev.id} className={`border-b border-gray-50 ${ev.resolved ? 'opacity-50' : ''} hover:bg-gray-50`}>
                  <td className="px-4 py-2.5 text-xs text-gray-400 font-mono">
                    {new Date(ev.timestamp).toISOString().replace('T', ' ').slice(0, 19)}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${cfg.color}`}>
                      <Icon size={10} />
                      {ev.severity}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-600 font-mono">{ev.event_type}</td>
                  <td className="px-4 py-2.5 text-sm text-gray-700">{ev.description}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-400">
                    {ev.username && <div>{ev.username}</div>}
                    {ev.source_ip && <div className="font-mono">{ev.source_ip}</div>}
                  </td>
                  <td className="px-4 py-2.5">
                    {ev.resolved ? (
                      <span className="text-xs text-green-600 flex items-center gap-1">
                        <CheckCircle size={12} /> Resolved
                      </span>
                    ) : (
                      <button onClick={() => resolve.mutate(ev.id)}
                        className="text-xs text-blue-600 hover:text-blue-800">
                        Resolve
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
            {!isLoading && events.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No events found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-gray-500">{total} total events</p>
          <div className="flex gap-2">
            <button disabled={page === 1} onClick={() => setPage(page - 1)}
              className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50">
              Previous
            </button>
            <button disabled={page === pages} onClick={() => setPage(page + 1)}
              className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50">
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
