import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, File, MessageSquare, RefreshCw, ShieldCheck } from 'lucide-react'
import api from '../api/client'
import { openCyberAssistant } from '../components/cyberAssistant'

function SectionCard({ projectId, section, onRefresh }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold text-gray-900">{section.title}</h3>
          <p className="text-xs text-gray-500 mt-1">{section.source_count || 0} source facts attached</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onRefresh(section.section_id)}
            className="inline-flex items-center gap-1.5 border border-gray-300 text-gray-700 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-gray-50"
          >
            <RefreshCw size={12} />
            Regenerate
          </button>
          <button
            onClick={() => openCyberAssistant({
              mode: 'workspace',
              title: `${section.title} Assistant`,
              projectId: Number(projectId),
              attachments: [{ type: 'project', resource_id: String(projectId), context_json: { view: 'ssp_workbench', section_id: section.section_id } }],
              initialPrompt: `Review the drafted SSP section "${section.title}". Explain whether it looks grounded, what seems missing, and what evidence should be validated before using it.`,
            })}
            className="inline-flex items-center gap-1.5 border border-violet-300 text-violet-700 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-violet-50"
          >
            <MessageSquare size={12} />
            Ask AI
          </button>
        </div>
      </div>

      <div className="bg-gray-50 border border-gray-100 rounded-lg p-4">
        <pre className="whitespace-pre-wrap text-sm text-gray-800 leading-6 font-sans">{section.content}</pre>
      </div>

      {section.sources?.length ? (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Source Facts</p>
          <div className="space-y-2">
            {section.sources.map((source, index) => (
              <div key={index} className="border border-gray-200 rounded-lg px-3 py-2 bg-white">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-sky-100 text-sky-700 font-medium">
                    {source.type?.replace(/_/g, ' ') || 'source'}
                  </span>
                  <span className="text-sm font-medium text-gray-900">{source.label}</span>
                  {source.status ? (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                      {source.status.replace(/_/g, ' ')}
                    </span>
                  ) : null}
                </div>
                {source.details ? (
                  <pre className="whitespace-pre-wrap text-xs text-gray-600 mt-2 font-sans">
                    {JSON.stringify(source.details, null, 2)}
                  </pre>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default function SspWorkbenchPage() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get(`/projects/${projectId}`).then((r) => r.data),
  })

  const { data: knowledge } = useQuery({
    queryKey: ['ssp-knowledge-sources', projectId],
    queryFn: () => api.get(`/projects/${projectId}/ssp/knowledge-sources`).then((r) => r.data),
  })

  const { data: composition, isLoading } = useQuery({
    queryKey: ['ssp-composition', projectId],
    queryFn: () => api.post(`/projects/${projectId}/ssp/compose`).then((r) => r.data),
  })

  const refreshSectionMutation = useMutation({
    mutationFn: (sectionKey) => api.post(`/projects/${projectId}/ssp/compose-section`, { section_key: sectionKey }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ssp-composition', projectId] }),
  })

  const assertionCount = knowledge?.assertions?.length || 0
  const toolCount = knowledge?.tools?.length || 0

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
            <h1 className="text-2xl font-bold text-gray-900">SSP Workbench</h1>
            <p className="text-sm text-gray-500 mt-1">
              Review knowledge-backed SSP section drafts for {project?.name || 'this project'} before using them in formal package narrative.
            </p>
          </div>
        </div>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ['ssp-composition', projectId] })}
          className="inline-flex items-center gap-2 border border-gray-300 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50"
        >
          <RefreshCw size={16} />
          Refresh Draft
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Knowledge Assertions</p>
          <p className="text-2xl font-bold text-gray-900">{assertionCount}</p>
          <p className="text-xs text-gray-500 mt-1">Architecture facts available for SSP drafting</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Detected Tools</p>
          <p className="text-2xl font-bold text-gray-900">{toolCount}</p>
          <p className="text-xs text-gray-500 mt-1">Defense-in-depth components available to describe</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Draft Sections</p>
          <p className="text-2xl font-bold text-gray-900">{composition?.section_count || 0}</p>
          <p className="text-xs text-gray-500 mt-1">Generated from project knowledge instead of free-text guessing</p>
        </div>
      </div>

      <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm text-emerald-900">
        <p className="font-semibold mb-1">How to use this</p>
        <p>
          Treat these sections as grounded draft narrative, not final SSP truth. Confirm architecture assertions in the Architecture & Tools view first, then use this workbench to review wording, source facts, and remaining evidence gaps section by section.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => navigate(`/projects/${projectId}/architecture-tools`)}
          className="inline-flex items-center gap-2 border border-sky-300 text-sky-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-sky-50"
        >
          <ShieldCheck size={16} />
          Review Architecture & Tools
        </button>
        <button
          onClick={() => openCyberAssistant({
            mode: 'workspace',
            title: `${project?.name || 'Project'} SSP Assistant`,
            projectId: Number(projectId),
            attachments: [{ type: 'project', resource_id: String(projectId), context_json: { view: 'ssp_workbench' } }],
            initialPrompt: 'Review the current SSP drafts, explain which sections look strong, and call out where the architecture knowledge still needs confirmation before the SSP can be trusted.',
          })}
          className="inline-flex items-center gap-2 border border-violet-300 text-violet-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-violet-50"
        >
          <MessageSquare size={16} />
          Ask AI
        </button>
      </div>

      {isLoading ? (
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-sm text-gray-500">
          Composing SSP sections...
        </div>
      ) : (
        <div className="space-y-4">
          {(composition?.sections || []).map((section) => (
            <SectionCard
              key={section.section_id}
              projectId={projectId}
              section={section}
              onRefresh={(sectionKey) => refreshSectionMutation.mutate(sectionKey)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
