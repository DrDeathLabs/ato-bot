import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Eye,
  EyeOff,
  MessageSquare,
  Key,
  RefreshCw,
  Save,
  Settings,
  Shield,
  Wifi,
  XCircle,
} from 'lucide-react'

import api from '../../api/client'
import { openCyberAssistant } from '../../components/cyberAssistant'

function fmt(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

const GROUPS = {
  Embeddings: [
    'embedding_provider',
    'embedding_model',
    'embedding_base_url',
    'embedding_api_key',
    'embedding_headers_json',
    'embedding_max_concurrency',
  ],
  Ollama: [
    'ollama_connection_mode',
    'ollama_base_url',
    'ollama_api_key',
    'ollama_headers_json',
    'ollama_reasoning_model',
    'ollama_vision_model',
    'ollama_screening_model',
    'ollama_classify_model',
    'ollama_reasoning_effort',
  ],
  Corpus: ['active_corpus_key'],
  'Voyage AI': ['voyage_api_key', 'voyage_model', 'voyage_base_url', 'voyage_max_concurrency', 'voyage_rate_limit_backoff_secs'],
  'Pipeline Thresholds': ['screening_mode', 'screening_threshold', 'expand_window_lines', 'expand_max_tokens'],
  'Batch & Timeout': [
    'screening_batch_size',
    'screening_max_concurrency',
    'screening_reasoning_effort',
    'screening_timeout_secs',
    'classify_max_concurrency',
    'classify_reasoning_effort',
    'classify_batch_size',
    'embed_batch_size',
    'classify_timeout_secs',
    'embed_timeout_secs',
    'max_retries',
    'retry_delay_secs',
  ],
}

const SELECT_OPTIONS = {
  ollama_connection_mode: [
    { value: 'local', label: 'Local' },
    { value: 'cloud', label: 'Cloud' },
    { value: 'custom', label: 'Custom' },
  ],
  embedding_provider: [
    { value: 'voyage', label: 'Voyage' },
    { value: 'ollama', label: 'Ollama' },
  ],
  screening_mode: [
    { value: 'llm', label: 'LLM Screening' },
    { value: 'heuristic', label: 'Legacy Heuristic' },
  ],
  ollama_reasoning_effort: [
    { value: 'none', label: 'None' },
    { value: 'low', label: 'Low' },
    { value: 'medium', label: 'Medium' },
    { value: 'high', label: 'High' },
  ],
  classify_reasoning_effort: [
    { value: 'none', label: 'None' },
    { value: 'low', label: 'Low' },
    { value: 'medium', label: 'Medium' },
    { value: 'high', label: 'High' },
  ],
  screening_reasoning_effort: [
    { value: 'none', label: 'None' },
    { value: 'low', label: 'Low' },
    { value: 'medium', label: 'Medium' },
    { value: 'high', label: 'High' },
  ],
}

function groupSettings(settings) {
  const grouped = {}
  const assigned = new Set()
  for (const [group, keys] of Object.entries(GROUPS)) {
    const items = settings.filter(setting => keys.includes(setting.key))
    if (items.length) {
      grouped[group] = items
      items.forEach(setting => assigned.add(setting.key))
    }
  }
  const other = settings.filter(setting => !assigned.has(setting.key))
  if (other.length) grouped.Other = other
  return grouped
}

const RUNTIME_LABELS = {
  assessment_reasoning: {
    title: 'Assessment reasoning',
    detail: 'Objective evaluation, challenge review, and assessment narratives.',
  },
  ai_assist_notes: {
    title: 'AI assist notes',
    detail: 'Notes, rationales, and short analyst-writing helpers.',
  },
  dissent_chat: {
    title: 'Dissent chat',
    detail: 'Interactive discussion panel for challenged assessment findings.',
  },
  chat_general: {
    title: 'Cyber assistant - general',
    detail: 'Global cyber and compliance chat opened from anywhere in the app.',
  },
  chat_workspace: {
    title: 'Cyber assistant - workspace',
    detail: 'Project and assessment scoped conversations.',
  },
  chat_control: {
    title: 'Cyber assistant - control',
    detail: 'Control, finding, and dissent conversations with attached evidence context.',
  },
  chat_remediation: {
    title: 'Cyber assistant - remediation',
    detail: 'Remediation package, artifact, and gap-planning conversations.',
  },
  chat_evidence: {
    title: 'Cyber assistant - evidence',
    detail: 'Evidence and citation-focused conversations.',
  },
  chat_vision: {
    title: 'Cyber assistant - vision',
    detail: 'One-time image and screenshot context derivation for assistant file uploads.',
  },
  chat_admin_explainer: {
    title: 'Cyber assistant - admin',
    detail: 'Explanations of AI runtime and admin settings.',
  },
  document_tagging: {
    title: 'Document tagging',
    detail: 'Older full-document control tagging and chunk mapping flows.',
  },
  procedure_categorization: {
    title: 'Procedure categorization',
    detail: 'Enterprise procedure auto-categorization before tagging.',
  },
  remediation_generation: {
    title: 'Remediation generation',
    detail: 'Remediation guides, artifact templates, and supplement generation.',
  },
  test_dataset_generation: {
    title: 'Test dataset generation',
    detail: 'Fictitious package planning and generated test evidence bundles.',
  },
  ingestion_screening: {
    title: 'Ingestion screening',
    detail: 'Stage 2 candidate-relevance screening for parsed lines and cells.',
  },
  ingestion_classification: {
    title: 'Ingestion classification',
    detail: 'Stage 4 evidence-unit classification before embeddings.',
  },
  embeddings: {
    title: 'Embeddings',
    detail: 'Evidence indexing and retrieval query vectors.',
  },
}

function SecretField({ setting, onSave, isSaving }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [showValue, setShowValue] = useState(false)

  if (!editing) {
    return (
      <div className="flex items-center gap-2">
        <span className="flex-1 rounded border border-gray-200 bg-gray-50 px-3 py-1.5 font-mono text-sm text-gray-400">
          ********
        </span>
        <button
          onClick={() => setEditing(true)}
          className="rounded-lg border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-600 transition-colors hover:bg-blue-50"
        >
          Change
        </button>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <div className="relative flex-1">
        <input
          type={showValue ? 'text' : 'password'}
          value={draft}
          onChange={event => setDraft(event.target.value)}
          placeholder="Enter new value"
          className="w-full rounded-lg border border-blue-300 px-3 py-1.5 pr-9 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
          autoFocus
        />
        <button
          type="button"
          onClick={() => setShowValue(value => !value)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
        >
          {showValue ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
      <button
        onClick={() => {
          onSave(setting.key, draft)
          setEditing(false)
          setDraft('')
        }}
        disabled={!draft || isSaving}
        className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
      >
        {isSaving ? <RefreshCw size={12} className="animate-spin" /> : <Save size={12} />}
        Save
      </button>
      <button
        onClick={() => {
          setEditing(false)
          setDraft('')
        }}
        className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-500 transition-colors hover:bg-gray-50"
      >
        Cancel
      </button>
    </div>
  )
}

function PlainField({ setting, onSave, isSaving }) {
  const [draft, setDraft] = useState(setting.value ?? setting.default ?? '')
  const isDirty = draft !== (setting.value ?? setting.default ?? '')

  return (
    <div className="flex items-center gap-2">
      <input
        type="text"
        value={draft}
        onChange={event => setDraft(event.target.value)}
        className="flex-1 rounded-lg border border-gray-200 px-3 py-1.5 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
      />
      <button
        onClick={() => onSave(setting.key, draft)}
        disabled={!isDirty || isSaving}
        className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
      >
        {isSaving ? <RefreshCw size={12} className="animate-spin" /> : <Save size={12} />}
        Save
      </button>
    </div>
  )
}

function SelectField({ setting, options, onSave, isSaving }) {
  const [draft, setDraft] = useState(setting.value ?? setting.default ?? '')
  const isDirty = draft !== (setting.value ?? setting.default ?? '')

  return (
    <div className="flex items-center gap-2">
      <select
        value={draft}
        onChange={event => setDraft(event.target.value)}
        className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
      >
        {options.map(option => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <button
        onClick={() => onSave(setting.key, draft)}
        disabled={!isDirty || isSaving}
        className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
      >
        {isSaving ? <RefreshCw size={12} className="animate-spin" /> : <Save size={12} />}
        Save
      </button>
    </div>
  )
}

function TestResult({ result }) {
  if (!result) return null
  if (result.ok) {
    return (
      <div className="mt-2 flex items-start gap-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
        <CheckCircle size={15} className="mt-0.5 flex-shrink-0" />
        <div>
          <span className="font-medium">Connected</span>
          {result.base_url ? <span className="ml-2 text-green-600">{result.base_url}</span> : null}
          {result.model ? <div className="mt-1 text-xs">Model: {result.model}</div> : null}
          {result.available_models?.length ? (
            <div className="mt-1 text-xs">Available: {result.available_models.join(', ')}</div>
          ) : null}
        </div>
      </div>
    )
  }
  return (
    <div className="mt-2 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
      <XCircle size={15} className="mt-0.5 flex-shrink-0" />
      <div>
        <span className="font-medium">Connection failed</span>
        {result.error ? <div className="mt-1 font-mono text-xs">{result.error}</div> : null}
      </div>
    </div>
  )
}

export default function IngestionConfig() {
  const queryClient = useQueryClient()
  const [savingKey, setSavingKey] = useState(null)
  const [savedKey, setSavedKey] = useState(null)
  const [voyageResult, setVoyageResult] = useState(null)
  const [ollamaResult, setOllamaResult] = useState(null)
  const [embeddingResult, setEmbeddingResult] = useState(null)
  const [testingVoyage, setTestingVoyage] = useState(false)
  const [testingOllama, setTestingOllama] = useState(false)
  const [testingEmbedding, setTestingEmbedding] = useState(false)
  const [activatingCorpus, setActivatingCorpus] = useState(false)

  const { data: configData, isLoading: configLoading } = useQuery({
    queryKey: ['ingestion-config'],
    queryFn: () => api.get('/ingestion-config').then(response => response.data),
  })

  const { data: auditData, isLoading: auditLoading } = useQuery({
    queryKey: ['ingestion-config-audit'],
    queryFn: () => api.get('/ingestion-config/audit').then(response => response.data),
  })

  const { data: corpusData, isLoading: corpusLoading } = useQuery({
    queryKey: ['ingestion-corpora'],
    queryFn: () => api.get('/ingestion-config/corpora').then(response => response.data),
  })

  const { data: runtimeMapData, isLoading: runtimeMapLoading } = useQuery({
    queryKey: ['llm-runtime-map'],
    queryFn: () => api.get('/llm/runtime-map').then(response => response.data),
  })

  const saveMutation = useMutation({
    mutationFn: ({ key, value }) => api.put(`/ingestion-config/${key}`, { value }),
    onMutate: ({ key }) => setSavingKey(key),
    onSuccess: (_, { key }) => {
      queryClient.invalidateQueries(['ingestion-config'])
      queryClient.invalidateQueries(['ingestion-config-audit'])
      queryClient.invalidateQueries(['ingestion-corpora'])
      setSavingKey(null)
      setSavedKey(key)
      setTimeout(() => setSavedKey(null), 2000)
    },
    onError: () => setSavingKey(null),
  })

  const handleSave = (key, value) => saveMutation.mutate({ key, value })

  const activateCorpus = async corpusKey => {
    setActivatingCorpus(true)
    try {
      await api.post('/ingestion-config/corpora/activate', { corpus_key: corpusKey })
      queryClient.invalidateQueries(['ingestion-config'])
      queryClient.invalidateQueries(['ingestion-config-audit'])
      queryClient.invalidateQueries(['ingestion-corpora'])
    } finally {
      setActivatingCorpus(false)
    }
  }

  const testVoyage = async () => {
    setTestingVoyage(true)
    setVoyageResult(null)
    try {
      const { data } = await api.post('/ingestion-config/test/voyage')
      setVoyageResult(data)
    } catch (error) {
      setVoyageResult({ ok: false, error: error?.response?.data?.detail || error.message })
    } finally {
      setTestingVoyage(false)
    }
  }

  const testOllama = async () => {
    setTestingOllama(true)
    setOllamaResult(null)
    try {
      const { data } = await api.post('/ingestion-config/test/ollama')
      setOllamaResult(data)
    } catch (error) {
      setOllamaResult({ ok: false, error: error?.response?.data?.detail || error.message })
    } finally {
      setTestingOllama(false)
    }
  }

  const testEmbedding = async () => {
    setTestingEmbedding(true)
    setEmbeddingResult(null)
    try {
      const { data } = await api.post('/ingestion-config/test/embedding')
      setEmbeddingResult(data)
    } catch (error) {
      setEmbeddingResult({ ok: false, error: error?.response?.data?.detail || error.message })
    } finally {
      setTestingEmbedding(false)
    }
  }

  const settings = configData?.settings ?? []
  const auditEntries = auditData?.entries ?? []
  const grouped = groupSettings(settings)

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-blue-100 p-2">
            <Settings size={22} className="text-blue-700" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">AI Runtime Settings</h1>
            <p className="text-sm text-gray-500">
              Manage live model routing, provider endpoints, embeddings, corpus versions, and staged pipeline behavior.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => openCyberAssistant({
            mode: 'admin_runtime',
            title: 'AI Runtime Assistant',
            attachments: [{
              type: 'admin_runtime',
              resource_id: 'ai_runtime',
              context_json: {
                label: 'AI Runtime Settings',
                setting_key: 'ai_runtime',
                setting_value: 'Model routing, providers, embeddings, and pipeline behavior',
              },
            }],
          })}
          className="inline-flex items-center gap-1.5 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-xs font-medium text-violet-700 hover:bg-violet-100 transition-colors"
        >
          <MessageSquare size={13} />
          Ask AI
        </button>
      </div>

      <div className="overflow-hidden rounded-xl border border-blue-200 bg-blue-50">
        <div className="px-5 py-3 text-sm text-blue-900">
          This page now controls more than ingestion. It is the app-wide AI runtime surface for assessment reasoning, AI assist, remediation generation, test dataset generation, ingestion screening/classification, and embeddings.
        </div>
      </div>

      {configLoading ? (
        <div className="py-6 text-center text-sm text-gray-400">Loading configuration...</div>
      ) : (
        Object.entries(grouped).map(([group, items]) => (
          <div key={group} className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <div className="flex items-center gap-2 border-b border-gray-200 bg-gray-50 px-5 py-3">
              {group === 'Embeddings' ? <Key size={14} className="text-purple-500" /> : null}
              {group === 'Voyage AI' ? <Key size={14} className="text-indigo-500" /> : null}
              {group === 'Ollama' ? <Shield size={14} className="text-teal-500" /> : null}
              {group === 'Corpus' ? <Shield size={14} className="text-emerald-500" /> : null}
              {group !== 'Embeddings' && group !== 'Voyage AI' && group !== 'Ollama' && group !== 'Corpus' ? (
                <Settings size={14} className="text-gray-400" />
              ) : null}
              <h2 className="text-sm font-semibold text-gray-700">{group}</h2>
            </div>
            {group === 'Embeddings' ? (
              <div className="border-b border-amber-200 bg-amber-50 px-5 py-3 text-xs text-amber-800">
                Switching the active embedding provider or model requires re-embedding stored evidence before retrieval can use the new embedding space safely.
              </div>
            ) : null}
            <div className="divide-y divide-gray-100">
              {items.map(setting => (
                <div key={`${setting.key}:${setting.value}`} className="px-5 py-4">
                  <div className="mb-2 flex items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-medium text-gray-800">{setting.key}</span>
                        {setting.is_secret ? (
                          <span className="flex items-center gap-1 rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-700">
                            <Key size={10} />
                            secret
                          </span>
                        ) : null}
                        {savedKey === setting.key ? (
                          <span className="flex items-center gap-1 text-xs text-green-600">
                            <CheckCircle size={12} />
                            Saved
                          </span>
                        ) : null}
                      </div>
                      {setting.description ? <p className="mt-0.5 text-xs text-gray-500">{setting.description}</p> : null}
                    </div>
                    {setting.default && !setting.is_secret ? (
                      <span className="flex-shrink-0 text-xs text-gray-400">
                        default: <code className="font-mono">{setting.default}</code>
                      </span>
                    ) : null}
                  </div>
                  {setting.is_secret ? (
                    <SecretField setting={setting} onSave={handleSave} isSaving={savingKey === setting.key} />
                  ) : SELECT_OPTIONS[setting.key] ? (
                    <SelectField
                      setting={setting}
                      options={SELECT_OPTIONS[setting.key]}
                      onSave={handleSave}
                      isSaving={savingKey === setting.key}
                    />
                  ) : (
                    <PlainField setting={setting} onSave={handleSave} isSaving={savingKey === setting.key} />
                  )}
                </div>
              ))}
            </div>
          </div>
        ))
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="flex items-center gap-2 border-b border-gray-200 bg-gray-50 px-5 py-3">
          <Shield size={14} className="text-emerald-500" />
          <h2 className="text-sm font-semibold text-gray-700">Corpus Versions</h2>
        </div>
        <div className="space-y-3 p-5">
          {corpusLoading ? (
            <div className="text-sm text-gray-400">Loading corpus versions...</div>
          ) : (
            (corpusData?.corpora ?? []).map(corpus => (
              <div key={corpus.corpus_key} className="flex items-center justify-between gap-4 rounded-lg border border-gray-200 px-4 py-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">{corpus.display_name}</span>
                    <span className="font-mono text-xs text-gray-500">{corpus.version}</span>
                    {corpus.is_active ? (
                      <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                        Active
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-xs text-gray-500">{corpus.description || corpus.corpus_key}</p>
                  <p className="mt-1 text-xs text-gray-400">Created: {fmt(corpus.created_at)}</p>
                </div>
                <button
                  onClick={() => activateCorpus(corpus.corpus_key)}
                  disabled={corpus.is_active || activatingCorpus}
                  className="rounded-lg border border-emerald-200 px-3 py-1.5 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-50 disabled:opacity-50"
                >
                  {corpus.is_active ? 'Selected' : 'Activate'}
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="flex items-center gap-2 border-b border-gray-200 bg-gray-50 px-5 py-3">
          <Wifi size={14} className="text-blue-500" />
          <h2 className="text-sm font-semibold text-gray-700">Connection Tests</h2>
        </div>
        <div className="grid grid-cols-1 gap-6 p-5 md:grid-cols-3">
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-sm font-medium text-gray-800">Active embedding provider</span>
              <button
                onClick={testEmbedding}
                disabled={testingEmbedding}
                className="flex items-center gap-1.5 rounded-lg border border-purple-200 bg-purple-50 px-3 py-1.5 text-sm font-medium text-purple-700 transition-colors hover:bg-purple-100 disabled:opacity-50"
              >
                {testingEmbedding ? <RefreshCw size={13} className="animate-spin" /> : <Wifi size={13} />}
                Test Embeddings
              </button>
            </div>
            <p className="mb-2 text-xs text-gray-400">Tests the currently configured embedding backend and model that ingestion and retrieval will use.</p>
            <TestResult result={embeddingResult} />
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-sm font-medium text-gray-800">Voyage AI</span>
              <button
                onClick={testVoyage}
                disabled={testingVoyage}
                className="flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-700 transition-colors hover:bg-indigo-100 disabled:opacity-50"
              >
                {testingVoyage ? <RefreshCw size={13} className="animate-spin" /> : <Wifi size={13} />}
                Test Voyage
              </button>
            </div>
            <p className="mb-2 text-xs text-gray-400">Tests the configured Voyage embedding endpoint using the stored key.</p>
            <TestResult result={voyageResult} />
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-sm font-medium text-gray-800">Ollama-compatible reasoning service</span>
              <button
                onClick={testOllama}
                disabled={testingOllama}
                className="flex items-center gap-1.5 rounded-lg border border-teal-200 bg-teal-50 px-3 py-1.5 text-sm font-medium text-teal-700 transition-colors hover:bg-teal-100 disabled:opacity-50"
              >
                {testingOllama ? <RefreshCw size={13} className="animate-spin" /> : <Wifi size={13} />}
                Test Ollama
              </button>
            </div>
            <p className="mb-2 text-xs text-gray-400">
              Validates the configured local or cloud Ollama-compatible endpoint and confirms the selected model is available.
            </p>
            <TestResult result={ollamaResult} />
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="flex items-center gap-2 border-b border-gray-200 bg-gray-50 px-5 py-3">
          <Shield size={14} className="text-violet-500" />
          <h2 className="text-sm font-semibold text-gray-700">Runtime Model Usage</h2>
          <span className="ml-auto text-xs text-gray-400">
            {runtimeMapData?.default_ollama_base_url ? runtimeMapData.default_ollama_base_url : 'model routing map'}
          </span>
        </div>
        <div className="border-b border-violet-100 bg-violet-50 px-5 py-3 text-xs text-violet-900">
          This is the live routing map the app is currently using. It shows which provider and model power each feature area, so assessment, ingestion, chat, remediation, and embeddings are easy to trace.
        </div>
        <div className="p-5">
          {runtimeMapLoading ? (
            <div className="text-sm text-gray-400">Loading model usage...</div>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {Object.entries(runtimeMapData?.routes ?? {}).map(([key, route]) => {
                const meta = RUNTIME_LABELS[key] || { title: key, detail: '' }
                return (
                  <div key={key} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-gray-900">{meta.title}</div>
                        <div className="mt-1 text-xs text-gray-500">{meta.detail}</div>
                      </div>
                      <span className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-gray-500">
                        {route.provider}
                      </span>
                    </div>
                    <div className="mt-3 space-y-1 text-xs">
                      <div className="text-gray-500">Model</div>
                      <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 font-mono text-gray-800">
                        {route.model || '-'}
                      </div>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
                      <div>
                        <div className="text-gray-500">Reasoning effort</div>
                        <div className="mt-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-gray-700">
                          {route.reasoning_effort || 'n/a'}
                        </div>
                      </div>
                      <div>
                        <div className="text-gray-500">Config source</div>
                        <div className="mt-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-gray-700">
                          {route.source || 'default'}
                        </div>
                      </div>
                    </div>
                    {route.base_url ? (
                      <div className="mt-3">
                        <div className="text-xs text-gray-500">Endpoint</div>
                        <div className="mt-1 rounded-lg border border-gray-200 bg-white px-3 py-2 font-mono text-[11px] text-gray-600">
                          {route.base_url}
                        </div>
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="flex items-center gap-2 border-b border-gray-200 bg-gray-50 px-5 py-3">
          <Clock size={14} className="text-gray-400" />
          <h2 className="text-sm font-semibold text-gray-700">Config Change Audit Log</h2>
          <span className="ml-auto text-xs text-gray-400">last 50 changes</span>
        </div>
        {auditLoading ? (
          <div className="py-6 text-center text-sm text-gray-400">Loading audit log...</div>
        ) : auditEntries.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-gray-400">No config changes recorded yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 bg-gray-50">
                <tr>
                  <th className="px-5 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Key</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Old Value</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">New Value</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Changed By</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {auditEntries.map(entry => (
                  <tr key={entry.id} className="transition-colors hover:bg-gray-50">
                    <td className="px-5 py-3">
                      <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs font-medium text-gray-800">
                        {entry.key}
                      </span>
                    </td>
                    <td className="max-w-[160px] truncate px-4 py-3 font-mono text-xs text-gray-500">{entry.old_value ?? '-'}</td>
                    <td className="max-w-[160px] truncate px-4 py-3 font-mono text-xs text-gray-800">{entry.new_value ?? '-'}</td>
                    <td className="px-4 py-3 text-xs text-gray-600">{entry.changed_by ?? 'system'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-500">{fmt(entry.changed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="flex items-center gap-2 border-b border-gray-200 bg-gray-50 px-5 py-3">
          <AlertTriangle size={14} className="text-amber-500" />
          <h2 className="text-sm font-semibold text-gray-700">Pipeline and Runtime Health</h2>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm text-gray-500">
            Use the document management surfaces to view run history, reprocess documents, and resume failed ingestion runs. Use the prompt manager for prompt text and this page for the live models and providers that execute those prompts.
          </p>
          <div className="mt-3 flex items-center gap-4 text-xs text-gray-400">
            <span className="flex items-center gap-1">
              <CheckCircle size={12} className="text-green-500" />
              Embeddings: {embeddingResult ? (embeddingResult.ok ? 'Connected' : 'Error') : 'Not tested'}
            </span>
            <span className="flex items-center gap-1">
              <CheckCircle size={12} className="text-green-500" />
              Voyage: {voyageResult ? (voyageResult.ok ? 'Connected' : 'Error') : 'Not tested'}
            </span>
            <span className="flex items-center gap-1">
              <CheckCircle size={12} className="text-green-500" />
              Ollama: {ollamaResult ? (ollamaResult.ok ? 'Connected' : 'Error') : 'Not tested'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
