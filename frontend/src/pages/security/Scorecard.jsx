import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Shield, CheckCircle, AlertTriangle, XCircle, MinusCircle, RefreshCw } from 'lucide-react'
import api from '../../api/client'

const STATUS_CFG = {
  implemented: { label: 'Implemented', color: 'bg-green-100 text-green-800', icon: CheckCircle, iconColor: 'text-green-500' },
  partial: { label: 'Partial', color: 'bg-yellow-100 text-yellow-800', icon: AlertTriangle, iconColor: 'text-yellow-500' },
  not_implemented: { label: 'Not Implemented', color: 'bg-red-100 text-red-800', icon: XCircle, iconColor: 'text-red-500' },
  inherited: { label: 'Inherited', color: 'bg-blue-100 text-blue-800', icon: Shield, iconColor: 'text-blue-500' },
  not_applicable: { label: 'N/A', color: 'bg-gray-100 text-gray-500', icon: MinusCircle, iconColor: 'text-gray-400' },
}

function ControlRow({ ctrl }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState(ctrl.evidence_text || '')
  const [status, setStatus] = useState(ctrl.status)

  const cfg = STATUS_CFG[ctrl.status] || STATUS_CFG.not_implemented
  const Icon = cfg.icon

  const update = useMutation({
    mutationFn: (data) => api.patch(`/security/scorecard/controls/${ctrl.control_id}`, data).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries(['scorecard-controls']); qc.invalidateQueries(['scorecard-summary']); setEditing(false) },
  })

  return (
    <>
      <tr className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer" onClick={() => setEditing(!editing)}>
        <td className="px-4 py-2.5 font-mono text-xs text-blue-700 font-semibold">{ctrl.control_id}</td>
        <td className="px-4 py-2.5 text-sm text-gray-800">{ctrl.title}</td>
        <td className="px-4 py-2.5">
          <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${cfg.color}`}>
            <Icon size={11} />
            {cfg.label}
          </span>
        </td>
        <td className="px-4 py-2.5 text-xs text-gray-400">
          {ctrl.auto_collected ? (
            <span className="text-blue-500">Auto</span>
          ) : (
            <span>Manual</span>
          )}
        </td>
        <td className="px-4 py-2.5 text-xs text-gray-400">
          {ctrl.last_checked ? new Date(ctrl.last_checked).toLocaleDateString() : '—'}
        </td>
      </tr>
      {editing && (
        <tr className="bg-blue-50/30">
          <td colSpan={5} className="px-6 py-4">
            <div className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-gray-500 block mb-1">STATUS</label>
                <select value={status} onChange={(e) => setStatus(e.target.value)}
                  className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm">
                  {Object.keys(STATUS_CFG).map((s) => <option key={s} value={s}>{STATUS_CFG[s].label}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 block mb-1">EVIDENCE / NOTES</label>
                <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
              </div>
              <div className="flex gap-2">
                <button onClick={() => update.mutate({ status, evidence_text: note })}
                  disabled={update.isPending}
                  className="bg-blue-700 text-white text-xs px-4 py-1.5 rounded-lg hover:bg-blue-800 disabled:opacity-50">
                  {update.isPending ? 'Saving...' : 'Save'}
                </button>
                <button onClick={() => setEditing(false)}
                  className="border border-gray-300 text-xs px-4 py-1.5 rounded-lg hover:bg-gray-50">Cancel</button>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export default function Scorecard() {
  const [familyFilter, setFamilyFilter] = useState('')

  const { data: summary } = useQuery({
    queryKey: ['scorecard-summary'],
    queryFn: () => api.get('/security/scorecard/summary').then((r) => r.data),
    refetchInterval: 30000,
  })

  const { data: controls = [], isLoading } = useQuery({
    queryKey: ['scorecard-controls', familyFilter],
    queryFn: () => api.get('/security/scorecard/controls', {
      params: familyFilter ? { family: familyFilter } : {}
    }).then((r) => r.data),
  })

  const families = [...new Set(controls.map((c) => c.control_id.split('-')[0]))].sort()

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Shield size={22} className="text-blue-700" />
            Internal Security Scorecard
          </h1>
          <p className="text-sm text-gray-500 mt-1">ATO Bot own compliance posture — NIST 800-53 Moderate</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <RefreshCw size={12} /> Auto-refreshes every 30s
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-5 gap-3 mb-6">
          {[
            { key: 'compliance_score_pct', label: 'Score', suffix: '%', color: 'text-blue-700' },
            { key: 'implemented', label: 'Implemented', color: 'text-green-600' },
            { key: 'partial', label: 'Partial', color: 'text-yellow-600' },
            { key: 'not_implemented', label: 'Not Implemented', color: 'text-red-600' },
            { key: 'open_poams', label: 'Open POA&Ms', color: 'text-orange-600' },
          ].map(({ key, label, suffix, color }) => (
            <div key={key} className="bg-white rounded-xl border border-gray-200 p-4">
              <p className="text-xs text-gray-500 mb-1">{label}</p>
              <p className={`text-2xl font-bold ${color}`}>
                {summary[key]}{suffix || ''}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Progress bar */}
      {summary && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 mb-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Compliance Progress</span>
            <span className="text-sm font-bold text-gray-900">{summary.compliance_score_pct}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-4 overflow-hidden">
            <div
              className="h-4 rounded-full transition-all"
              style={{
                width: `${summary.compliance_score_pct}%`,
                background: summary.compliance_score_pct >= 80 ? '#22c55e' : summary.compliance_score_pct >= 60 ? '#eab308' : '#ef4444',
              }}
            />
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select value={familyFilter} onChange={(e) => setFamilyFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm">
          <option value="">All Families</option>
          {families.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        {familyFilter && (
          <button onClick={() => setFamilyFilter('')} className="text-sm text-blue-600 hover:text-blue-800">
            Clear
          </button>
        )}
      </div>

      {/* Controls table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-24">Control</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Title</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-36">Status</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-20">Source</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-28">Last Checked</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">Loading controls...</td></tr>
            )}
            {controls.map((c) => <ControlRow key={c.control_id} ctrl={c} />)}
          </tbody>
        </table>
      </div>
    </div>
  )
}
