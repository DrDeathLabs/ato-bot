import { useRef, useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload, File, Trash2, Play, ChevronRight, ChevronDown, Settings, AlertCircle, Pause, RotateCcw, Pencil, Check, X, StickyNote, ClipboardList, Maximize2, Download, ArrowUpDown, ArrowUp, ArrowDown, Building2, Link2, Unlink, BookOpen, Globe, FlaskConical, BarChart2, MessageSquare, ShieldCheck } from 'lucide-react'
import api from '../api/client'
import SystemProfile from './SystemProfile'
import DocumentExplorer from '../components/DocumentExplorer'
import DocumentPipelineReport from '../components/DocumentPipelineReport'
import { openCyberAssistant } from '../components/cyberAssistant'
import { useFeature } from '../components/FeatureRegistry'

// ── Expanding Textarea ─────────────────────────────────────────────────────────
// Preview textarea that opens a centered modal overlay for comfortable editing
function ExpandingTextarea({ value, onChange, className = '', placeholder = '', rows, disabled, readOnly, ...props }) {
  const [open, setOpen] = useState(false)

  const handleOpen = () => {
    if (disabled || readOnly) return
    setOpen(true)
  }

  const handleClose = () => setOpen(false)

  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) handleClose()
  }

  return (
    <>
      {/* Read-only preview textarea — clicking opens modal */}
      <div className={`relative group ${className}`}>
        <textarea
          readOnly
          value={value || ''}
          placeholder={placeholder}
          rows={rows || 3}
          onClick={handleOpen}
          disabled={disabled}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none bg-white cursor-pointer hover:border-blue-300 transition-colors"
          {...props}
        />
        {!disabled && !readOnly && (
          <button
            type="button"
            onClick={handleOpen}
            className="absolute top-1.5 right-1.5 p-0.5 text-gray-300 group-hover:text-blue-400 transition-colors"
            tabIndex={-1}
            title="Expand editor"
          >
            <Maximize2 size={12} />
          </button>
        )}
      </div>

      {/* Modal overlay */}
      {open && (
        <div
          className="fixed inset-0 z-[9999] bg-black/50 flex items-center justify-center p-4"
          onClick={handleBackdrop}
        >
          <div className="bg-white rounded-xl shadow-2xl flex flex-col w-full max-w-2xl" style={{ width: 'min(600px, 90vw)' }}>
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-700 truncate">
                {placeholder || 'Edit text'}
              </span>
              <button
                type="button"
                onClick={handleClose}
                className="text-gray-400 hover:text-gray-600 transition-colors ml-4 flex-shrink-0"
              >
                <X size={16} />
              </button>
            </div>
            {/* Large textarea */}
            <div className="px-5 py-4">
              <textarea
                autoFocus
                value={value || ''}
                onChange={onChange}
                placeholder={placeholder}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-300"
                style={{ minHeight: '50vh' }}
              />
            </div>
            {/* Footer */}
            <div className="flex justify-end px-5 py-3 border-t border-gray-100">
              <button
                type="button"
                onClick={handleClose}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

const STATUS_DOT = {
  pending: 'bg-gray-400',
  processing: 'bg-yellow-400 animate-pulse',
  complete: 'bg-amber-400',
  queued: 'bg-purple-400 animate-pulse',
  indexing: 'bg-blue-400 animate-pulse',
  indexed: 'bg-green-500',
  failed: 'bg-red-500',
  index_failed: 'bg-orange-500',
}

const fmt12hr = (dt) => {
  if (!dt) return '—'
  return new Date(dt).toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  })
}

const fmtDuration = (started, completed) => {
  if (!started || !completed) return null
  const secs = Math.round((new Date(completed) - new Date(started)) / 1000)
  if (secs < 60) return `${secs}s`
  const m = Math.floor(secs / 60), s = secs % 60
  if (m < 60) return s > 0 ? `${m}m ${s}s` : `${m}m`
  const h = Math.floor(m / 60), rm = m % 60
  return rm > 0 ? `${h}h ${rm}m` : `${h}h`
}

const isAssessmentReasoningModel = (model) => {
  const name = (model || '').toLowerCase()
  return name && !name.includes('embed') && !name.includes('embedding') && !name.includes('nomic-embed')
}

const formatOllamaModelLabel = (model) => {
  const labels = {
    'gpt-oss:120b-cloud': 'GPT-OSS 120B Cloud',
    'gpt-oss:20b-cloud': 'GPT-OSS 20B Cloud',
    'qwen3.5:cloud': 'Qwen 3.5 Cloud',
  }
  return labels[model] || model
}

export default function ProjectDetail() {
  const experimentalCatoEnabled = useFeature('cato_dashboard')
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const fileRef = useRef()
  const [startConfig, setStartConfig] = useState({
    llm_provider: 'ollama',
    llm_model: '',
    context_strategy: 'rag',
    ollama_num_ctx: 32768,
    skip_stage3: false,
    carry_forward_compliant: true,
  })
  const [showStartModal, setShowStartModal] = useState(false)

  // Inline edit state per assessment: { [id]: { name, notes, editingName, editingNotes } }
  const [edits, setEdits] = useState({})
  const getEdit = (a) => edits[a.id] || { name: a.name || '', notes: a.notes || '', editingName: false, editingNotes: false }
  const setEdit = (aId, patch) => setEdits((prev) => ({ ...prev, [aId]: { ...getEdit({ id: aId }), ...patch } }))

  const { data: project } = useQuery({
    queryKey: ['project', id],
    queryFn: () => api.get(`/projects/${id}`).then((r) => r.data),
  })
  const { data: documents = [], refetch: refetchDocs } = useQuery({
    queryKey: ['documents', id],
    queryFn: () => api.get(`/projects/${id}/documents`).then((r) => r.data),
    refetchInterval: (query) => query.state.data?.some((d) => ['processing', 'indexing', 'queued', 'pending'].includes(d.parse_status)) ? 1000 : false,
  })
  const hasIndexing = documents.some(d => d.parse_status === 'indexing')
  const hasProcessing = documents.some(d => d.parse_status === 'processing')
  const { data: indexingProgress = {} } = useQuery({
    queryKey: ['indexing-progress', id],
    queryFn: () => api.get(`/projects/${id}/documents/indexing-progress`).then(r => r.data),
    enabled: hasIndexing,
    refetchInterval: hasIndexing ? 2000 : false,
  })
  const { data: processingProgress = {} } = useQuery({
    queryKey: ['processing-progress', id],
    queryFn: () => api.get(`/projects/${id}/documents/processing-progress`).then(r => r.data),
    enabled: hasProcessing,
    refetchInterval: hasProcessing ? 1000 : false,
  })
  const { data: assessments = [] } = useQuery({
    queryKey: ['assessments', id],
    queryFn: () => api.get(`/projects/${id}/assessments`).then((r) => r.data),
    refetchInterval: (query) => query.state.data?.some(a => ['running', 'paused'].includes(a.status)) ? 4000 : false,
  })
  const latestCompletedAssessment = [...assessments]
    .filter((a) => a.status === 'complete')
    .sort((a, b) => new Date(b.completed_at || b.started_at || 0) - new Date(a.completed_at || a.started_at || 0))[0]
  const { data: oscalExportStatus = [] } = useQuery({
    queryKey: ['oscal-export-status', id, latestCompletedAssessment?.id],
    queryFn: () =>
      api
        .get(`/projects/${id}/assessments/${latestCompletedAssessment.id}/reports/oscal/status`)
        .then((r) => r.data),
    enabled: !!latestCompletedAssessment?.id,
  })

  // Auto-collapse doc list when docs are present on first load
  useEffect(() => { if (documents.length > 0) setDocsCollapsed(true) }, [documents.length > 0])

  // Common control providers
  const { data: linkedProviders = [], refetch: refetchLinked } = useQuery({
    queryKey: ['project-cc-providers', id],
    queryFn: () => api.get(`/common-controls/projects/${id}/providers`).then(r => r.data),
  })
  const { data: allProviders = [] } = useQuery({
    queryKey: ['cc-providers'],
    queryFn: () => api.get('/common-controls/providers').then(r => r.data),
  })
  const linkProviderMut = useMutation({
    mutationFn: (pid) => api.post(`/common-controls/projects/${id}/providers/${pid}`),
    onSuccess: () => refetchLinked(),
  })
  const unlinkProviderMut = useMutation({
    mutationFn: (pid) => api.delete(`/common-controls/projects/${id}/providers/${pid}`),
    onSuccess: () => refetchLinked(),
  })

  const { data: ollamaInfo, isError: ollamaError } = useQuery({
    queryKey: ['ollama-models'],
    queryFn: () => api.get('/llm/ollama/models').then((r) => r.data),
    enabled: showStartModal && startConfig.llm_provider === 'ollama',
    retry: false,
  })
  const selectedOllamaModel = startConfig.llm_model || ollamaInfo?.assessment_default || ollamaInfo?.default || 'gpt-oss:120b-cloud'
  const defaultOllamaModel = ollamaInfo?.assessment_default || ollamaInfo?.default || 'gpt-oss:120b-cloud'
  const ollamaAssessmentModels = Array.from(new Set([
    selectedOllamaModel,
    ollamaInfo?.assessment_default,
    ollamaInfo?.default,
    ...(ollamaInfo?.models || []),
  ].filter(Boolean))).filter(isAssessmentReasoningModel)

  const { data: policyLibraries = [] } = useQuery({
    queryKey: ['ep-libraries'],
    queryFn: () => api.get('/enterprise-policies/libraries').then(r => r.data),
  })
  const { data: procedureLibraries = [] } = useQuery({
    queryKey: ['eproc-libraries'],
    queryFn: () => api.get('/enterprise-procedures/libraries').then(r => r.data),
  })

  const uploadMutation = useMutation({
    mutationFn: (file) => {
      const form = new FormData()
      form.append('file', file)
      return api.post(`/projects/${id}/documents`, form)
    },
    onSuccess: () => refetchDocs(),
  })

  const [rerunErrors, setRerunErrors] = useState({}) // { [docId]: errorMsg }
  const [explorerDoc, setExplorerDoc] = useState(null)   // doc object to show in explorer
  const [reportDoc, setReportDoc]     = useState(null)   // doc to show pipeline report for
  const [docsCollapsed, setDocsCollapsed] = useState(false)
  const [docSort, setDocSort] = useState('date_desc') // date_desc|date_asc|name_asc|name_desc
  const [docFilter, setDocFilter] = useState('all')   // all | user | ai

  const userDocs = documents.filter(d => !d.autogenerated)
  const aiDocs   = documents.filter(d => d.autogenerated)

  const deleteMutation = useMutation({
    mutationFn: (docId) => api.delete(`/projects/${id}/documents/${docId}`),
    onSuccess: () => refetchDocs(),
  })

  const deleteAllDocsMutation = useMutation({
    mutationFn: () => Promise.all(documents.map(d => api.delete(`/projects/${id}/documents/${d.id}`))),
    onSuccess: () => refetchDocs(),
  })

  const deleteAiDocsMutation = useMutation({
    mutationFn: () => Promise.all(aiDocs.map(d => api.delete(`/projects/${id}/documents/${d.id}`))),
    onSuccess: () => { refetchDocs(); if (docFilter === 'ai') setDocFilter('all') },
  })

  const reparseMutation = useMutation({
    mutationFn: (docId) => api.post(`/projects/${id}/documents/${docId}/reparse`),
    onSuccess: (_data, docId) => {
      setRerunErrors(prev => { const n = {...prev}; delete n[docId]; return n })
      refetchDocs()
    },
    onError: (err, docId) => {
      const detail = err.response?.data?.detail
      const msg = typeof detail === 'string' ? detail
        : Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('; ')
        : detail ? JSON.stringify(detail)
        : (err.message || 'Unknown error')
      setRerunErrors(prev => ({ ...prev, [docId]: msg }))
      refetchDocs()
    },
  })

  const reindexMutation = useMutation({
    mutationFn: (docId) => api.post(`/projects/${id}/documents/${docId}/reindex`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents', id] }),
  })

  const reindexAllMutation = useMutation({
    mutationFn: () => api.post(`/projects/${id}/documents/reindex-all`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents', id] }),
  })

  const rerunAllFailed = async () => {
    const failed = documents.filter(d => d.parse_status === 'failed')
    for (const d of failed) reparseMutation.mutate(d.id)
  }

  const startAssessment = useMutation({
    mutationFn: (config) => api.post(`/projects/${id}/assessments`, config),
    onSuccess: () => {
      qc.invalidateQueries(['assessments', id])
      setShowStartModal(false)
    },
  })

  const pauseAssessment = useMutation({
    mutationFn: (aId) => api.post(`/projects/${id}/assessments/${aId}/pause`),
    onSuccess: () => qc.invalidateQueries(['assessments', id]),
  })
  const resumeAssessment = useMutation({
    mutationFn: (aId) => api.post(`/projects/${id}/assessments/${aId}/resume`),
    onSuccess: () => qc.invalidateQueries(['assessments', id]),
  })
  const deleteAssessment = useMutation({
    mutationFn: (aId) => api.delete(`/projects/${id}/assessments/${aId}`),
    onSuccess: () => qc.invalidateQueries(['assessments', id]),
  })
  const updateAssessment = useMutation({
    mutationFn: ({ aId, patch }) => api.patch(`/projects/${id}/assessments/${aId}`, patch),
    onSuccess: (res, { aId }) => {
      qc.invalidateQueries(['assessments', id])
      setEdit(aId, { editingName: false, editingNotes: false, name: res.data.name || '', notes: res.data.notes || '' })
    },
  })

  const [confirmDeleteProject, setConfirmDeleteProject] = useState(false)
  const deleteProject = useMutation({
    mutationFn: () => api.delete(`/projects/${id}`),
    onSuccess: () => navigate('/projects'),
  })

  const [dragging, setDragging] = useState(false)
  const [downloadingOscalKind, setDownloadingOscalKind] = useState(null)

  const handleFileChange = (e) => {
    for (const file of e.target.files) uploadMutation.mutate(file)
  }

  const downloadDoc = async (doc) => {
    try {
      const res = await api.get(`/projects/${id}/documents/${doc.id}/download`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = doc.filename
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('Download failed — file may no longer exist on disk.')
    }
  }

  const [downloadingAll, setDownloadingAll] = useState(false)
  const downloadAllDocs = async () => {
    setDownloadingAll(true)
    try {
      const res = await api.get(`/projects/${id}/documents/download-all`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `project-${id}-documents.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('Download failed.')
    } finally {
      setDownloadingAll(false)
    }
  }

  const downloadOscalExport = async (kind) => {
    if (!latestCompletedAssessment?.id) return
    setDownloadingOscalKind(kind)
    try {
      const filenameMap = {
        ssp: `assessment_${latestCompletedAssessment.id}_oscal_ssp.json`,
        'assessment-plan': `assessment_${latestCompletedAssessment.id}_oscal_assessment_plan.json`,
        'assessment-results': `assessment_${latestCompletedAssessment.id}_oscal_assessment_results.json`,
        poam: `assessment_${latestCompletedAssessment.id}_oscal_poam.json`,
      }
      const filename = filenameMap[kind] || `assessment_${latestCompletedAssessment.id}_oscal_export.json`
      const res = await api.get(
        `/projects/${id}/assessments/${latestCompletedAssessment.id}/reports/oscal/${kind}`,
        { responseType: 'blob' }
      )
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      const detail = err.response?.data?.detail?.message || err.response?.data?.detail || 'OSCAL export failed.'
      alert(typeof detail === 'string' ? detail : 'OSCAL export failed.')
    } finally {
      setDownloadingOscalKind(null)
    }
  }

  // Recursively collect all files from a FileSystemEntry (handles folders + subfolders)
  const collectFiles = (entry) => new Promise((resolve) => {
    if (entry.isFile) {
      entry.file(file => resolve([file]), () => resolve([]))
    } else if (entry.isDirectory) {
      const reader = entry.createReader()
      const readAll = (accumulated) => {
        reader.readEntries(async (batch) => {
          if (batch.length === 0) {
            const nested = await Promise.all(accumulated.map(collectFiles))
            resolve(nested.flat())
          } else {
            readAll([...accumulated, ...batch])
          }
        }, () => resolve([]))
      }
      readAll([])
    } else {
      resolve([])
    }
  })

  const handleDrop = async (e) => {
    e.preventDefault()
    setDragging(false)
    const items = Array.from(e.dataTransfer.items)
    const entries = items.map(i => i.webkitGetAsEntry?.()).filter(Boolean)
    if (entries.length > 0) {
      // Use FileSystem API — supports folders and subfolders
      const nested = await Promise.all(entries.map(collectFiles))
      for (const file of nested.flat()) uploadMutation.mutate(file)
    } else {
      // Fallback for browsers without FileSystem API
      for (const file of Array.from(e.dataTransfer.files)) uploadMutation.mutate(file)
    }
  }

  const handleDragOver = (e) => { e.preventDefault(); setDragging(true) }
  const handleDragLeave = (e) => { if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false) }

  const saveName = (a) => {
    const name = (getEdit(a).name || '').trim() || null
    updateAssessment.mutate({ aId: a.id, patch: { name } })
  }
  const saveNotes = (a) => {
    const notes = (getEdit(a).notes || '').trim() || null
    updateAssessment.mutate({ aId: a.id, patch: { notes } })
  }

  if (!project) return <div className="p-8 text-gray-600">Loading...</div>

  const assessmentResultsStatus = oscalExportStatus.find((row) => row.export_kind === 'assessment-results')
  const assessmentPlanStatus = oscalExportStatus.find((row) => row.export_kind === 'assessment-plan')
  const poamStatus = oscalExportStatus.find((row) => row.export_kind === 'poam')
  const sspStatus = oscalExportStatus.find((row) => row.export_kind === 'ssp')
  const statusBadge = (status) => {
    if (status === 'valid') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
    if (status === 'invalid') return 'border-red-200 bg-red-50 text-red-700'
    if (status === 'error') return 'border-red-200 bg-red-50 text-red-700'
    return 'border-gray-200 bg-gray-50 text-gray-600'
  }

  return (
    <div className="p-8 max-w-5xl">
      {/* Confirm delete project modal */}
      {confirmDeleteProject && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-sm shadow-2xl">
            <h2 className="text-lg font-bold text-gray-900 mb-2">Delete Project?</h2>
            <p className="text-sm text-gray-600 mb-1">
              This will permanently delete <span className="font-semibold">{project.name}</span> and all associated data:
            </p>
            <ul className="text-sm text-gray-500 list-disc ml-5 mb-5 space-y-0.5">
              <li>All documents and embeddings</li>
              <li>All assessments and findings</li>
              <li>All control overrides and activity logs</li>
            </ul>
            <p className="text-sm font-medium text-red-600 mb-4">This action cannot be undone.</p>
            <div className="flex gap-3">
              <button onClick={() => setConfirmDeleteProject(false)}
                className="flex-1 border rounded-lg py-2 text-sm hover:bg-gray-50">Cancel</button>
              <button
                onClick={() => deleteProject.mutate()}
                disabled={deleteProject.isPending}
                className="flex-1 bg-red-600 text-white rounded-lg py-2 text-sm hover:bg-red-700 disabled:opacity-50"
              >
                {deleteProject.isPending ? 'Deleting...' : 'Delete Project'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{project.name}</h1>
          <p className="text-gray-500 text-sm mt-1">
            {project.impact_baseline.toUpperCase()} baseline
            {project.system_type && ` · ${project.system_type}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => openCyberAssistant({
              mode: 'workspace',
              title: `${project.name} Assistant`,
              projectId: Number(id),
              attachments: [
                { type: 'project', resource_id: String(id), context_json: {} },
              ],
            })}
            className="flex items-center gap-2 border border-violet-300 text-violet-600 px-4 py-2 rounded-lg text-sm font-medium hover:bg-violet-50 transition-colors"
          >
            <MessageSquare size={16} />
            Ask AI
          </button>
          <button
            onClick={() => setConfirmDeleteProject(true)}
            className="flex items-center gap-2 border border-red-200 text-red-500 px-3 py-2 rounded-lg text-sm font-medium hover:bg-red-50 transition-colors"
            title="Delete project"
          >
            <Trash2 size={15} />
            Delete
          </button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr] mb-6">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">ATO Workspace</p>
              <h2 className="mt-1 text-lg font-semibold text-gray-900">Assessment and authorization work</h2>
              <p className="mt-1 text-sm text-gray-500">
                Keep the assessor workflow here: evidence review, datasets, assessment policy, workbench, and formal assessment runs.
              </p>
            </div>
            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
              ATO
            </span>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              onClick={() => navigate(`/projects/${id}/audit-log`)}
              className="flex items-center gap-2 border border-gray-300 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              <ClipboardList size={16} />
              Audit Trail
            </button>
            <button
              onClick={() => navigate(`/projects/${id}/test-dataset`)}
              className="flex items-center gap-2 border border-violet-300 text-violet-600 px-4 py-2 rounded-lg text-sm font-medium hover:bg-violet-50 transition-colors"
            >
              <FlaskConical size={16} />
              Test Dataset
            </button>
            <button
              onClick={() => navigate('/assessment-policy')}
              className="flex items-center gap-2 border border-blue-300 text-blue-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-50 transition-colors"
            >
              <BarChart2 size={16} />
              Assessment Policy
            </button>
            <button
              onClick={() => navigate(`/projects/${id}/ssp-workbench`)}
              className="flex items-center gap-2 border border-emerald-300 text-emerald-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-emerald-50 transition-colors"
            >
              <File size={16} />
              SSP Workbench
            </button>
            <button
              onClick={() => setShowStartModal(true)}
              disabled={documents.length === 0 || documents.some(d => d.parse_status === 'processing')}
              className="flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-40 transition-colors"
            >
              <Play size={16} />
              Start Assessment
            </button>
          </div>
          <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50/70 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">OSCAL Exports</p>
                <p className="mt-1 text-sm text-gray-600">
                  {latestCompletedAssessment
                    ? `Use the latest completed assessment (#${latestCompletedAssessment.project_run_number}) as the formal OSCAL export source.`
                    : 'Complete an assessment to enable NIST-aligned OSCAL exports and validation status.'}
                </p>
              </div>
              {latestCompletedAssessment && (
                <span className="rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs font-semibold text-gray-700">
                  Assessment #{latestCompletedAssessment.project_run_number}
                </span>
              )}
            </div>
            {latestCompletedAssessment ? (
              <>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    onClick={() => downloadOscalExport('ssp')}
                    disabled={downloadingOscalKind !== null}
                    className="flex items-center gap-2 border border-emerald-300 text-emerald-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-emerald-50 disabled:opacity-50 transition-colors"
                  >
                    <Download size={16} />
                    {downloadingOscalKind === 'ssp' ? 'Exporting…' : 'SSP'}
                  </button>
                  <button
                    onClick={() => downloadOscalExport('assessment-plan')}
                    disabled={downloadingOscalKind !== null}
                    className="flex items-center gap-2 border border-indigo-300 text-indigo-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-50 disabled:opacity-50 transition-colors"
                  >
                    <Download size={16} />
                    {downloadingOscalKind === 'assessment-plan' ? 'Exporting…' : 'Assessment Plan'}
                  </button>
                  <button
                    onClick={() => downloadOscalExport('assessment-results')}
                    disabled={downloadingOscalKind !== null}
                    className="flex items-center gap-2 border border-sky-300 text-sky-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-sky-50 disabled:opacity-50 transition-colors"
                  >
                    <Download size={16} />
                    {downloadingOscalKind === 'assessment-results' ? 'Exporting…' : 'Assessment Results'}
                  </button>
                  <button
                    onClick={() => downloadOscalExport('poam')}
                    disabled={downloadingOscalKind !== null}
                    className="flex items-center gap-2 border border-amber-300 text-amber-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-amber-50 disabled:opacity-50 transition-colors"
                  >
                    <Download size={16} />
                    {downloadingOscalKind === 'poam' ? 'Exporting…' : 'POA&M'}
                  </button>
                </div>
                <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-gray-800">SSP</p>
                      <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${statusBadge(sspStatus?.status)}`}>
                        {sspStatus?.status || 'not run'}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      {sspStatus?.summary || 'No validation run recorded yet.'}
                    </p>
                  </div>
                  <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-gray-800">Assessment Plan</p>
                      <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${statusBadge(assessmentPlanStatus?.status)}`}>
                        {assessmentPlanStatus?.status || 'not run'}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      {assessmentPlanStatus?.summary || 'No validation run recorded yet.'}
                    </p>
                  </div>
                  <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-gray-800">Assessment Results</p>
                      <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${statusBadge(assessmentResultsStatus?.status)}`}>
                        {assessmentResultsStatus?.status || 'not run'}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      {assessmentResultsStatus?.summary || 'No validation run recorded yet.'}
                    </p>
                  </div>
                  <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-gray-800">POA&amp;M</p>
                      <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${statusBadge(poamStatus?.status)}`}>
                        {poamStatus?.status || 'not run'}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      {poamStatus?.summary || 'No validation run recorded yet.'}
                    </p>
                  </div>
                </div>
              </>
            ) : null}
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">System Knowledge</p>
              <h2 className="mt-1 text-lg font-semibold text-gray-900">Architecture and tool inventory</h2>
              <p className="mt-1 text-sm text-gray-500">
                Review the system architecture, technology inventory, and provider responsibilities used to interpret assessment evidence.
              </p>
            </div>
            {experimentalCatoEnabled && (
              <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700">
                Experimental cATO
              </span>
            )}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              onClick={() => navigate(`/projects/${id}/architecture-tools`)}
              className="flex items-center gap-2 border border-sky-300 text-sky-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-sky-50 transition-colors"
            >
              <Building2 size={16} />
              Architecture & Tools
            </button>
            {experimentalCatoEnabled && (
              <>
                <button
                  onClick={() => navigate(`/projects/${id}/integrations`)}
                  className="flex items-center gap-2 border border-indigo-300 text-indigo-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-50 transition-colors"
                >
                  <Globe size={16} />
                  Experimental Integrations
                </button>
                <button
                  onClick={() => navigate(`/projects/${id}/cato-dashboard`)}
                  className="flex items-center gap-2 border border-teal-300 text-teal-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-teal-50 transition-colors"
                >
                  <ShieldCheck size={16} />
                  Experimental cATO Dashboard
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* System Profile */}
      <div className="mb-6">
        <SystemProfile projectId={id} />
      </div>

      {/* Documents */}
      {(() => {
        const filteredDocs = docFilter === 'user' ? userDocs : docFilter === 'ai' ? aiDocs : documents
        const sortedDocs = [...filteredDocs].sort((a, b) => {
          if (docSort === 'date_desc') return new Date(b.created_at) - new Date(a.created_at)
          if (docSort === 'date_asc')  return new Date(a.created_at) - new Date(b.created_at)
          if (docSort === 'name_asc')  return a.filename.localeCompare(b.filename)
          if (docSort === 'name_desc') return b.filename.localeCompare(a.filename)
          return 0
        })
        const SortBtn = ({ field, label }) => {
          const isDate = field === 'date'
          const asc = field === 'name' ? 'name_asc' : 'date_asc'
          const desc = field === 'name' ? 'name_desc' : 'date_desc'
          const active = docSort === asc || docSort === desc
          const Icon = active ? (docSort === asc ? ArrowUp : ArrowDown) : ArrowUpDown
          return (
            <button onClick={() => setDocSort(docSort === desc ? asc : desc)}
              className={`flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors ${active ? 'border-blue-300 text-blue-600 bg-blue-50' : 'border-gray-200 text-gray-400 hover:text-gray-600'}`}>
              <Icon size={10} />{label}
            </button>
          )
        }
        return (
        <div className="bg-white rounded-xl border border-gray-200 mb-6">
          {/* Header — always visible */}
          <div className="flex items-center justify-between px-6 py-4 pb-3">
            <button onClick={() => setDocsCollapsed(c => !c)}
              className="flex items-center gap-2 font-semibold text-gray-900 hover:text-gray-700">
              <ChevronDown size={16} className={`text-gray-400 transition-transform ${docsCollapsed ? '-rotate-90' : ''}`} />
              Documents ({documents.length})
            </button>
            <div className="flex items-center gap-2">
              {/* Indexing status counter */}
              {documents.length > 0 && (() => {
                const total      = documents.length
                const indexed    = documents.filter(d => d.parse_status === 'indexed').length
                const processing = documents.filter(d => ['processing', 'indexing', 'queued', 'pending'].includes(d.parse_status)).length
                const failed     = documents.filter(d => ['failed', 'index_failed'].includes(d.parse_status)).length
                const allDone    = indexed === total
                return (
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    allDone      ? 'bg-green-50 text-green-700' :
                    processing > 0 ? 'bg-blue-50 text-blue-700' :
                    failed > 0   ? 'bg-red-50 text-red-700' :
                    'bg-gray-100 text-gray-600'
                  }`}>
                    {indexed}/{total} indexed
                    {processing > 0 ? ` · ${processing} processing` : ''}
                    {failed > 0 ? ` · ${failed} failed` : ''}
                  </span>
                )
              })()}
              {!docsCollapsed && documents.length > 0 && (
                <>
                  <SortBtn field="date" label="Date" />
                  <SortBtn field="name" label="Name" />
                </>
              )}
              {documents.some(d => ['complete', 'index_failed'].includes(d.parse_status)) && (
                <button onClick={() => reindexAllMutation.mutate()}
                  disabled={reindexAllMutation.isPending}
                  title="Queue control tagging for all unindexed documents"
                  className="flex items-center gap-1.5 text-xs text-blue-700 border border-blue-300 bg-blue-50 px-2.5 py-1.5 rounded-lg hover:bg-blue-100 disabled:opacity-50 transition-colors">
                  <RotateCcw size={12} className={reindexAllMutation.isPending ? 'animate-spin' : ''} />Index All
                </button>
              )}
              {documents.some(d => d.parse_status === 'failed') && (
                <button onClick={rerunAllFailed} disabled={reparseMutation.isPending}
                  className="flex items-center gap-1.5 text-xs text-amber-700 border border-amber-300 bg-amber-50 px-2.5 py-1.5 rounded-lg hover:bg-amber-100 disabled:opacity-50 transition-colors">
                  <RotateCcw size={12} className={reparseMutation.isPending ? 'animate-spin' : ''} />Rerun Failed
                </button>
              )}
              {docFilter === 'ai' && aiDocs.length > 0 && (
                <button onClick={() => { if (window.confirm(`Remove all ${aiDocs.length} AI-generated document${aiDocs.length !== 1 ? 's' : ''}? This restores your original document set.`)) deleteAiDocsMutation.mutate() }}
                  disabled={deleteAiDocsMutation.isPending}
                  className="flex items-center gap-1.5 text-xs text-purple-700 border border-purple-300 bg-purple-50 px-2.5 py-1.5 rounded-lg hover:bg-purple-100 disabled:opacity-50 transition-colors">
                  <Trash2 size={12} className={deleteAiDocsMutation.isPending ? 'animate-spin' : ''} />Remove AI Docs
                </button>
              )}
              {documents.length > 0 && (
                <button onClick={downloadAllDocs} disabled={downloadingAll}
                  title="Download all documents as ZIP"
                  className="flex items-center gap-1.5 text-xs text-gray-700 border border-gray-200 bg-gray-50 px-2.5 py-1.5 rounded-lg hover:bg-gray-100 disabled:opacity-50 transition-colors">
                  <Download size={12} className={downloadingAll ? 'animate-bounce' : ''} />Download All
                </button>
              )}
              {documents.length > 0 && docFilter !== 'ai' && (
                <button onClick={() => { if (window.confirm(`Delete all ${documents.length} documents? This cannot be undone.`)) deleteAllDocsMutation.mutate() }}
                  disabled={deleteAllDocsMutation.isPending}
                  className="flex items-center gap-1.5 text-xs text-red-600 border border-red-200 bg-red-50 px-2.5 py-1.5 rounded-lg hover:bg-red-100 disabled:opacity-50 transition-colors">
                  <Trash2 size={12} />Delete All
                </button>
              )}
              <button onClick={() => fileRef.current.click()}
                className="flex items-center gap-2 text-blue-700 text-sm font-medium hover:text-blue-800">
                <Upload size={16} />Upload
              </button>
            </div>
            <input ref={fileRef} type="file" multiple className="hidden" onChange={handleFileChange}
              accept=".pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.vsdx,.txt,.md,.png,.jpg,.jpeg" />
          </div>
          {/* Filter tabs */}
          {documents.length > 0 && (
            <div className="flex items-center gap-1 px-6 pb-3">
              {[
                { key: 'all',  label: 'All',           count: documents.length },
                { key: 'user', label: 'Uploaded',      count: userDocs.length },
                { key: 'ai',   label: 'AI Generated',  count: aiDocs.length },
              ].map(tab => (
                <button key={tab.key} onClick={() => setDocFilter(tab.key)}
                  className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full font-medium transition-colors ${
                    docFilter === tab.key
                      ? tab.key === 'ai' ? 'bg-purple-100 text-purple-800 border border-purple-300'
                        : 'bg-blue-100 text-blue-800 border border-blue-300'
                      : 'bg-gray-50 text-gray-500 border border-gray-200 hover:bg-gray-100'
                  }`}>
                  {tab.label}
                  <span className={`text-xs font-semibold px-1.5 py-0 rounded-full ${
                    docFilter === tab.key
                      ? tab.key === 'ai' ? 'bg-purple-200 text-purple-700' : 'bg-blue-200 text-blue-700'
                      : 'bg-gray-200 text-gray-500'
                  }`}>{tab.count}</span>
                </button>
              ))}
              {docFilter === 'ai' && aiDocs.length === 0 && (
                <span className="text-xs text-gray-400 italic ml-2">No AI-generated documents yet — run a Remediation Report to generate artifacts</span>
              )}
            </div>
          )}

          {/* Drop zone — always visible */}
          <div onDrop={handleDrop} onDragOver={handleDragOver} onDragLeave={handleDragLeave}
            onClick={() => fileRef.current.click()}
            className={`mx-6 mb-3 border border-dashed rounded-lg px-4 py-2 text-center text-xs cursor-pointer transition-colors ${dragging ? 'border-blue-400 text-blue-500 bg-blue-50' : 'border-gray-200 text-gray-400 hover:border-blue-300 hover:text-gray-500'}`}>
            <Upload size={12} className="inline mr-1 opacity-60" />
            {documents.length === 0 ? 'Drop files here or click to upload — PDF, Word, Excel, PowerPoint, Visio, images, text' : 'Drop files here or click to add more'}
          </div>

          {/* File list — collapsible */}
          {!docsCollapsed && documents.length > 0 && (
            <div className="px-6 pb-4">
              <div className="divide-y divide-gray-100 border border-gray-100 rounded-lg overflow-hidden">
                {sortedDocs.map((doc) => (
                  <div key={doc.id}>
                    <div className={`flex items-center gap-3 px-3 py-2 hover:bg-gray-50 ${doc.autogenerated ? 'bg-purple-50/30' : ''}`}>
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[doc.parse_status] || 'bg-gray-300'}`} />
                      <File size={15} className={`flex-shrink-0 ${doc.autogenerated ? 'text-purple-400' : 'text-gray-400'}`} />
                      {doc.parse_status === 'indexed' ? (
                        <button
                          onClick={() => setExplorerDoc(doc)}
                          className="flex-1 text-sm text-blue-700 hover:text-blue-900 hover:underline truncate min-w-0 text-left"
                          title={`View evidence index for ${doc.filename}`}
                        >
                          {doc.filename}
                        </button>
                      ) : (
                        <span className="flex-1 text-sm text-gray-700 truncate min-w-0" title={doc.filename}>{doc.filename}</span>
                      )}
                      {doc.autogenerated && (
                        <span className="flex-shrink-0 text-xs font-semibold px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-700 border border-purple-200">
                          AI
                        </span>
                      )}
                      {doc.autogenerated && (doc.source_assessment_run_number ?? doc.source_assessment_id) && (
                        <span className="flex-shrink-0 text-xs text-purple-400" title="Source assessment">
                          Run #{doc.source_assessment_run_number ?? doc.source_assessment_id}
                        </span>
                      )}
                      <span className="text-xs text-gray-400 flex-shrink-0">{new Date(doc.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                      <span className="text-xs text-gray-400 flex-shrink-0">{(doc.file_size_bytes / 1024).toFixed(0)} KB</span>
                      {doc.parse_status === 'processing' ? (
                        (() => {
                          const p = processingProgress[doc.id]
                          const STAGES = ['parse','screen','expand','classify','embed']
                          const STAGE_LABELS = { parse:'Parsing', screen:'Screening', expand:'Expanding', classify:'Classifying', embed:'Embedding' }
                          const activeStage = p?.stage || 'parse'
                          const pct = p?.pct ?? 0
                          return (
                            <div className="flex items-center gap-1.5 flex-shrink-0">
                              {/* 5-pip stage indicator */}
                              <div className="flex items-center gap-0.5">
                                {STAGES.map(s => {
                                  const stageKey = `stage_${s}`
                                  const stageStatus = p?.[stageKey]
                                  const isComplete = stageStatus === 'complete'
                                  const isActive = p?.stage === s && stageStatus === 'running'
                                  return (
                                    <div key={s} title={STAGE_LABELS[s]}
                                      className={`w-2 h-2 rounded-full transition-all ${
                                        isComplete ? 'bg-yellow-500' :
                                        isActive   ? 'bg-yellow-400 animate-pulse ring-2 ring-yellow-300' :
                                                     'bg-gray-200'
                                      }`} />
                                  )
                                })}
                              </div>
                              <span className="text-xs font-medium text-yellow-600 tabular-nums">
                                {p ? STAGE_LABELS[activeStage] || 'Processing' : 'Processing'}
                                {p?.lines_parsed > 0 && activeStage === 'screen' ? ` · ${p.lines_parsed}L` : ''}
                                {p?.evidence_units > 0 && ['classify','embed'].includes(activeStage) ? ` · ${p.evidence_units}U` : ''}
                              </span>
                            </div>
                          )
                        })()
                      ) : doc.parse_status === 'indexing' && indexingProgress[doc.id] ? (
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                          <div className="w-16 h-1.5 bg-blue-100 rounded-full overflow-hidden">
                            <div
                              className="h-1.5 bg-blue-500 rounded-full transition-all duration-500"
                              style={{ width: `${indexingProgress[doc.id].pct}%` }}
                            />
                          </div>
                          <span className="text-xs font-medium text-blue-600 tabular-nums">
                            {indexingProgress[doc.id].pct}%
                          </span>
                        </div>
                      ) : (
                        <span className={`text-xs font-medium flex-shrink-0 ${
                          doc.parse_status === 'failed' ? 'text-red-600' :
                          doc.parse_status === 'index_failed' ? 'text-orange-600' :
                          doc.parse_status === 'indexed' ? 'text-green-600' :
                          doc.parse_status === 'indexing' ? 'text-blue-500' :
                          doc.parse_status === 'queued' ? 'text-purple-600' :
                          doc.parse_status === 'complete' ? 'text-amber-600' :
                          'text-gray-500'
                        }`}>
                          {doc.parse_status === 'complete' ? 'Parsed (not indexed)' :
                           doc.parse_status === 'queued' ? 'In queue' :
                           doc.parse_status === 'indexing' ? 'Indexing...' :
                           doc.parse_status === 'indexed' ? 'Indexed' :
                           doc.parse_status === 'index_failed' ? 'Index Failed' :
                           doc.parse_status}
                        </span>
                      )}
                      {doc.parse_status === 'failed' && (
                        <button onClick={() => reparseMutation.mutate(doc.id)}
                          disabled={reparseMutation.isPending && reparseMutation.variables === doc.id}
                          title="Retry parsing"
                          className="flex items-center gap-1 text-xs text-amber-700 border border-amber-200 bg-amber-50 px-2 py-0.5 rounded hover:bg-amber-100 disabled:opacity-50 transition-colors flex-shrink-0">
                          <RotateCcw size={11} />Retry
                        </button>
                      )}
                      {['indexed', 'index_failed', 'complete'].includes(doc.parse_status) && (
                        <button onClick={() => reindexMutation.mutate(doc.id)}
                          disabled={reindexMutation.isPending && reindexMutation.variables === doc.id}
                          title="Re-run control tagging"
                          className="flex items-center gap-1 text-xs text-blue-700 border border-blue-200 bg-blue-50 px-2 py-0.5 rounded hover:bg-blue-100 disabled:opacity-50 transition-colors flex-shrink-0">
                          <RotateCcw size={11} />Re-index
                        </button>
                      )}
                      {doc.parse_status === 'indexed' && (
                        <button
                          onClick={() => setReportDoc(doc)}
                          title="View pipeline quality report"
                          className="text-gray-400 hover:text-indigo-500 transition-colors flex-shrink-0">
                          <BarChart2 size={14} />
                        </button>
                      )}
                      <button
                        onClick={() => openCyberAssistant({
                          mode: 'workspace',
                          title: `${doc.filename} Assistant`,
                          projectId: Number(id),
                          attachments: [{
                            type: 'document',
                            resource_id: String(doc.id),
                            context_json: {
                              label: `Document: ${doc.filename}`,
                              filename: doc.filename,
                              parse_status: doc.parse_status,
                            },
                          }],
                        })}
                        title="Ask AI about this document"
                        className="text-violet-500 hover:text-violet-700 transition-colors flex-shrink-0"
                      >
                        <MessageSquare size={14} />
                      </button>
                      <button onClick={() => downloadDoc(doc)} title="Download source file"
                        className="text-gray-400 hover:text-blue-500 transition-colors flex-shrink-0">
                        <Download size={14} />
                      </button>
                      <button onClick={() => deleteMutation.mutate(doc.id)}
                        className="text-gray-400 hover:text-red-500 transition-colors flex-shrink-0">
                        <Trash2 size={14} />
                      </button>
                    </div>
                    {rerunErrors[doc.id] && (
                      <div className="ml-8 mb-2 flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
                        <AlertCircle size={12} className="mt-0.5 flex-shrink-0" />
                        <span>{rerunErrors[doc.id]}</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        )
      })()}

      {/* Common Controls */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <Building2 size={16} className="text-blue-500" />
            Common Controls ({linkedProviders.length})
          </h2>
        </div>
        {linkedProviders.length > 0 && (
          <div className="space-y-2 mb-4">
            {linkedProviders.map(p => (
              <div key={p.id} className="flex items-center gap-3 p-2.5 rounded-lg border border-gray-100 bg-gray-50">
                <Building2 size={13} className="text-blue-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-gray-800">{p.name}</span>
                  <span className="ml-2 text-xs text-gray-400">{p.document_count} doc{p.document_count !== 1 ? 's' : ''}</span>
                  {p.control_families?.length > 0 && (
                    <span className="ml-2 text-xs text-gray-400">{p.control_families.join(', ')}</span>
                  )}
                </div>
                <button onClick={() => unlinkProviderMut.mutate(p.id)} title="Unlink provider"
                  className="p-1 text-gray-300 hover:text-red-500 transition-colors">
                  <Unlink size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
        {/* Enterprise Policies & Procedures — auto-applied to every assessment */}
        {(policyLibraries.length > 0 || procedureLibraries.length > 0) && (() => {
          const policyDocs = policyLibraries.reduce((s, l) => s + (l.document_count || 0), 0)
          const procDocs   = procedureLibraries.reduce((s, l) => s + (l.document_count || 0), 0)
          return (
            <div className="space-y-2 mb-4">
              {policyLibraries.length > 0 && (
                <div className="flex items-center gap-3 p-2.5 rounded-lg border border-emerald-100 bg-emerald-50">
                  <BookOpen size={13} className="text-emerald-500 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium text-gray-800">Enterprise Policies</span>
                    <span className="ml-2 text-xs text-gray-400">
                      {policyLibraries.length} librar{policyLibraries.length !== 1 ? 'ies' : 'y'} · {policyDocs} doc{policyDocs !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <span className="flex items-center gap-1 text-xs text-emerald-600 font-medium bg-emerald-100 px-2 py-0.5 rounded-full">
                    <Globe size={10} /> Auto-applied
                  </span>
                </div>
              )}
              {procedureLibraries.length > 0 && (
                <div className="flex items-center gap-3 p-2.5 rounded-lg border border-emerald-100 bg-emerald-50">
                  <ClipboardList size={13} className="text-emerald-500 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium text-gray-800">Enterprise Procedures</span>
                    <span className="ml-2 text-xs text-gray-400">
                      {procedureLibraries.length} librar{procedureLibraries.length !== 1 ? 'ies' : 'y'} · {procDocs} doc{procDocs !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <span className="flex items-center gap-1 text-xs text-emerald-600 font-medium bg-emerald-100 px-2 py-0.5 rounded-full">
                    <Globe size={10} /> Auto-applied
                  </span>
                </div>
              )}
            </div>
          )
        })()}

        {(() => {
          const linkedIds = new Set(linkedProviders.map(p => p.id))
          const available = allProviders.filter(p => !linkedIds.has(p.id))
          if (available.length === 0) return null
          return (
            <div>
              <p className="text-xs text-gray-500 mb-2">Add a common control provider to this project:</p>
              <div className="flex flex-wrap gap-2">
                {available.map(p => (
                  <button key={p.id} onClick={() => linkProviderMut.mutate(p.id)}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-dashed border-gray-300 text-gray-600 hover:border-blue-400 hover:text-blue-600 hover:bg-blue-50 transition-colors">
                    <Link2 size={11} /> {p.name}
                  </button>
                ))}
              </div>
            </div>
          )
        })()}
        {allProviders.length === 0 && (
          <p className="text-sm text-gray-400 italic">
            No common control providers exist yet. <a href="/common-controls" className="text-blue-500 hover:underline">Create one →</a>
          </p>
        )}
      </div>

      {/* Assessments */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="font-semibold text-gray-900 mb-4">Assessments ({assessments.length})</h2>
        {assessments.length === 0 ? (
          <p className="text-gray-600 text-sm">No assessments yet. Upload documents and start an assessment.</p>
        ) : (
          <div className="space-y-4">
            {assessments.map((a) => {
              const edit = getEdit(a)
              const duration = fmtDuration(a.started_at, a.completed_at)
              const isNavigable = ['complete', 'running', 'paused'].includes(a.status)
              return (
                <div key={a.id} className="border rounded-xl overflow-hidden">
                  {/* Card header — clickable to navigate */}
                  <div
                    onClick={() => isNavigable && navigate(`/projects/${id}/assessments/${a.id}`)}
                    className={`flex items-start gap-4 p-4 ${isNavigable ? 'cursor-pointer hover:bg-gray-50' : ''} transition-colors`}
                  >
                    <div className="flex-1 min-w-0">
                      {/* Name row */}
                      <div className="flex items-center gap-2 mb-0.5" onClick={(e) => e.stopPropagation()}>
                        {edit.editingName ? (
                          <div className="flex items-center gap-1 flex-1">
                            <input
                              autoFocus
                              value={edit.name}
                              onChange={(e) => setEdit(a.id, { name: e.target.value })}
                              onKeyDown={(e) => { if (e.key === 'Enter') saveName(a); if (e.key === 'Escape') setEdit(a.id, { editingName: false }) }}
                              className="flex-1 border rounded px-2 py-0.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-300"
                              placeholder={`Assessment #${a.project_run_number}`}
                            />
                            <button onClick={() => saveName(a)} className="text-green-600 hover:text-green-700"><Check size={14} /></button>
                            <button onClick={() => setEdit(a.id, { editingName: false })} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
                          </div>
                        ) : (
                          <>
                            <span className="font-semibold text-sm text-gray-900">
                              {edit.name || `Assessment #${a.project_run_number}`}
                            </span>
                            <button
                              onClick={() => setEdit(a.id, { editingName: true, name: a.name || '' })}
                              className="text-gray-400 hover:text-blue-500 transition-colors"
                              title="Rename"
                            >
                              <Pencil size={12} />
                            </button>
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                              a.status === 'complete' ? 'bg-green-600 text-white' :
                              a.status === 'running'  ? 'bg-blue-600 text-white' :
                              a.status === 'paused'   ? 'bg-amber-500 text-white' :
                              a.status === 'failed'   ? 'bg-red-600 text-white' :
                              'bg-slate-400 text-white'
                            }`}>{a.status}</span>
                          </>
                        )}
                      </div>

                      {/* Model info */}
                      <p className="text-xs text-gray-600 flex items-center gap-2 flex-wrap">
                        <span>{a.llm_provider} / {a.llm_model} · {a.context_strategy}</span>
                        {a.carry_forward_compliant && (
                          <span className="inline-flex items-center gap-1 text-blue-600 bg-blue-50 border border-blue-200 rounded px-1.5 py-0.5 text-xs font-medium">
                            ⏩ Carry-forward on
                          </span>
                        )}
                      </p>

                      {/* Date / Duration */}
                      <div className="flex items-center gap-3 mt-1 text-xs text-gray-600">
                        {a.started_at && (
                          <span>Started {fmt12hr(a.started_at)}</span>
                        )}
                        {duration && (
                          <span className="text-gray-500 font-medium">· {duration}</span>
                        )}
                        {a.status === 'running' && (
                          <span>{a.controls_complete} / {a.controls_total} controls</span>
                        )}
                      </div>

                      {/* Progress bar when running */}
                      {a.status === 'running' && (
                        <div className="mt-2" onClick={(e) => e.stopPropagation()}>
                          <div className="h-1.5 bg-gray-200 rounded-full">
                            <div
                              className="h-1.5 bg-blue-500 rounded-full transition-all"
                              style={{ width: `${a.controls_total ? (a.controls_complete / a.controls_total) * 100 : 0}%` }}
                            />
                          </div>
                          {a.progress_detail && (
                            <p className="text-xs text-blue-500 mt-1 font-mono truncate">▶ {a.progress_detail}</p>
                          )}
                        </div>
                      )}
                      {a.status === 'paused' && a.progress_detail && (
                        <p className="text-xs text-gray-600 mt-1 font-mono truncate" onClick={(e) => e.stopPropagation()}>
                          ⏸ {a.progress_detail}
                        </p>
                      )}
                      {a.status === 'failed' && a.error_message && (
                        <p className="text-xs text-red-500 mt-1 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                          <AlertCircle size={11} />{a.error_message}
                        </p>
                      )}
                    </div>
                    {isNavigable && !edit.editingName && <ChevronRight size={16} className="text-gray-400 mt-1 flex-shrink-0" />}
                  </div>

                  {/* Notes + actions — single compact bottom row */}
                  <div className="border-t border-gray-100 px-4 py-2 flex items-center gap-2 bg-gray-50/60" onClick={(e) => e.stopPropagation()}>
                    {/* Notes (inline expand) */}
                    <div className="flex-1 min-w-0">
                      {edit.editingNotes ? (
                        <div className="flex items-start gap-2">
                          <ExpandingTextarea
                            value={edit.notes}
                            onChange={(e) => setEdit(a.id, { notes: e.target.value })}
                            rows={2}
                            placeholder="Add notes about this assessment run..."
                            className="flex-1 text-xs"
                          />
                          <div className="flex flex-col gap-1 flex-shrink-0">
                            <button onClick={() => saveNotes(a)} className="text-xs bg-blue-600 text-white px-2 py-0.5 rounded hover:bg-blue-700">Save</button>
                            <button onClick={() => setEdit(a.id, { editingNotes: false, notes: a.notes || '' })} className="text-xs text-gray-500 hover:text-gray-700 px-2 py-0.5 rounded border">✕</button>
                          </div>
                        </div>
                      ) : (
                        <button onClick={() => setEdit(a.id, { editingNotes: true, notes: a.notes || '' })} className="flex items-center gap-1.5 w-full text-left group min-w-0">
                          <StickyNote size={12} className="text-gray-400 group-hover:text-blue-400 flex-shrink-0 transition-colors" />
                          <span className="text-xs text-gray-400 italic group-hover:text-gray-600 transition-colors truncate">
                            {a.notes || 'Add notes...'}
                          </span>
                        </button>
                      )}
                    </div>
                    {/* Action buttons */}
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      {a.status === 'running' && (
                        <button onClick={() => pauseAssessment.mutate(a.id)} className="flex items-center gap-1 text-xs text-yellow-600 hover:text-yellow-800 border border-yellow-200 rounded px-2 py-0.5">
                          <Pause size={10} /> Pause
                        </button>
                      )}
                      {a.status === 'paused' && (
                        <button onClick={() => resumeAssessment.mutate(a.id)} className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 border border-blue-200 rounded px-2 py-0.5">
                          <RotateCcw size={10} /> Resume
                        </button>
                      )}
                      {['complete', 'failed', 'paused'].includes(a.status) && (
                        <button onClick={() => { if (window.confirm('Delete this assessment and all its findings?')) deleteAssessment.mutate(a.id) }} className="flex items-center gap-1 text-xs text-red-500 hover:text-red-700 border border-red-200 rounded px-2 py-0.5">
                          <Trash2 size={10} /> Delete
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Start Assessment Modal */}
      {showStartModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-2xl">
            <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
              <Settings size={18} />
              Assessment Configuration
            </h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">LLM Provider</label>
                <select value={startConfig.llm_provider}
                  onChange={(e) => setStartConfig({ ...startConfig, llm_provider: e.target.value, llm_model: '' })}
                  className="w-full border rounded-lg px-3 py-2 text-sm">
                  <option value="ollama">Ollama (Local/Cloud)</option>
                  <option value="claude">Claude (Anthropic)</option>
                  <option value="bedrock">AWS Bedrock</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Context Strategy</label>
                <select value={startConfig.context_strategy}
                  onChange={(e) => setStartConfig({ ...startConfig, context_strategy: e.target.value })}
                  className="w-full border rounded-lg px-3 py-2 text-sm">
                  <option value="rag">RAG (Recommended — semantic retrieval)</option>
                  <option value="hybrid">Hybrid (RAG + full context)</option>
                  <option value="full">Full Context (large window only)</option>
                </select>
              </div>
              {startConfig.llm_provider === 'ollama' && (
                <>
                  <div>
                    <label className="block text-sm font-medium mb-1">Model</label>
                    {ollamaError ? (
                      <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
                        <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
                        <span>Cannot reach Ollama at <code className="font-mono">host.docker.internal:11434</code>. Make sure Ollama is running.</span>
                      </div>
                    ) : ollamaAssessmentModels.length > 0 ? (
                      <select
                        value={selectedOllamaModel}
                        onChange={(e) => setStartConfig({ ...startConfig, llm_model: e.target.value })}
                        className="w-full border rounded-lg px-3 py-2 text-sm">
                        {ollamaAssessmentModels.map((m) => (
                          <option key={m} value={m}>
                            {formatOllamaModelLabel(m)}
                            {m === defaultOllamaModel ? ' (default)' : ''}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input type="text"
                        placeholder={selectedOllamaModel}
                        value={startConfig.llm_model}
                        onChange={(e) => setStartConfig({ ...startConfig, llm_model: e.target.value })}
                        className="w-full border rounded-lg px-3 py-2 text-sm" />
                    )}
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Context Window (tokens)</label>
                    <select value={startConfig.ollama_num_ctx}
                      onChange={(e) => setStartConfig({ ...startConfig, ollama_num_ctx: parseInt(e.target.value) })}
                      className="w-full border rounded-lg px-3 py-2 text-sm">
                      <option value={8192}>8k (Fast)</option>
                      <option value={32768}>32k (Recommended)</option>
                      <option value={65536}>64k (More context, slower)</option>
                      <option value={131072}>128k (Heavy VRAM)</option>
                      <option value={262144}>256k (Maximum)</option>
                    </select>
                  </div>
                </>
              )}
              {/* Carry-forward compliant toggle */}
              {/* Carry-forward compliant toggle */}
              {(() => {
                const lastComplete = [...assessments]
                  .sort((a, b) => new Date(b.completed_at) - new Date(a.completed_at))
                  .find(a => a.status === 'complete')
                const noHistory = !lastComplete
                return (
                  <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                    noHistory
                      ? 'border-gray-200 bg-gray-50 opacity-60 cursor-not-allowed'
                      : 'border-blue-200 bg-blue-50 hover:bg-blue-100'
                  }`}>
                    <input type="checkbox"
                      checked={!noHistory && startConfig.carry_forward_compliant}
                      disabled={noHistory}
                      onChange={(e) => setStartConfig({ ...startConfig, carry_forward_compliant: e.target.checked })}
                      className="mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-gray-800">
                        Carry forward compliant controls
                        {!noHistory && <span className="text-xs font-normal text-blue-600 ml-1">recommended · saves time</span>}
                        {noHistory && <span className="text-xs font-normal text-gray-400 ml-1">no previous assessment</span>}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        Controls marked <strong>compliant</strong> in the previous assessment are copied directly — no LLM call.
                        Only non-compliant, partial, N/A, and new controls are re-tested.
                        {lastComplete && (
                          <span className="block mt-1 text-blue-700 font-medium">
                            Previous run #{lastComplete.project_run_number}: {lastComplete.controls_total} controls —
                            compliant ones will be skipped automatically
                          </span>
                        )}
                      </p>
                    </div>
                  </label>
                )
              })()}

              {/* Fast mode toggle */}
              <label className="flex items-start gap-3 p-3 rounded-lg border border-gray-200 cursor-pointer hover:bg-gray-50 transition-colors">
                <input type="checkbox"
                  checked={startConfig.skip_stage3}
                  onChange={(e) => setStartConfig({ ...startConfig, skip_stage3: e.target.checked })}
                  className="mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-gray-800">Fast mode <span className="text-xs font-normal text-green-600 ml-1">~2× faster</span></p>
                  <p className="text-xs text-gray-500 mt-0.5">Skip narrative writing (Stage 3). Evidence analysis still runs — results are synthesized from gap analysis instead of a second LLM call.</p>
                </div>
              </label>

              <div className="flex gap-3 pt-2">
                <button onClick={() => setShowStartModal(false)}
                  className="flex-1 border rounded-lg py-2 text-sm hover:bg-gray-50">Cancel</button>
                <button onClick={() => startAssessment.mutate(startConfig)}
                  disabled={startAssessment.isPending}
                  className="flex-1 bg-green-600 text-white rounded-lg py-2 text-sm hover:bg-green-700 disabled:opacity-50">
                  {startAssessment.isPending ? 'Starting...' : 'Start'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Document Evidence Explorer */}
      {explorerDoc && (
        <DocumentExplorer
          projectId={id}
          doc={explorerDoc}
          onClose={() => setExplorerDoc(null)}
        />
      )}

      {/* Document Pipeline Quality Report */}
      {reportDoc && (
        <DocumentPipelineReport
          documentId={reportDoc.id}
          documentName={reportDoc.filename || reportDoc.original_filename}
          onClose={() => setReportDoc(null)}
        />
      )}
    </div>
  )
}
