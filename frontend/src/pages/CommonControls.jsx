import { useState, useCallback, useRef, Fragment } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Building2, Upload, File, Trash2, RefreshCw, Plus, X,
  ChevronRight, ChevronDown, CheckCircle2, AlertCircle, Loader2,
  Download, Tag, FolderOpen, BarChart2, MessageSquare,
} from 'lucide-react'
import api from '../api/client'
import DocumentExplorer from '../components/DocumentExplorer'
import PipelineStageIndicator from '../components/PipelineStageIndicator'
import DocumentPipelineReport from '../components/DocumentPipelineReport'
import { openCyberAssistant } from '../components/cyberAssistant'

const ORG_LEVELS = ['enterprise', 'department', 'agency', 'program']
const CONTROL_FAMILIES = [
  'AC','AT','AU','CA','CM','CP','IA','IR','MA','MP',
  'PE','PL','PM','PS','PT','RA','SA','SC','SI','SR',
]

const STATUS_COLOR = {
  complete:     'text-green-600',
  failed:       'text-red-500',
  processing:   'text-blue-500',
  pending:      'text-gray-400',
  queued:       'text-purple-500',
  indexing:     'text-blue-500',
  indexed:      'text-emerald-600',
  index_failed: 'text-orange-500',
}
const STATUS_LABEL = {
  complete:     'Parsed',
  failed:       'Failed',
  processing:   'Processing',
  pending:      'Pending',
  queued:       'Queued…',
  indexing:     'Indexing…',
  indexed:      'Indexed',
  index_failed: 'Index Failed',
}
const STATUS_ICON = {
  complete:     <CheckCircle2 size={13} />,
  failed:       <AlertCircle size={13} />,
  processing:   <Loader2 size={13} className="animate-spin" />,
  pending:      <Loader2 size={13} className="animate-spin" />,
  queued:       <Loader2 size={13} className="animate-spin" />,
  indexing:     <Loader2 size={13} className="animate-spin" />,
  indexed:      <Tag size={13} />,
  index_failed: <AlertCircle size={13} />,
}

function fmt(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function fmtBytes(b) {
  if (b < 1024) return `${b} B`
  if (b < 1048576) return `${(b / 1024).toFixed(0)} KB`
  return `${(b / 1048576).toFixed(1)} MB`
}

// ── Drop Zone ────────────────────────────────────────────────────────────────
function DropZone({ onFiles, uploading }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef()

  const collectFiles = (entry) => new Promise((resolve) => {
    if (entry.isFile) {
      entry.file(file => resolve([file]), () => resolve([]))
    } else if (entry.isDirectory) {
      const reader = entry.createReader()
      const readAll = (acc) => {
        reader.readEntries(async (batch) => {
          if (batch.length === 0) {
            const nested = await Promise.all(acc.map(collectFiles))
            resolve(nested.flat())
          } else {
            readAll([...acc, ...batch])
          }
        })
      }
      readAll([])
    } else {
      resolve([])
    }
  })

  const handleDrop = useCallback(async (e) => {
    e.preventDefault()
    setDragging(false)
    const items = Array.from(e.dataTransfer.items || [])
    const entries = items.map(i => i.webkitGetAsEntry?.()).filter(Boolean)
    if (entries.length) {
      const all = await Promise.all(entries.map(collectFiles))
      onFiles(all.flat())
    } else {
      onFiles(Array.from(e.dataTransfer.files || []))
    }
  }, [onFiles])

  return (
    <div
      onDrop={handleDrop}
      onDragOver={e => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onClick={() => inputRef.current?.click()}
      className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
        dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
      } ${uploading ? 'opacity-50 pointer-events-none' : ''}`}
    >
      <input ref={inputRef} type="file" multiple className="hidden"
        onChange={e => onFiles(Array.from(e.target.files || []))} />
      <Upload size={28} className="mx-auto mb-2 text-gray-300" />
      <p className="text-sm text-gray-500">Drop files or folders here, or click to upload</p>
      <p className="text-xs text-gray-400 mt-1">PDF, Word, Excel, PowerPoint, Visio, images, text</p>
    </div>
  )
}

// ── Document Row ─────────────────────────────────────────────────────────────
function DocRow({ doc, providerId, processingProgress, onDelete, onReparse, onReindex, onExplore, onPipelineReport }) {
  const [reparsing, setReparsing] = useState(false)
  const [reindexing, setReindexing] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const download = async () => {
    setDownloading(true)
    try {
      const res = await api.get(
        `/common-controls/providers/${providerId}/documents/${doc.id}/download`,
        { responseType: 'blob' }
      )
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url; a.download = doc.filename; a.click()
      URL.revokeObjectURL(url)
    } catch { alert('Download failed') }
    setDownloading(false)
  }

  const reparse = async () => {
    setReparsing(true)
    await onReparse(doc.id)
    setReparsing(false)
  }

  const reindex = async () => {
    setReindexing(true)
    await onReindex(doc.id)
    setReindexing(false)
  }

  const showError = ['failed', 'index_failed'].includes(doc.parse_status) && doc.parse_error
  const canReparse = doc.parse_status === 'failed'
  const canReindex = ['complete', 'indexed', 'index_failed'].includes(doc.parse_status)

  return (
    <div className="flex items-center gap-3 py-2 border-b border-gray-100 last:border-0 group">
      <File size={14} className="text-gray-400 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        {doc.parse_status === 'indexed' ? (
          <button
            onClick={() => onExplore(doc)}
            className="text-sm text-blue-700 hover:text-blue-900 hover:underline truncate block text-left w-full"
            title={`View evidence index for ${doc.filename}`}
          >
            {doc.filename}
          </button>
        ) : (
          <span className="text-sm text-gray-800 truncate block">{doc.filename}</span>
        )}
        <span className="text-xs text-gray-400">{fmtBytes(doc.file_size_bytes)} · {fmt(doc.created_at)}</span>
      </div>
      {doc.parse_status === 'processing' ? (
        <PipelineStageIndicator progress={processingProgress?.[doc.id]} />
      ) : (
        <span className={`flex items-center gap-1 text-xs font-medium ${STATUS_COLOR[doc.parse_status] || 'text-gray-400'}`}>
          {STATUS_ICON[doc.parse_status]}
          {STATUS_LABEL[doc.parse_status] || doc.parse_status}
        </span>
      )}
      {showError && (
        <span
          className={`text-xs max-w-[200px] truncate ${
            doc.parse_status === 'failed' ? 'text-red-400' : 'text-orange-400'
          }`}
          title={doc.parse_error}
        >
          {doc.parse_error}
        </span>
      )}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={() => openCyberAssistant({
            mode: 'workspace',
            title: `${doc.filename} Assistant`,
            attachments: [
              { type: 'provider', resource_id: String(providerId), context_json: {} },
              {
                type: 'document',
                resource_id: String(doc.id),
                context_json: {
                  label: `Document: ${doc.filename}`,
                  filename: doc.filename,
                  parse_status: doc.parse_status,
                },
              },
            ],
          })}
          className="p-1 text-violet-500 hover:text-violet-700"
          title="Ask AI about this document"
        >
          <MessageSquare size={13} />
        </button>
        {canReparse && (
          <button onClick={reparse} disabled={reparsing}
            className="p-1 text-blue-500 hover:text-blue-700 disabled:opacity-50" title="Retry parse">
            <RefreshCw size={13} className={reparsing ? 'animate-spin' : ''} />
          </button>
        )}
        {canReindex && (
          <button onClick={reindex} disabled={reindexing}
            className="p-1 text-purple-500 hover:text-purple-700 disabled:opacity-50" title="Index controls (assign NIST tags via LLM)">
            <Tag size={13} className={reindexing ? 'animate-pulse' : ''} />
          </button>
        )}
        {doc.parse_status === 'indexed' && (
          <button onClick={() => onPipelineReport(doc)}
            className="p-1 text-gray-400 hover:text-indigo-500 transition-colors" title="Pipeline quality report">
            <BarChart2 size={13} />
          </button>
        )}
        <button onClick={download} disabled={downloading}
          className="p-1 text-gray-400 hover:text-blue-500 disabled:opacity-50" title="Download">
          <Download size={13} />
        </button>
        <button onClick={() => onDelete(doc.id)}
          className="p-1 text-gray-300 hover:text-red-500" title="Delete">
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  )
}

// ── Provider Card ─────────────────────────────────────────────────────────────
function ProviderCard({ provider, onDeleted }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadErrors, setUploadErrors] = useState([])
  const [explorerDoc, setExplorerDoc] = useState(null)
  const [reportDoc, setReportDoc] = useState(null)

  const { data: docs = [], refetch: refetchDocs } = useQuery({
    queryKey: ['cc-docs', provider.id],
    queryFn: () => api.get(`/common-controls/providers/${provider.id}/documents`).then(r => r.data),
    enabled: open,
    refetchInterval: (query) =>
      query.state.data?.some((doc) => ['pending', 'processing', 'indexing', 'queued'].includes(doc.parse_status)) ? 1000 : false,
  })

  const indexed = docs.filter(d => d.parse_status === 'indexed').length
  const active  = docs.filter(d => ['indexing', 'queued', 'processing', 'pending'].includes(d.parse_status)).length
  const hasProcessing = docs.some(d => d.parse_status === 'processing')

  const { data: processingProgress } = useQuery({
    queryKey: ['cc-progress', provider.id],
    queryFn: () => api.get(`/common-controls/providers/${provider.id}/processing-progress`).then(r => r.data),
    enabled: open && hasProcessing,
    refetchInterval: hasProcessing ? 1000 : false,
  })

  const deleteMut = useMutation({
    mutationFn: (docId) => api.delete(`/common-controls/providers/${provider.id}/documents/${docId}`),
    onSuccess: () => refetchDocs(),
  })

  const uploadFiles = async (files) => {
    setUploading(true)
    setUploadErrors([])
    const errs = []
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      try {
        await api.post(`/common-controls/providers/${provider.id}/documents`, form)
      } catch (e) {
        errs.push(`${file.name}: ${e.response?.data?.detail || e.message}`)
      }
    }
    setUploadErrors(errs)
    refetchDocs()
    qc.invalidateQueries(['cc-providers'])
    setUploading(false)
  }

  const reparse = async (docId) => {
    try {
      await api.post(`/common-controls/providers/${provider.id}/documents/${docId}/reparse`)
      refetchDocs()
    } catch (e) {
      alert('Reparse failed: ' + (e?.response?.data?.detail || e?.message))
    }
  }

  const reindex = async (docId) => {
    try {
      await api.post(`/common-controls/providers/${provider.id}/documents/${docId}/reindex`)
      refetchDocs()
    } catch (e) {
      alert('Reindex failed: ' + (e?.response?.data?.detail || e?.message))
    }
  }

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden bg-white">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors"
        onClick={() => setOpen(o => !o)}>
        <Building2 size={16} className="text-blue-500 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm text-gray-900">{provider.name}</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
              {provider.org_level}
            </span>
          </div>
          {provider.description && (
            <p className="text-xs text-gray-500 truncate mt-0.5">{provider.description}</p>
          )}
          <div className="flex items-center gap-3 mt-1 flex-wrap">
            <span className="text-xs text-gray-400">{provider.document_count} document{provider.document_count !== 1 ? 's' : ''}</span>
            {open && docs.length > 0 && (
              <span className={`text-xs font-medium ${
                indexed === docs.length ? 'text-emerald-600'
                : active > 0 ? 'text-blue-500'
                : 'text-amber-600'
              }`}>
                {indexed}/{docs.length} indexed{active > 0 ? ` · ${active} active` : ''}
              </span>
            )}
            {provider.control_families?.length > 0 && (
              <div className="flex gap-1 flex-wrap">
                {provider.control_families.slice(0, 6).map(f => (
                  <span key={f} className="text-xs px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 font-mono">
                    {f}
                  </span>
                ))}
                {provider.control_families.length > 6 && (
                  <span className="text-xs text-gray-400">+{provider.control_families.length - 6}</span>
                )}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation()
              openCyberAssistant({
                mode: 'workspace',
                title: `${provider.name} Provider Assistant`,
                attachments: [
                  { type: 'provider', resource_id: String(provider.id), context_json: {} },
                ],
              })
            }}
            className="p-1.5 text-violet-500 hover:text-violet-700 transition-colors rounded"
            title="Ask AI about this provider"
          >
            <MessageSquare size={15} />
          </button>
          <button onClick={(e) => { e.stopPropagation(); if (window.confirm(`Delete provider "${provider.name}" and all its documents?`)) onDeleted(provider.id) }}
            className="p-1 text-gray-300 hover:text-red-500 transition-colors" title="Delete provider">
            <Trash2 size={14} />
          </button>
          {open ? <ChevronDown size={14} className="text-gray-400" /> : <ChevronRight size={14} className="text-gray-400" />}
        </div>
        <button
          onClick={() => openCyberAssistant({
            mode: 'workspace',
            title: 'Common Controls Assistant',
            attachments: [{ type: 'general', resource_id: 'general', context_json: { label: 'Common Controls Workspace' } }],
          })}
          className="flex items-center gap-2 border border-violet-300 text-violet-600 px-4 py-2.5 rounded-xl text-sm font-medium hover:bg-violet-50 transition-colors shadow-sm flex-shrink-0 ml-4"
        >
          <MessageSquare size={16} />
          Ask AI
        </button>
      </div>

      {/* Expanded body */}
      {open && (
        <div className="border-t border-gray-100 px-4 py-4 bg-gray-50 space-y-4">
          <DropZone onFiles={uploadFiles} uploading={uploading} />

          {uploading && (
            <p className="text-xs text-blue-600 flex items-center gap-1">
              <Loader2 size={11} className="animate-spin" /> Uploading…
            </p>
          )}
          {uploadErrors.map((e, i) => (
            <p key={i} className="text-xs text-red-500 flex items-center gap-1">
              <AlertCircle size={11} /> {e}
            </p>
          ))}

          {docs.length > 0 ? (
            <>
              {/* Indexing progress bar */}
              <div className="flex items-center justify-between px-1">
                <span className={`text-xs font-medium ${
                  indexed === docs.length ? 'text-emerald-600'
                  : active > 0 ? 'text-blue-500'
                  : 'text-amber-600'
                }`}>
                  {indexed}/{docs.length} indexed{active > 0 ? ` · ${active} active` : ''}
                </span>
                {docs.length > 0 && (
                  <div className="flex-1 mx-3 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        indexed === docs.length ? 'bg-emerald-500' : active > 0 ? 'bg-blue-400' : 'bg-amber-400'
                      }`}
                      style={{ width: `${Math.round((indexed / docs.length) * 100)}%` }}
                    />
                  </div>
                )}
                <span className="text-xs text-gray-400">{Math.round((indexed / docs.length) * 100)}%</span>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg px-3 py-1">
                {docs.map(doc => (
                  <DocRow key={doc.id} doc={doc} providerId={provider.id}
                    processingProgress={processingProgress}
                    onDelete={(id) => deleteMut.mutate(id)} onReparse={reparse} onReindex={reindex}
                    onExplore={setExplorerDoc} onPipelineReport={setReportDoc} />
                ))}
              </div>
            </>
          ) : (
            <p className="text-xs text-gray-400 italic text-center py-2">No documents uploaded yet.</p>
          )}
        </div>
      )}

      {/* Document Evidence Explorer */}
      {explorerDoc && (
        <DocumentExplorer
          providerId={provider.id}
          doc={explorerDoc}
          onClose={() => setExplorerDoc(null)}
        />
      )}
      {reportDoc && (
        <DocumentPipelineReport
          documentId={reportDoc.id}
          documentName={reportDoc.filename}
          onClose={() => setReportDoc(null)}
        />
      )}
    </div>
  )
}

// ── New Provider Modal ────────────────────────────────────────────────────────
function NewProviderModal({ onClose, onCreate }) {
  const [form, setForm] = useState({ name: '', description: '', org_level: 'enterprise', control_families: [] })
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  const toggleFamily = (f) => setForm(p => ({
    ...p,
    control_families: p.control_families.includes(f)
      ? p.control_families.filter(x => x !== f)
      : [...p.control_families, f],
  }))

  const save = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    setSaveError('')
    try {
      await onCreate(form)
    } catch (e) {
      setSaveError(e?.response?.data?.detail || e?.message || 'Failed to create provider')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-gray-900">New Common Control Provider</h2>
          <button onClick={onClose}><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-gray-600 uppercase mb-1">Provider Name *</label>
            <input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
              placeholder="e.g. Enterprise IT, AWS GovCloud FedRAMP Package"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 uppercase mb-1">Description</label>
            <textarea value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
              placeholder="Describe what controls this provider covers…"
              rows={2}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 resize-y" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 uppercase mb-1">Org Level</label>
            <select value={form.org_level} onChange={e => setForm(p => ({ ...p, org_level: e.target.value }))}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300">
              {ORG_LEVELS.map(l => <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 uppercase mb-2">Control Families Covered</label>
            <div className="flex flex-wrap gap-1.5">
              {CONTROL_FAMILIES.map(f => (
                <button key={f} onClick={() => toggleFamily(f)}
                  className={`text-xs px-2 py-1 rounded font-mono font-medium border transition-colors ${
                    form.control_families.includes(f)
                      ? 'bg-blue-600 text-white border-blue-600'
                      : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'
                  }`}>
                  {f}
                </button>
              ))}
            </div>
          </div>
        </div>

        {saveError && (
          <div className="mt-4 flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            <AlertCircle size={14} />
            {saveError}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={save} disabled={!form.name.trim() || saving}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2">
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
            Create Provider
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function CommonControls() {
  const qc = useQueryClient()
  const [showModal, setShowModal] = useState(false)

  const { data: providers = [], isLoading } = useQuery({
    queryKey: ['cc-providers'],
    queryFn: () => api.get('/common-controls/providers').then(r => r.data),
    refetchInterval: 10000,
  })

  const createMut = useMutation({
    mutationFn: (body) => api.post('/common-controls/providers', body),
    onSuccess: () => { qc.invalidateQueries(['cc-providers']); setShowModal(false) },
  })

  const deleteMut = useMutation({
    mutationFn: (id) => api.delete(`/common-controls/providers/${id}`),
    onSuccess: () => qc.invalidateQueries(['cc-providers']),
  })

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Building2 size={22} className="text-blue-600" />
            Common Controls Library
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Enterprise-level common control providers. Documents uploaded here are made available
            to any project that links to a provider, supplementing the project's own evidence
            during AI assessments.
          </p>
        </div>
        <button onClick={() => setShowModal(true)}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700">
          <Plus size={14} /> New Provider
        </button>
      </div>

      {/* Info banner */}
      <div className="mb-6 flex items-start gap-3 p-4 rounded-xl bg-blue-50 border border-blue-200">
        <FolderOpen size={16} className="text-blue-500 mt-0.5 flex-shrink-0" />
        <p className="text-sm text-blue-700">
          To use a provider in an assessment, open a project and select which providers to inherit from
          in the <strong>Common Controls</strong> section. Provider documents are then automatically
          included in RAG retrieval for every control assessment.
        </p>
      </div>

      {/* Providers list */}
      {isLoading ? (
        <div className="text-sm text-gray-400 text-center py-12">Loading providers…</div>
      ) : providers.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <Building2 size={40} className="mx-auto mb-3 text-gray-200" />
          <p className="font-medium">No common control providers yet</p>
          <p className="text-sm mt-1">Create your first provider to get started</p>
        </div>
      ) : (
        <div className="space-y-3">
          {providers.map(p => (
            <ProviderCard key={p.id} provider={p}
              onDeleted={(id) => deleteMut.mutate(id)} />
          ))}
        </div>
      )}

      {showModal && (
        <NewProviderModal
          onClose={() => setShowModal(false)}
          onCreate={(body) => createMut.mutateAsync(body)}
        />
      )}
    </div>
  )
}
