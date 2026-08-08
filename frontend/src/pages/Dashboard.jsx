import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FolderOpen, ShieldCheck, AlertTriangle, Clock, TrendingUp } from 'lucide-react'
import api from '../api/client'

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-center gap-4">
      <div className={`p-3 rounded-lg ${color}`}>
        <Icon size={20} className="text-white" />
      </div>
      <div>
        <p className="text-sm text-gray-500">{label}</p>
        <p className="text-2xl font-bold text-gray-900">{value ?? '—'}</p>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get('/projects').then((r) => r.data),
  })

  const { data: scorecard } = useQuery({
    queryKey: ['scorecard-summary'],
    queryFn: () => api.get('/security/scorecard/summary').then((r) => r.data),
    retry: false,
  })

  const recentProjects = [...projects].slice(0, 5)

  const baselineColor = {
    LOW: 'bg-green-100 text-green-800',
    MODERATE: 'bg-yellow-100 text-yellow-800',
    HIGH: 'bg-red-100 text-red-800',
  }

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">ATO Bot — NIST SP 800-53 Rev 5 Assessment Platform</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <StatCard icon={FolderOpen} label="Total Projects" value={projects.length} color="bg-blue-600" />
        <StatCard
          icon={ShieldCheck}
          label="cATO Score"
          value={scorecard ? `${scorecard.compliance_score_pct}%` : null}
          color="bg-green-600"
        />
        <StatCard
          icon={AlertTriangle}
          label="Open POA&Ms"
          value={scorecard?.open_poams}
          color="bg-yellow-500"
        />
        <StatCard
          icon={Clock}
          label="Critical Events"
          value={scorecard?.critical_events_24h}
          color="bg-red-600"
        />
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Recent Projects */}
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h2 className="font-semibold text-gray-800">Recent Projects</h2>
            <Link to="/projects" className="text-sm text-blue-600 hover:text-blue-800">View all</Link>
          </div>
          <ul className="divide-y divide-gray-50">
            {recentProjects.length === 0 && (
              <li className="px-5 py-8 text-center text-sm text-gray-400">No projects yet</li>
            )}
            {recentProjects.map((p) => (
              <li key={p.id}>
                <Link to={`/projects/${p.id}`}
                  className="flex items-center justify-between px-5 py-3 hover:bg-gray-50">
                  <div>
                    <p className="text-sm font-medium text-gray-800">{p.name}</p>
                    <p className="text-xs text-gray-400">{p.system_type}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${baselineColor[p.impact_baseline] || 'bg-gray-100 text-gray-600'}`}>
                    {p.impact_baseline}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>

        {/* cATO Snapshot */}
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h2 className="font-semibold text-gray-800">Internal cATO Snapshot</h2>
            <Link to="/security/scorecard" className="text-sm text-blue-600 hover:text-blue-800">Full scorecard</Link>
          </div>
          {scorecard ? (
            <div className="p-5 space-y-3">
              <div className="flex items-center gap-3">
                <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
                  <div
                    className="h-3 rounded-full bg-green-500 transition-all"
                    style={{ width: `${scorecard.compliance_score_pct}%` }}
                  />
                </div>
                <span className="text-sm font-bold text-gray-700 w-12 text-right">
                  {scorecard.compliance_score_pct}%
                </span>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="bg-green-50 rounded-lg p-3">
                  <p className="text-xl font-bold text-green-700">{scorecard.implemented}</p>
                  <p className="text-xs text-green-600">Implemented</p>
                </div>
                <div className="bg-yellow-50 rounded-lg p-3">
                  <p className="text-xl font-bold text-yellow-700">{scorecard.partial}</p>
                  <p className="text-xs text-yellow-600">Partial</p>
                </div>
                <div className="bg-red-50 rounded-lg p-3">
                  <p className="text-xl font-bold text-red-700">{scorecard.not_implemented}</p>
                  <p className="text-xs text-red-600">Not Implemented</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="px-5 py-8 text-center text-sm text-gray-400">
              Scorecard data not available
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
