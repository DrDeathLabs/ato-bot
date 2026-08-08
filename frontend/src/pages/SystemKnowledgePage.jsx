import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft, BrainCircuit, CheckCircle2, File, RefreshCw, ShieldAlert, Wrench, XCircle,
  Search, MessageSquare,
} from 'lucide-react'
import api from '../api/client'
import { openCyberAssistant } from '../components/cyberAssistant'

const experimentalCatoEnabled = import.meta.env.VITE_ENABLE_EXPERIMENTAL_CATO === 'true'

function SummaryCard({ label, value, hint }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      {hint ? <p className="text-xs text-gray-500 mt-1">{hint}</p> : null}
    </div>
  )
}

function StatusBadge({ status }) {
  const map = {
    proposed: 'bg-amber-100 text-amber-700',
    confirmed: 'bg-green-100 text-green-700',
    rejected: 'bg-red-100 text-red-700',
    missing_evidence: 'bg-gray-100 text-gray-600',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${map[status] || 'bg-gray-100 text-gray-600'}`}>
      {status?.replace(/_/g, ' ') || 'unknown'}
    </span>
  )
}

export default function SystemKnowledgePage() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get(`/projects/${projectId}`).then((r) => r.data),
  })

  const { data: knowledge, isLoading } = useQuery({
    queryKey: ['system-knowledge', projectId],
    queryFn: () => api.get(`/projects/${projectId}/system-knowledge`).then((r) => r.data),
  })

  const { data: validation } = useQuery({
    queryKey: ['system-knowledge-validation', projectId],
    queryFn: () => api.get(`/projects/${projectId}/system-knowledge/validation`).then((r) => r.data),
  })

  const { data: inheritance } = useQuery({
    queryKey: ['system-knowledge-inheritance', projectId],
    queryFn: () => api.get(`/projects/${projectId}/system-knowledge/inheritance`).then((r) => r.data),
  })

  const extractMutation = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/system-knowledge/extract`, { source_mode: 'manual_review', source_run_id: 0 }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['system-knowledge', projectId] })
      qc.invalidateQueries({ queryKey: ['system-knowledge-validation', projectId] })
    },
  })

  const suggestInheritanceMutation = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/system-knowledge/inheritance/suggest`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['system-knowledge-inheritance', projectId] }),
  })

  const reviewMutation = useMutation({
    mutationFn: ({ assertionId, status }) =>
      api.patch(`/projects/${projectId}/system-knowledge/assertions/${assertionId}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['system-knowledge', projectId] }),
  })

  const reviewInheritanceMutation = useMutation({
    mutationFn: ({ responsibilityId, status }) =>
      api.patch(`/projects/${projectId}/system-knowledge/inheritance/${responsibilityId}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['system-knowledge-inheritance', projectId] }),
  })

  const assertions = knowledge?.assertions || []
  const tools = knowledge?.tools || []
  const run = knowledge?.run
  const validationSummary = validation?.validation_run?.summary || {}
  const viability = validation?.package_viability
  const providers = inheritance?.providers || []
  const responsibilities = inheritance?.responsibilities || []
  const inheritanceCounts = inheritance?.summary?.inheritance_counts || {}

  const groupedAssertions = useMemo(() => {
    const grouped = {}
    for (const assertion of assertions) {
      const category = assertion.category || 'other'
      if (!grouped[category]) grouped[category] = []
      grouped[category].push(assertion)
    }
    return Object.entries(grouped).sort((a, b) => a[0].localeCompare(b[0]))
  }, [assertions])

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
            <h1 className="text-2xl font-bold text-gray-900">Architecture & Tools</h1>
            <p className="text-sm text-gray-500 mt-1">
              Review what the system inferred about {project?.name || 'this project'} and confirm the real stack.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {experimentalCatoEnabled && (
            <>
              <button
                onClick={() => navigate(`/projects/${projectId}/integrations`)}
                className="inline-flex items-center gap-2 border border-indigo-300 text-indigo-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-50"
              >
                <Wrench size={16} />
                Experimental Integrations
              </button>
              <button
                onClick={() => navigate(`/projects/${projectId}/cato-dashboard`)}
                className="inline-flex items-center gap-2 border border-teal-300 text-teal-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-teal-50"
              >
                <ShieldAlert size={16} />
                Experimental cATO Dashboard
              </button>
            </>
          )}
          <button
            onClick={() => navigate(`/projects/${projectId}/ssp-workbench`)}
            className="inline-flex items-center gap-2 border border-emerald-300 text-emerald-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-emerald-50"
          >
            <File size={16} />
            SSP Workbench
          </button>
          <button
            onClick={() => openCyberAssistant({
              mode: 'workspace',
              title: `${project?.name || 'Project'} Architecture Assistant`,
              projectId: Number(projectId),
              attachments: [{ type: 'project', resource_id: String(projectId), context_json: { view: 'system_knowledge' } }],
              initialPrompt: 'Explain what we know about this system architecture, where evidence is strong, and what tools or components may still be missing.',
            })}
            className="inline-flex items-center gap-2 border border-violet-300 text-violet-600 px-4 py-2 rounded-lg text-sm font-medium hover:bg-violet-50"
          >
            <MessageSquare size={16} />
            Ask AI
          </button>
          <button
            onClick={() => extractMutation.mutate()}
            disabled={extractMutation.isPending}
            className="inline-flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            <RefreshCw size={16} className={extractMutation.isPending ? 'animate-spin' : ''} />
            Refresh Extraction
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        <SummaryCard label="Assertions" value={assertions.length} hint={run ? `Latest run #${run.id}` : 'No extraction yet'} />
        <SummaryCard label="Detected Tools" value={tools.length} hint="Review and confirm the active stack" />
        <SummaryCard label="Providers" value={providers.length} hint="Linked common control providers" />
        <SummaryCard label="Ready Artifacts" value={validationSummary.retrieval_viable || 0} hint={`${validationSummary.document_count || 0} validated docs`} />
        <SummaryCard label="Viability" value={`${Math.round(viability?.viability_score || 0)}%`} hint={viability?.status || 'No package score yet'} />
      </div>

      <div className="bg-sky-50 border border-sky-200 rounded-xl p-4">
        <p className="text-sm font-semibold text-sky-900 mb-1">Why this matters</p>
        <p className="text-sm text-sky-800">
          This layer is what the system currently believes about your architecture, tools, and defense-in-depth controls.
          Confirm what is right, reject what is wrong, and use the gaps to decide which artifacts or screenshots still need to be collected.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-1 bg-white border border-gray-200 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Wrench size={16} className="text-blue-600" />
            <h2 className="font-semibold text-gray-900">Detected Tools</h2>
          </div>
          {tools.length === 0 ? (
            <p className="text-sm text-gray-500">No tools detected yet. Run extraction or add more evidence.</p>
          ) : (
            <div className="space-y-3">
              {tools.map((tool, index) => (
                <div key={`${tool.tool_name}-${index}`} className="border border-gray-200 rounded-lg p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="font-medium text-gray-900">{tool.tool_name}</p>
                      <p className="text-xs text-gray-500 mt-0.5">{tool.tool_category || 'tool'} - {tool.vendor || 'vendor unknown'}</p>
                    </div>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
                      {(tool.status || 'proposed').replace(/_/g, ' ')}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="xl:col-span-2 bg-white border border-gray-200 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <BrainCircuit size={16} className="text-violet-600" />
            <h2 className="font-semibold text-gray-900">Reviewable Assertions</h2>
          </div>
          {isLoading ? (
            <p className="text-sm text-gray-500">Loading system knowledge...</p>
          ) : assertions.length === 0 ? (
            <p className="text-sm text-gray-500">No system assertions yet.</p>
          ) : (
            <div className="space-y-5">
              {groupedAssertions.map(([category, items]) => (
                <div key={category}>
                  <div className="flex items-center gap-2 mb-2">
                    <ShieldAlert size={14} className="text-gray-400" />
                    <h3 className="text-sm font-semibold text-gray-800 capitalize">{category.replace(/_/g, ' ')}</h3>
                  </div>
                  <div className="space-y-3">
                    {items.map((assertion) => (
                      <div key={assertion.id} className="border border-gray-200 rounded-lg p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-sm font-medium text-gray-900">{assertion.key.replace(/_/g, ' ')}</span>
                              <StatusBadge status={assertion.status} />
                              <span className="text-xs text-gray-400">confidence {Math.round((assertion.confidence || 0) * 100)}%</span>
                            </div>
                            <p className="text-sm text-gray-700 mt-1 break-words">
                              {typeof assertion.value === 'object' ? JSON.stringify(assertion.value) : String(assertion.value)}
                            </p>
                            {assertion.rationale ? (
                              <p className="text-xs text-gray-500 mt-2">{assertion.rationale}</p>
                            ) : null}
                            {assertion.provenance?.snippets?.length ? (
                              <div className="mt-2 bg-gray-50 border border-gray-100 rounded p-2">
                                <p className="text-xs font-semibold text-gray-500 mb-1">Supporting snippets</p>
                                <ul className="space-y-1">
                                  {assertion.provenance.snippets.slice(0, 2).map((snippet, idx) => (
                                    <li key={idx} className="text-xs text-gray-600 leading-relaxed">{snippet}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0">
                            <button
                              onClick={() => reviewMutation.mutate({ assertionId: assertion.id, status: 'confirmed' })}
                              className="inline-flex items-center gap-1 text-xs border border-green-200 text-green-700 px-2 py-1 rounded hover:bg-green-50"
                            >
                              <CheckCircle2 size={12} />
                              Confirm
                            </button>
                            <button
                              onClick={() => reviewMutation.mutate({ assertionId: assertion.id, status: 'rejected' })}
                              className="inline-flex items-center gap-1 text-xs border border-red-200 text-red-600 px-2 py-1 rounded hover:bg-red-50"
                            >
                              <XCircle size={12} />
                              Reject
                            </button>
                            <button
                              onClick={() => openCyberAssistant({
                                mode: 'workspace',
                                title: `${project?.name || 'Project'} Evidence Search`,
                                projectId: Number(projectId),
                                attachments: [{ type: 'project', resource_id: String(projectId), context_json: { assertion_id: assertion.id, assertion_key: assertion.key } }],
                                initialPrompt: `Search the project evidence for more proof about "${assertion.key}". If the evidence is weak, tell me what artifact or screenshot should be collected next.`,
                              })}
                              className="inline-flex items-center gap-1 text-xs border border-blue-200 text-blue-600 px-2 py-1 rounded hover:bg-blue-50"
                            >
                              <Search size={12} />
                              Search
                            </button>
                          </div>
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

      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-gray-900">Control Inheritance & Shared Responsibility</h2>
            <p className="text-sm text-gray-500 mt-1">
              Model what a common control provider covers, what is shared, and what still belongs to the system team.
            </p>
          </div>
          <button
            onClick={() => suggestInheritanceMutation.mutate()}
            disabled={suggestInheritanceMutation.isPending || providers.length === 0}
            className="inline-flex items-center gap-2 border border-blue-300 text-blue-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-50 disabled:opacity-50"
          >
            <RefreshCw size={15} className={suggestInheritanceMutation.isPending ? 'animate-spin' : ''} />
            Suggest Inheritance
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <SummaryCard label="Linked Providers" value={providers.length} hint="Cloud or enterprise common control sources" />
          <SummaryCard label="Mappings" value={responsibilities.length} hint="Family/control/objective responsibility entries" />
          <SummaryCard label="Inherited" value={inheritanceCounts.inherited || 0} hint="Provider-led coverage" />
          <SummaryCard label="Shared" value={inheritanceCounts.shared || 0} hint="Local system still owns part of the control" />
        </div>

        {providers.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-5 text-sm text-gray-600">
            No common control providers are linked to this project yet. Link a provider such as AWS or an enterprise shared service first, then suggest inheritance mappings here.
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {providers.map((provider) => (
                <div key={provider.id} className="rounded-lg border border-gray-200 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-medium text-gray-900">{provider.name}</p>
                      <p className="text-xs text-gray-500 mt-0.5">{provider.org_level} provider</p>
                    </div>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
                      {(provider.control_families || []).length} families
                    </span>
                  </div>
                  <p className="text-sm text-gray-600 mt-2">{provider.description || 'No description provided.'}</p>
                  <p className="text-xs text-gray-500 mt-2">
                    Families: {(provider.control_families || []).join(', ') || 'none declared'}
                  </p>
                </div>
              ))}
            </div>

            {responsibilities.length === 0 ? (
              <div className="rounded-lg border border-dashed border-blue-300 bg-blue-50 px-4 py-5 text-sm text-blue-800">
                No inheritance mappings yet. Use <span className="font-medium">Suggest Inheritance</span> to create proposed shared-responsibility mappings from the linked providers.
              </div>
            ) : (
              <div className="space-y-3">
                {responsibilities.map((item) => (
                  <div key={item.id} className="rounded-lg border border-gray-200 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium text-gray-900">{item.provider_name}</span>
                          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 font-medium">
                            {item.scope_type}
                          </span>
                          <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-medium">
                            {item.scope_id}
                          </span>
                          <StatusBadge status={item.status} />
                        </div>
                        <p className="text-sm text-gray-700 mt-2">
                          <span className="font-medium">Inheritance:</span> {item.inheritance_type.replace(/_/g, ' ')}
                          {' '}· <span className="font-medium">Provider coverage:</span> {item.provider_coverage_status.replace(/_/g, ' ')}
                        </p>
                        {item.system_responsibility ? (
                          <p className="text-sm text-gray-600 mt-2">
                            <span className="font-medium text-gray-700">System still owns:</span> {item.system_responsibility}
                          </p>
                        ) : null}
                        {item.rationale ? (
                          <p className="text-xs text-gray-500 mt-2">{item.rationale}</p>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <button
                          onClick={() => reviewInheritanceMutation.mutate({ responsibilityId: item.id, status: 'confirmed' })}
                          className="inline-flex items-center gap-1 text-xs border border-green-200 text-green-700 px-2 py-1 rounded hover:bg-green-50"
                        >
                          <CheckCircle2 size={12} />
                          Confirm
                        </button>
                        <button
                          onClick={() => reviewInheritanceMutation.mutate({ responsibilityId: item.id, status: 'rejected' })}
                          className="inline-flex items-center gap-1 text-xs border border-red-200 text-red-600 px-2 py-1 rounded hover:bg-red-50"
                        >
                          <XCircle size={12} />
                          Reject
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
