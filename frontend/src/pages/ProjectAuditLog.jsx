import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Filter, RefreshCw, Shield, Download } from 'lucide-react'
import api from '../api/client'
import { ControlReferenceButton } from '../components/ControlReference'

const ACTION_LABELS = {
  llm_assessed: 'LLM Assessment',
  carried_forward: 'Carried Forward',
  override_not_applicable: 'Marked N/A',
  override_applicable: 'Marked Applicable',
  override_inherited: 'Marked Inherited',
  override_cleared: 'Override Cleared',
  marked_satisfied: 'Marked Satisfied',
  satisfied_removed: 'Satisfied Removed',
  risk_accepted: 'Risk Accepted',
  risk_acceptance_removed: 'Risk Acceptance Removed',
  notes_updated: 'Notes Updated',
  manual_resolved: 'Manually Resolved',
  reviewer_accepted: 'Reviewer Accepted',
  reviewer_override: 'Reviewer Override',
  reviewer_revision: 'Revision Requested',
  retry_queued: 'Retry Queued',
}

const ACTION_COLORS = {
  llm_assessed: 'bg-blue-100 text-blue-800',
  carried_forward: 'bg-gray-100 text-gray-700',
  override_not_applicable: 'bg-orange-100 text-orange-800',
  override_applicable: 'bg-green-100 text-green-800',
  override_inherited: 'bg-indigo-100 text-indigo-800',
  override_cleared: 'bg-gray-100 text-gray-700',
  marked_satisfied: 'bg-green-100 text-green-800',
  satisfied_removed: 'bg-gray-100 text-gray-700',
  risk_accepted: 'bg-amber-100 text-amber-800',
  risk_acceptance_removed: 'bg-gray-100 text-gray-700',
  notes_updated: 'bg-purple-100 text-purple-800',
  manual_resolved: 'bg-blue-100 text-blue-800',
  reviewer_accepted: 'bg-green-100 text-green-800',
  reviewer_override: 'bg-blue-100 text-blue-800',
  reviewer_revision: 'bg-amber-100 text-amber-800',
  retry_queued: 'bg-gray-100 text-gray-700',
}

export default function ProjectAuditLog() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const [filterControl, setFilterControl] = useState('')
  const [filterFamily, setFilterFamily] = useState('')
  const [filterAction, setFilterAction] = useState('')
  const [filterUser, setFilterUser] = useState('')
  const [showFilters, setShowFilters] = useState(false)

  const params = {}
  if (filterControl.trim()) params.control_id = filterControl.trim().toUpperCase()
  if (filterFamily.trim()) params.control_family = filterFamily.trim().toUpperCase()
  if (filterAction) params.action_type = filterAction
  if (filterUser.trim()) params.performed_by = filterUser.trim()
  params.limit = 500

  const { data: entries = [], isLoading, refetch } = useQuery({
    queryKey: ['project-audit-log', projectId, params],
    queryFn: () => api.get(`/projects/${projectId}/activity-log`, { params }).then(r => r.data),
  })

  // Group by date for display
  const grouped = entries.reduce((acc, e) => {
    const date = new Date(e.performed_at).toLocaleDateString('en-US', {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
    })
    if (!acc[date]) acc[date] = []
    acc[date].push(e)
    return acc
  }, {})

  const hasFilters = filterControl || filterFamily || filterAction || filterUser

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate(`/projects/${projectId}`)} className="text-gray-400 hover:text-gray-600">
              <ArrowLeft size={20} />
            </button>
            <Shield size={22} className="text-blue-600" />
            <div>
              <h1 className="text-xl font-bold text-gray-900">Control Activity Audit Trail</h1>
              <p className="text-sm text-gray-500">{entries.length} entries{hasFilters ? ' (filtered)' : ''}</p>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setShowFilters(f => !f)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border ${showFilters || hasFilters ? 'bg-blue-50 border-blue-200 text-blue-700' : 'bg-white border-gray-200 text-gray-600'}`}
            >
              <Filter size={14} />
              Filter{hasFilters ? ` (${[filterControl,filterFamily,filterAction,filterUser].filter(Boolean).length})` : ''}
            </button>
            <button onClick={() => refetch()} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm bg-white border border-gray-200 text-gray-600 hover:bg-gray-50">
              <RefreshCw size={14} />
              Refresh
            </button>
          </div>
        </div>

        {/* Filters */}
        {showFilters && (
          <div className="bg-white border border-gray-200 rounded-xl p-4 mb-6 grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-1">Control ID</label>
              <input
                value={filterControl} onChange={e => setFilterControl(e.target.value)}
                placeholder="e.g. AC-2" className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Family</label>
              <input
                value={filterFamily} onChange={e => setFilterFamily(e.target.value)}
                placeholder="e.g. AC" className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Action Type</label>
              <select value={filterAction} onChange={e => setFilterAction(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm bg-white">
                <option value="">All actions</option>
                {Object.entries(ACTION_LABELS).map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Performed By</label>
              <input
                value={filterUser} onChange={e => setFilterUser(e.target.value)}
                placeholder="username" className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm"
              />
            </div>
            {hasFilters && (
              <div className="col-span-full">
                <button onClick={() => { setFilterControl(''); setFilterFamily(''); setFilterAction(''); setFilterUser('') }}
                  className="text-xs text-blue-600 hover:underline">Clear all filters</button>
              </div>
            )}
          </div>
        )}

        {isLoading ? (
          <div className="text-center py-16 text-gray-400">Loading audit trail...</div>
        ) : entries.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <Shield size={40} className="mx-auto mb-3 opacity-30" />
            <p className="font-medium">No activity recorded yet</p>
            <p className="text-sm mt-1">Actions on controls will appear here as assessments run and assessors make decisions.</p>
          </div>
        ) : (
          <div className="space-y-6">
            {Object.entries(grouped).map(([date, dayEntries]) => (
              <div key={date}>
                <div className="flex items-center gap-3 mb-3">
                  <div className="h-px flex-1 bg-gray-200" />
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">{date}</span>
                  <div className="h-px flex-1 bg-gray-200" />
                </div>
                <div className="bg-white border border-gray-200 rounded-xl overflow-hidden divide-y divide-gray-100">
                  {dayEntries.map(entry => (
                    <div key={entry.id} className="flex gap-4 px-4 py-3 hover:bg-gray-50 transition-colors">
                      {/* Time */}
                      <div className="w-16 shrink-0 text-xs text-gray-400 pt-0.5 tabular-nums">
                        {new Date(entry.performed_at).toLocaleTimeString('en-US', {
                          hour: 'numeric', minute: '2-digit', hour12: true
                        })}
                      </div>
                      {/* Control ID */}
                      <div className="w-16 shrink-0">
                        <div className="flex items-center gap-1">
                          <span className="text-xs font-bold text-blue-700 font-mono">{entry.control_id}</span>
                          <ControlReferenceButton controlId={entry.control_id} iconOnly />
                        </div>
                        <div className="text-xs text-gray-400">{entry.control_family}</div>
                      </div>
                      {/* Action badge */}
                      <div className="w-36 shrink-0">
                        <span className={`inline-block text-xs px-2 py-0.5 rounded-full font-medium ${ACTION_COLORS[entry.action_type] || 'bg-gray-100 text-gray-700'}`}>
                          {ACTION_LABELS[entry.action_type] || entry.action_type}
                        </span>
                      </div>
                      {/* Summary */}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-gray-800 leading-snug">{entry.action_summary}</p>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {entry.control_title}
                          {entry.assessment_id ? ` · Assessment #${entry.assessment_id}` : ''}
                        </p>
                      </div>
                      {/* Performer */}
                      <div className="w-24 shrink-0 text-right">
                        <span className={`text-xs font-medium ${entry.performed_by === 'system' ? 'text-gray-400' : 'text-gray-700'}`}>
                          {entry.performed_by === 'system' ? 'System' : entry.performed_by}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
