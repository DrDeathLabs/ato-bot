import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Info,
  MessageSquare,
  RotateCcw,
  Save,
  Sparkles,
  Tag,
} from 'lucide-react'

import api from '../../api/client'
import { openCyberAssistant } from '../../components/cyberAssistant'

const CATEGORY_ORDER = ['Assessment', 'Multi-Stage Assessment', 'Ingestion', 'Remediation', 'AI Assist']

const CATEGORY_COLORS = {
  Assessment: 'bg-blue-100 text-blue-700',
  'Multi-Stage Assessment': 'bg-indigo-100 text-indigo-700',
  Ingestion: 'bg-teal-100 text-teal-700',
  Remediation: 'bg-amber-100 text-amber-700',
  'AI Assist': 'bg-violet-100 text-violet-700',
}

const RUNTIME_META = {
  assessment_reasoning: {
    title: 'Assessment reasoning',
    detail: 'Primary assessment, multi-stage evaluation, challenge review, and narratives.',
  },
  ai_assist_notes: {
    title: 'AI assist notes',
    detail: 'Short note and rationale helpers.',
  },
  document_tagging: {
    title: 'Document tagging',
    detail: 'Older full-document tagging and chunk mapping.',
  },
  procedure_categorization: {
    title: 'Procedure categorization',
    detail: 'Enterprise procedure library routing.',
  },
  remediation_generation: {
    title: 'Remediation generation',
    detail: 'Remediation guides, supplement planning, and artifact generation.',
  },
  ingestion_screening: {
    title: 'Ingestion screening',
    detail: 'Stage 2 candidate-relevance screening for parsed units.',
  },
}

function fmt(iso) {
  if (!iso) return null
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

function groupedPrompts(prompts) {
  const allCategories = [
    ...CATEGORY_ORDER,
    ...prompts.map(prompt => prompt.category).filter(category => !CATEGORY_ORDER.includes(category)),
  ].filter((value, index, array) => array.indexOf(value) === index)

  return allCategories.reduce((acc, category) => {
    acc[category] = prompts.filter(prompt => prompt.category === category)
    return acc
  }, {})
}

function RuntimeBadge({ runtime }) {
  if (!runtime) return null
  return (
    <div className="rounded-xl border border-violet-200 bg-violet-50 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-violet-900">{runtime.title}</div>
          <div className="mt-1 text-xs text-violet-700">{runtime.detail}</div>
        </div>
        <span className="rounded-full border border-violet-200 bg-white px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-violet-700">
          {runtime.provider}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-3">
        <div className="rounded-lg border border-violet-100 bg-white px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-gray-500">Model</div>
          <div className="mt-1 break-all font-mono text-xs text-gray-800">{runtime.model || '-'}</div>
        </div>
        <div className="rounded-lg border border-violet-100 bg-white px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-gray-500">Reasoning Effort</div>
          <div className="mt-1 text-xs text-gray-800">{runtime.reasoning_effort || 'n/a'}</div>
        </div>
        <div className="rounded-lg border border-violet-100 bg-white px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-gray-500">Config Source</div>
          <div className="mt-1 text-xs text-gray-800">{runtime.source || 'default'}</div>
        </div>
      </div>
    </div>
  )
}

export default function PromptManager() {
  const qc = useQueryClient()
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState('')
  const [showDefault, setShowDefault] = useState(false)
  const [saved, setSaved] = useState(false)

  const { data: prompts = [], isLoading } = useQuery({
    queryKey: ['admin-prompts'],
    queryFn: () => api.get('/admin/prompts').then(response => response.data),
  })

  const { data: runtimeMapData } = useQuery({
    queryKey: ['llm-runtime-map'],
    queryFn: () => api.get('/llm/runtime-map').then(response => response.data),
  })

  const selected = prompts.find(prompt => prompt.id === selectedId)

  const saveMutation = useMutation({
    mutationFn: ({ id, content }) => api.put(`/admin/prompts/${id}`, { content }),
    onSuccess: () => {
      qc.invalidateQueries(['admin-prompts'])
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    },
  })

  const resetMutation = useMutation({
    mutationFn: id => api.delete(`/admin/prompts/${id}`),
    onSuccess: (_, id) => {
      qc.invalidateQueries(['admin-prompts'])
      const prompt = prompts.find(item => item.id === id)
      if (prompt) setDraft(prompt.default)
      setShowDefault(false)
    },
  })

  const selectPrompt = prompt => {
    setSelectedId(prompt.id)
    setDraft(prompt.content)
    setShowDefault(false)
    setSaved(false)
  }

  const isDirty = selected && draft !== selected.content
  const grouped = useMemo(() => groupedPrompts(prompts), [prompts])

  const selectedRuntime = selected?.runtime_purpose
    ? runtimeMapData?.routes?.[selected.runtime_purpose]
    : null

  const runtimeSummary = useMemo(() => {
    const purposes = Object.keys(RUNTIME_META)
    return purposes
      .map(key => ({
        key,
        runtime: runtimeMapData?.routes?.[key],
        ...RUNTIME_META[key],
      }))
      .filter(item => item.runtime)
  }, [runtimeMapData])

  return (
    <div className="flex h-full" style={{ height: 'calc(100vh - 0px)' }}>
      <aside className="flex w-72 flex-col border-r border-gray-200 bg-white">
        <div className="border-b border-gray-100 px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h1 className="flex items-center gap-2 text-lg font-bold text-gray-900">
                <Sparkles size={18} className="text-violet-500" />
                Prompt Manager
              </h1>
              <p className="mt-0.5 text-xs text-gray-500">
                Edit live prompts and see which model route each prompt family feeds.
              </p>
            </div>
            <button
              type="button"
              onClick={() => openCyberAssistant({
                mode: 'admin_runtime',
                title: 'Prompt Manager Assistant',
                attachments: [{
                  type: 'admin_runtime',
                  resource_id: 'prompt_manager',
                  context_json: {
                    label: 'Prompt Manager',
                    setting_key: 'prompt_manager',
                    setting_value: 'Prompt editing and runtime ownership',
                  },
                }],
              })}
              className="inline-flex items-center gap-1.5 rounded-lg border border-violet-200 bg-violet-50 px-3 py-1.5 text-xs font-medium text-violet-700 hover:bg-violet-100 transition-colors"
            >
              <MessageSquare size={13} />
              Ask AI
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-3">
          {isLoading && <div className="p-3 text-xs text-gray-400">Loading prompts...</div>}
          {Object.entries(grouped).map(([category, items]) =>
            items.length > 0 ? (
              <div key={category}>
                <div className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
                  {category}
                </div>
                <div className="space-y-0.5">
                  {items.map(prompt => (
                    <button
                      key={prompt.id}
                      onClick={() => selectPrompt(prompt)}
                      className={`group w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${
                        selectedId === prompt.id
                          ? 'border-blue-200 bg-blue-50'
                          : 'border-transparent hover:bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="flex-1 truncate text-sm font-medium text-gray-800">{prompt.label}</span>
                        {prompt.is_overridden ? (
                          <span className="flex-shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-700">
                            Custom
                          </span>
                        ) : null}
                        <ChevronRight size={12} className="flex-shrink-0 text-gray-300" />
                      </div>
                      {prompt.runtime_purpose ? (
                        <p className="mt-0.5 truncate text-xs text-gray-400">
                          {RUNTIME_META[prompt.runtime_purpose]?.title || prompt.runtime_purpose}
                        </p>
                      ) : null}
                      {prompt.is_overridden && prompt.updated_at ? (
                        <p className="mt-0.5 truncate text-xs text-gray-400">
                          {fmt(prompt.updated_at)} - {prompt.updated_by}
                        </p>
                      ) : null}
                    </button>
                  ))}
                </div>
              </div>
            ) : null,
          )}
        </div>
      </aside>

      {selected ? (
        <div className="flex flex-1 flex-col bg-gray-50">
          <div className="border-b border-gray-200 bg-white px-6 py-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${CATEGORY_COLORS[selected.category] || 'bg-gray-100 text-gray-600'}`}>
                    {selected.category}
                  </span>
                  {selected.is_overridden ? (
                    <span className="flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                      <Tag size={10} />
                      Custom override active
                    </span>
                  ) : null}
                  {selected.runtime_purpose ? (
                    <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700">
                      {RUNTIME_META[selected.runtime_purpose]?.title || selected.runtime_purpose}
                    </span>
                  ) : null}
                </div>
                <h2 className="text-xl font-bold text-gray-900">{selected.label}</h2>
                <p className="mt-0.5 text-sm text-gray-500">{selected.description}</p>
                {selected.is_overridden && selected.updated_at ? (
                  <p className="mt-1 text-xs text-gray-400">
                    Last updated {fmt(selected.updated_at)} by {selected.updated_by}
                  </p>
                ) : null}
              </div>

              <div className="flex flex-shrink-0 items-center gap-2">
                <button
                  type="button"
                  onClick={() => openCyberAssistant({
                    mode: 'admin_runtime',
                    title: `${selected.label} Prompt Assistant`,
                    attachments: [{
                      type: 'admin_runtime',
                      resource_id: selected.id,
                      context_json: {
                        label: `Prompt: ${selected.label}`,
                        setting_key: selected.id,
                        setting_value: selected.description,
                        runtime_purpose: selected.runtime_purpose,
                        category: selected.category,
                      },
                    }],
                  })}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-violet-200 bg-violet-50 px-3 py-1.5 text-sm font-medium text-violet-700 hover:bg-violet-100 transition-colors"
                >
                  <MessageSquare size={13} />
                  Ask AI
                </button>
                {selected.is_overridden ? (
                  <button
                    onClick={() => setShowDefault(value => !value)}
                    className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 transition-colors hover:bg-gray-50"
                  >
                    <Info size={13} />
                    {showDefault ? 'Hide' : 'View'} Default
                  </button>
                ) : null}
                {selected.is_overridden ? (
                  <button
                    onClick={() => {
                      if (window.confirm('Reset to default? Your customization will be deleted.')) {
                        resetMutation.mutate(selected.id)
                      }
                    }}
                    disabled={resetMutation.isPending}
                    className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 text-sm text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50"
                  >
                    <RotateCcw size={13} />
                    Reset to Default
                  </button>
                ) : null}
                <button
                  onClick={() => saveMutation.mutate({ id: selected.id, content: draft })}
                  disabled={!isDirty || saveMutation.isPending}
                  className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
                >
                  {saved ? <CheckCircle2 size={13} /> : <Save size={13} />}
                  {saved ? 'Saved!' : 'Save Changes'}
                </button>
              </div>
            </div>

            {saveMutation.isError ? (
              <div className="mt-3 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
                <AlertCircle size={14} />
                {saveMutation.error?.response?.data?.detail || 'Save failed'}
              </div>
            ) : null}
          </div>

          <div className="space-y-4 px-6 py-4">
            {selectedRuntime ? (
              <RuntimeBadge
                runtime={{
                  ...selectedRuntime,
                  title: RUNTIME_META[selected.runtime_purpose]?.title || selected.runtime_purpose,
                  detail: RUNTIME_META[selected.runtime_purpose]?.detail || '',
                }}
              />
            ) : null}

            {selected.used_by?.length ? (
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Used By</div>
                <div className="mt-3 space-y-2">
                  {selected.used_by.map(item => (
                    <div key={item} className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 text-sm text-gray-700">
                      {item}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {showDefault && selected.is_overridden ? (
              <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
                <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50 px-4 py-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Hardcoded Default
                  </span>
                  <button
                    onClick={() => {
                      setDraft(selected.default)
                      setShowDefault(false)
                    }}
                    className="text-xs font-medium text-blue-600 hover:text-blue-700"
                  >
                    Restore to editor
                  </button>
                </div>
                <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed text-gray-600">
                  {selected.default}
                </pre>
              </div>
            ) : null}
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-2 px-6 pb-4">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Prompt Content
              </label>
              <span className="text-xs text-gray-400">{draft.length} characters</span>
            </div>
            <textarea
              value={draft}
              onChange={event => setDraft(event.target.value)}
              spellCheck={false}
              className="flex-1 w-full resize-none rounded-lg border border-gray-200 bg-white p-4 font-mono text-sm leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-300"
              style={{ minHeight: '400px' }}
            />
            {isDirty ? (
              <p className="flex items-center gap-1 text-xs text-amber-600">
                <AlertCircle size={11} />
                Unsaved changes - click Save Changes to apply
              </p>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="flex flex-1 flex-col bg-gray-50">
          <div className="border-b border-gray-200 bg-white px-6 py-4">
            <div className="flex items-center gap-2">
              <Cpu size={16} className="text-violet-500" />
              <h2 className="text-lg font-semibold text-gray-900">Prompt and Model Routing</h2>
            </div>
            <p className="mt-1 text-sm text-gray-500">
              Prompts define instructions. The runtime map shows which live model route executes those prompts.
            </p>
          </div>

          <div className="p-6">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {runtimeSummary.map(item => (
                <RuntimeBadge
                  key={item.key}
                  runtime={{
                    ...item.runtime,
                    title: item.title,
                    detail: item.detail,
                  }}
                />
              ))}
            </div>

            <div className="mt-6 rounded-xl border border-gray-200 bg-white p-5 text-sm text-gray-600">
              Select a prompt to edit. The detail view will show which runtime route and live model that prompt family currently feeds.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
