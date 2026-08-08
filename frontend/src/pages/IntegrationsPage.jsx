import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Activity,
  ArrowLeft,
  Cloud,
  Link2,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import api from '../api/client'

function StatusBadge({ status }) {
  const styles = {
    configured: 'bg-gray-100 text-gray-600',
    healthy: 'bg-green-100 text-green-700',
    connected: 'bg-blue-100 text-blue-700',
    needs_configuration: 'bg-amber-100 text-amber-700',
    failed: 'bg-red-100 text-red-700',
    completed: 'bg-green-100 text-green-700',
    running: 'bg-blue-100 text-blue-700',
    planned: 'bg-violet-100 text-violet-700',
    partial: 'bg-amber-100 text-amber-700',
    supported: 'bg-green-100 text-green-700',
    active: 'bg-red-100 text-red-700',
    resolved: 'bg-slate-100 text-slate-700',
  }
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles[status] || 'bg-gray-100 text-gray-600'}`}>
      {(status || 'unknown').replace(/_/g, ' ')}
    </span>
  )
}

function SummaryCard({ label, value, hint }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      {hint ? <p className="text-xs text-gray-500 mt-1">{hint}</p> : null}
    </div>
  )
}

function metricChips(evidence) {
  if (!evidence) return []
  return Object.entries(evidence)
    .filter(([key, value]) => (
      !['connector_type', 'connector_label', 'focus', 'summary', 'recommended_action'].includes(key)
      && (typeof value === 'number' || typeof value === 'string')
    ))
    .slice(0, 4)
}

export default function IntegrationsPage() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [connectorType, setConnectorType] = useState('ato_bot')
  const [name, setName] = useState('ATO Bot Internal')
  const [authMode, setAuthMode] = useState('internal')
  const [notes, setNotes] = useState('')

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get(`/projects/${projectId}`).then((r) => r.data),
  })

  const { data: catalogData } = useQuery({
    queryKey: ['integration-catalog', projectId],
    queryFn: () => api.get(`/projects/${projectId}/integrations/catalog`).then((r) => r.data),
  })

  const { data: accounts = [] } = useQuery({
    queryKey: ['integration-accounts', projectId],
    queryFn: () => api.get(`/projects/${projectId}/integrations/accounts`).then((r) => r.data),
  })

  const { data: runs = [] } = useQuery({
    queryKey: ['integration-runs', projectId],
    queryFn: () => api.get(`/projects/${projectId}/integrations/runs`).then((r) => r.data),
  })

  const { data: posture } = useQuery({
    queryKey: ['integration-posture', projectId],
    queryFn: () => api.get(`/projects/${projectId}/integrations/posture`).then((r) => r.data),
  })

  const catalog = catalogData?.items || []
  const selectedConnector = useMemo(
    () => catalog.find((item) => item.key === connectorType) || null,
    [catalog, connectorType],
  )

  const createMutation = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/integrations/accounts`, {
      connector_type: connectorType,
      name,
      auth_mode: authMode,
      config_json: notes.trim() ? { notes: notes.trim() } : {},
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['integration-accounts', projectId] })
      setNotes('')
    },
  })

  const testMutation = useMutation({
    mutationFn: (accountId) => api.post(`/projects/${projectId}/integrations/accounts/${accountId}/test`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['integration-accounts', projectId] }),
  })

  const syncMutation = useMutation({
    mutationFn: (accountId) => api.post(`/projects/${projectId}/integrations/accounts/${accountId}/sync`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['integration-accounts', projectId] })
      qc.invalidateQueries({ queryKey: ['integration-runs', projectId] })
      qc.invalidateQueries({ queryKey: ['integration-posture', projectId] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (accountId) => api.delete(`/projects/${projectId}/integrations/accounts/${accountId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['integration-accounts', projectId] })
      qc.invalidateQueries({ queryKey: ['integration-runs', projectId] })
      qc.invalidateQueries({ queryKey: ['integration-posture', projectId] })
    },
  })

  const healthyAccounts = accounts.filter((item) => ['healthy', 'connected'].includes(item.status)).length
  const supportCounts = posture?.summary?.support_counts || {}
  const liveControls = posture?.controls || []
  const drifts = posture?.drifts || []
  const latestRun = runs[0] || null

  return (
    <div className="p-8 max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate(`/projects/${projectId}`)}
            className="inline-flex items-center gap-2 border border-gray-300 text-gray-700 px-3 py-2 rounded-lg text-sm hover:bg-gray-50"
          >
            <ArrowLeft size={16} />
            Back
          </button>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Live Integrations</h1>
            <p className="text-sm text-gray-500 mt-1">
              Configure cATO-ready connector accounts for {project?.name || 'this project'}.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate(`/projects/${projectId}/cato-dashboard`)}
            className="inline-flex items-center gap-2 border border-teal-300 text-teal-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-teal-50"
          >
            <ShieldCheck size={16} />
            cATO Dashboard
          </button>
          <button
            onClick={() => navigate(`/projects/${projectId}/architecture-tools`)}
            className="inline-flex items-center gap-2 border border-sky-300 text-sky-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-sky-50"
          >
            <Cloud size={16} />
            Architecture & Tools
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <SummaryCard label="Configured Connectors" value={accounts.length} hint="Project-level integration accounts" />
        <SummaryCard label="Healthy" value={healthyAccounts} hint="Dry-run or configured connector checks passing" />
        <SummaryCard
          label="Live Control States"
          value={posture?.summary?.control_count || 0}
          hint={`${supportCounts.supported || 0} supported | ${supportCounts.partial || 0} partial | ${supportCounts.planned || 0} planned`}
        />
        <SummaryCard
          label="Active Drift"
          value={posture?.summary?.active_drift_count || 0}
          hint={`${runs.length} sync runs | ${catalog.length} templates`}
        />
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
        <p className="text-sm font-semibold text-blue-900 mb-1">Current slice</p>
        <p className="text-sm text-blue-800">
          These connectors support dry-run testing today so you can build the cATO workflow now without live credentials.
          Real API pulls are the next implementation slice.
        </p>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <ShieldCheck size={16} className="text-emerald-600" />
          <h2 className="font-semibold text-gray-900">cATO Rollup</h2>
        </div>
        {latestRun ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-gray-900">{latestRun.account_name}</span>
              <StatusBadge status={latestRun.status} />
              <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 font-medium">
                {latestRun.connector_label}
              </span>
            </div>
            <p className="text-sm text-gray-600">
              Latest sync observed {latestRun.records_seen} records and produced {latestRun.assertions_created} normalized assertions.
            </p>
            {latestRun.summary?.preview_assertions?.length ? (
              <ul className="space-y-1">
                {latestRun.summary.preview_assertions.slice(0, 3).map((item, index) => (
                  <li key={index} className="text-sm text-gray-700">{item}</li>
                ))}
              </ul>
            ) : null}
            {latestRun.summary?.next_step ? (
              <p className="text-xs text-gray-500">Next step: {latestRun.summary.next_step}</p>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-gray-500">Run a connector sync to produce normalized live posture and drift data.</p>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-1 bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Plus size={16} className="text-violet-600" />
            <h2 className="font-semibold text-gray-900">Add Connector</h2>
          </div>

          <label className="block text-sm text-gray-700">
            <span className="block text-xs font-semibold text-gray-500 mb-1">Connector Type</span>
            <select
              value={connectorType}
              onChange={(event) => {
                const nextType = event.target.value
                setConnectorType(nextType)
                const item = catalog.find((entry) => entry.key === nextType)
                if (item?.auth_modes?.length) setAuthMode(item.auth_modes[0])
                if (item?.label) setName(`${item.label} ${item?.auth_modes?.[0] === 'internal' ? 'Internal' : 'Dry Run'}`)
              }}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white"
            >
              {catalog.map((item) => (
                <option key={item.key} value={item.key}>{item.label}</option>
              ))}
            </select>
          </label>

          <label className="block text-sm text-gray-700">
            <span className="block text-xs font-semibold text-gray-500 mb-1">Connection Name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white"
            />
          </label>

          <label className="block text-sm text-gray-700">
            <span className="block text-xs font-semibold text-gray-500 mb-1">Auth Mode</span>
            <select
              value={authMode}
              onChange={(event) => setAuthMode(event.target.value)}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white"
            >
              {(selectedConnector?.auth_modes || ['dry_run']).map((mode) => (
                <option key={mode} value={mode}>{mode.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </label>

          <label className="block text-sm text-gray-700">
            <span className="block text-xs font-semibold text-gray-500 mb-1">Notes</span>
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              rows={5}
              placeholder="Environment name, intended tenant/account, or other planning notes."
              className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white"
            />
          </label>

          <button
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending || !connectorType || !name.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
          >
            <Plus size={15} />
            {createMutation.isPending ? 'Creating...' : 'Create Connector'}
          </button>

          {selectedConnector ? (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 space-y-2">
              <p className="font-medium text-gray-900">{selectedConnector.label}</p>
              <p>{selectedConnector.description}</p>
              <p className="text-xs text-gray-500">
                Evidence types: {(selectedConnector.evidence_types || []).join(', ')}
              </p>
            </div>
          ) : null}
        </div>

        <div className="xl:col-span-2 space-y-6">
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <Link2 size={16} className="text-blue-600" />
              <h2 className="font-semibold text-gray-900">Connector Accounts</h2>
            </div>
            {accounts.length === 0 ? (
              <p className="text-sm text-gray-500">No connectors configured yet.</p>
            ) : (
              <div className="space-y-3">
                {accounts.map((account) => (
                  <div key={account.id} className="rounded-lg border border-gray-200 p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-gray-900">{account.name}</span>
                          <StatusBadge status={account.status} />
                          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 font-medium">
                            {account.connector_label}
                          </span>
                        </div>
                        <p className="text-sm text-gray-600 mt-1">
                          Auth: {account.auth_mode.replace(/_/g, ' ')}
                          {account.config?.notes ? ` | ${account.config.notes}` : ''}
                        </p>
                        {account.last_error ? (
                          <p className="text-xs text-red-600 mt-2">{account.last_error}</p>
                        ) : null}
                        <p className="text-xs text-gray-500 mt-2">
                          Last tested: {account.last_tested_at ? new Date(account.last_tested_at).toLocaleString() : 'never'}
                          {' '}| Last sync: {account.last_run_at ? new Date(account.last_run_at).toLocaleString() : 'never'}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <button
                          onClick={() => testMutation.mutate(account.id)}
                          className="inline-flex items-center gap-1 rounded-lg border border-blue-200 px-3 py-2 text-xs font-medium text-blue-700 hover:bg-blue-50"
                        >
                          <ShieldCheck size={13} />
                          Test
                        </button>
                        <button
                          onClick={() => syncMutation.mutate(account.id)}
                          className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 px-3 py-2 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
                        >
                          <Play size={13} />
                          Sync
                        </button>
                        <button
                          onClick={() => deleteMutation.mutate(account.id)}
                          className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50"
                        >
                          <Trash2 size={13} />
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <Activity size={16} className="text-emerald-600" />
              <h2 className="font-semibold text-gray-900">Recent Sync Runs</h2>
            </div>
            {runs.length === 0 ? (
              <p className="text-sm text-gray-500">No sync runs yet.</p>
            ) : (
              <div className="space-y-3">
                {runs.map((run) => (
                  <div key={run.id} className="rounded-lg border border-gray-200 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-gray-900">{run.account_name}</span>
                          <StatusBadge status={run.status} />
                          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
                            {run.connector_label}
                          </span>
                        </div>
                        <p className="text-sm text-gray-600 mt-1">
                          Trigger: {run.trigger_mode}
                          {' '}| Records: {run.records_seen}
                          {' '}| Assertions: {run.assertions_created}
                        </p>
                        {run.summary?.preview_assertions?.length ? (
                          <ul className="mt-2 space-y-1">
                            {run.summary.preview_assertions.slice(0, 3).map((item, index) => (
                              <li key={index} className="text-xs text-gray-500">{item}</li>
                            ))}
                          </ul>
                        ) : null}
                        {run.error_message ? <p className="text-xs text-red-600 mt-2">{run.error_message}</p> : null}
                      </div>
                      <div className="text-right text-xs text-gray-500 flex-shrink-0">
                        <p>{run.started_at ? new Date(run.started_at).toLocaleString() : 'n/a'}</p>
                        <p className="mt-1">{run.completed_at ? 'completed' : 'in progress'}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <ShieldCheck size={16} className="text-violet-600" />
              <h2 className="font-semibold text-gray-900">Live Control Posture</h2>
            </div>
            {liveControls.length === 0 ? (
              <p className="text-sm text-gray-500">No live or planned control support yet. Run a connector sync to populate posture.</p>
            ) : (
              <div className="space-y-3">
                {liveControls.slice(0, 16).map((item) => (
                  <div key={`${item.control_id}-${item.source_ref}`} className="rounded-lg border border-gray-200 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-gray-900">{item.control_id}</span>
                          <StatusBadge status={item.support_status} />
                        </div>
                        <p className="text-sm text-gray-600 mt-1">
                          Source: {item.evidence?.connector_label || item.evidence?.connector_type || item.source_ref}
                          {' '}| Focus: {item.evidence?.focus || 'connector support'}
                        </p>
                        {item.evidence?.summary ? (
                          <p className="text-sm text-gray-700 mt-2">{item.evidence.summary}</p>
                        ) : null}
                        {metricChips(item.evidence).length ? (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {metricChips(item.evidence).map(([key, value]) => (
                              <span key={key} className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                                {key.replace(/_/g, ' ')}: {String(value)}
                              </span>
                            ))}
                          </div>
                        ) : null}
                        {item.evidence?.recommended_action ? (
                          <p className="text-xs text-gray-500 mt-2">
                            Recommended action: {item.evidence.recommended_action}
                          </p>
                        ) : null}
                        <p className="text-xs text-gray-500 mt-2">
                          Freshness: {item.freshness_status}
                          {' '}| Confidence: {item.confidence ? `${Math.round(item.confidence * 100)}%` : 'n/a'}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <RefreshCw size={16} className="text-amber-600" />
              <h2 className="font-semibold text-gray-900">Drift & Gaps</h2>
            </div>
            {drifts.length === 0 ? (
              <p className="text-sm text-gray-500">No drift records yet. Dry-run connectors usually stay clean until you switch to real credentials.</p>
            ) : (
              <div className="space-y-3">
                {drifts.slice(0, 12).map((item) => (
                  <div key={item.id} className="rounded-lg border border-gray-200 p-4">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-gray-900">{item.title}</span>
                      <StatusBadge status={item.status} />
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        item.severity === 'high'
                          ? 'bg-red-100 text-red-700'
                          : item.severity === 'medium'
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-slate-100 text-slate-700'
                      }`}>
                        {item.severity}
                      </span>
                    </div>
                    {item.details?.recommended_action ? (
                      <p className="text-sm text-gray-600 mt-2">{item.details.recommended_action}</p>
                    ) : null}
                    <p className="text-xs text-gray-500 mt-2">
                      Scope: {item.scope_type} | Reference: {item.scope_id} | Updated: {item.updated_at ? new Date(item.updated_at).toLocaleString() : 'n/a'}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <Cloud size={16} className="text-sky-600" />
              <h2 className="font-semibold text-gray-900">Supported Connector Templates</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {catalog.map((item) => (
                <div key={item.key} className="rounded-lg border border-gray-200 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-medium text-gray-900">{item.label}</p>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 font-medium">
                      {item.category}
                    </span>
                  </div>
                  <p className="text-sm text-gray-600 mt-2">{item.description}</p>
                  <p className="text-xs text-gray-500 mt-2">
                    Auth modes: {(item.auth_modes || []).join(', ')}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
