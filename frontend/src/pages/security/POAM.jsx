import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ClipboardList, AlertTriangle, Clock } from 'lucide-react'
import api from '../../api/client'

const RISK_COLOR = {
  critical: 'bg-red-100 text-red-800',
  high: 'bg-orange-100 text-orange-800',
  moderate: 'bg-yellow-100 text-yellow-800',
  low: 'bg-blue-100 text-blue-700',
}

const STATUS_COLOR = {
  open: 'bg-red-100 text-red-700',
  in_progress: 'bg-yellow-100 text-yellow-700',
  completed: 'bg-green-100 text-green-700',
  risk_accepted: 'bg-gray-100 text-gray-600',
}

function POAMRow({ item }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [status, setStatus] = useState(item.status)
  const [plan, setPlan] = useState(item.remediation_plan || '')
  const [dueDate, setDueDate] = useState(item.due_date ? item.due_date.slice(0, 10) : '')

  const update = useMutation({
    mutationFn: (data) => api.patch(`/security/poam/${item.id}`, data).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries(['poam']); setEditing(false) },
  })

  const daysUntilDue = item.due_date
    ? Math.ceil((new Date(item.due_date) - new Date()) / (1000 * 60 * 60 * 24))
    : null

  return (
    <>
      <tr className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer" onClick={() => setEditing(!editing)}>
        <td className="px-4 py-3 font-mono text-xs text-blue-700 font-semibold whitespace-nowrap">
          {item.poam_id}
        </td>
        <td className="px-4 py-3 font-mono text-xs text-gray-600">{item.control_id}</td>
        <td className="px-4 py-3 text-sm text-gray-800 max-w-xs truncate">{item.finding}</td>
        <td className="px-4 py-3">
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${RISK_COLOR[item.risk_level] || 'bg-gray-100 text-gray-600'}`}>
            {item.risk_level}
          </span>
        </td>
        <td className="px-4 py-3">
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLOR[item.status] || 'bg-gray-100 text-gray-600'}`}>
            {item.status?.replace('_', ' ')}
          </span>
        </td>
        <td className="px-4 py-3 text-xs">
          {item.due_date ? (
            <span className={daysUntilDue !== null && daysUntilDue < 0 ? 'text-red-600 font-medium' : daysUntilDue !== null && daysUntilDue <= 30 ? 'text-yellow-600' : 'text-gray-500'}>
              {new Date(item.due_date).toLocaleDateString()}
              {daysUntilDue !== null && daysUntilDue < 0 && ' (overdue)'}
              {daysUntilDue !== null && daysUntilDue >= 0 && daysUntilDue <= 30 && ` (${daysUntilDue}d)`}
            </span>
          ) : '—'}
        </td>
        <td className="px-4 py-3 text-xs text-gray-500">{item.owner_name || '—'}</td>
      </tr>
      {editing && (
        <tr className="bg-blue-50/30">
          <td colSpan={7} className="px-6 py-4">
            <div className="mb-2">
              <p className="text-xs font-semibold text-gray-500 mb-1">WEAKNESS</p>
              <p className="text-sm text-gray-700">{item.weakness || item.finding}</p>
            </div>
            <div className="grid grid-cols-3 gap-4 mb-3">
              <div>
                <label className="text-xs font-semibold text-gray-500 block mb-1">STATUS</label>
                <select value={status} onChange={(e) => setStatus(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm">
                  <option value="open">Open</option>
                  <option value="in_progress">In Progress</option>
                  <option value="completed">Completed</option>
                  <option value="risk_accepted">Risk Accepted</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 block mb-1">DUE DATE</label>
                <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
              </div>
            </div>
            <div className="mb-3">
              <label className="text-xs font-semibold text-gray-500 block mb-1">REMEDIATION PLAN</label>
              <textarea value={plan} onChange={(e) => setPlan(e.target.value)} rows={3}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
            </div>
            <div className="flex gap-2">
              <button onClick={() => update.mutate({ status, remediation_plan: plan, due_date: dueDate || null })}
                disabled={update.isPending}
                className="bg-blue-700 text-white text-xs px-4 py-1.5 rounded-lg hover:bg-blue-800 disabled:opacity-50">
                {update.isPending ? 'Saving...' : 'Save'}
              </button>
              <button onClick={() => setEditing(false)}
                className="border border-gray-300 text-xs px-4 py-1.5 rounded-lg hover:bg-gray-50">Cancel</button>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export default function POAM() {
  const [statusFilter, setStatusFilter] = useState('')
  const [riskFilter, setRiskFilter] = useState('')

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['poam', statusFilter, riskFilter],
    queryFn: () => api.get('/security/poam', {
      params: {
        ...(statusFilter && { status: statusFilter }),
        ...(riskFilter && { risk_level: riskFilter }),
      }
    }).then((r) => r.data),
  })

  const openCount = items.filter((i) => i.status === 'open').length
  const inProgressCount = items.filter((i) => i.status === 'in_progress').length
  const overdueCount = items.filter((i) => {
    if (!i.due_date || i.status === 'completed') return false
    return new Date(i.due_date) < new Date()
  }).length

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <ClipboardList size={22} className="text-blue-700" />
          Plan of Action & Milestones
        </h1>
        <p className="text-sm text-gray-500 mt-1">Open findings and remediation tracking — NIST CA-5</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs text-gray-500 mb-1">Total Items</p>
          <p className="text-2xl font-bold text-gray-900">{items.length}</p>
        </div>
        <div className="bg-white rounded-xl border border-red-200 p-4">
          <p className="text-xs text-red-500 mb-1 flex items-center gap-1"><AlertTriangle size={11} /> Open</p>
          <p className="text-2xl font-bold text-red-600">{openCount}</p>
        </div>
        <div className="bg-white rounded-xl border border-yellow-200 p-4">
          <p className="text-xs text-yellow-600 mb-1">In Progress</p>
          <p className="text-2xl font-bold text-yellow-600">{inProgressCount}</p>
        </div>
        <div className="bg-white rounded-xl border border-red-200 p-4">
          <p className="text-xs text-red-500 mb-1 flex items-center gap-1"><Clock size={11} /> Overdue</p>
          <p className="text-2xl font-bold text-red-700">{overdueCount}</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm">
          <option value="">All Statuses</option>
          <option value="open">Open</option>
          <option value="in_progress">In Progress</option>
          <option value="completed">Completed</option>
          <option value="risk_accepted">Risk Accepted</option>
        </select>
        <select value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm">
          <option value="">All Risk Levels</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="moderate">Moderate</option>
          <option value="low">Low</option>
        </select>
        {(statusFilter || riskFilter) && (
          <button onClick={() => { setStatusFilter(''); setRiskFilter('') }}
            className="text-sm text-blue-600 hover:text-blue-800">Clear</button>
        )}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-32">POA&M ID</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-24">Control</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Finding</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-24">Risk</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-28">Status</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-28">Due Date</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-28">Owner</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
            )}
            {items.map((item) => <POAMRow key={item.id} item={item} />)}
            {!isLoading && items.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">No POA&M items found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
