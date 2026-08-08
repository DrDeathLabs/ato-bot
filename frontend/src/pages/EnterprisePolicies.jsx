import { useState, useCallback, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  BookOpen, Upload, File, Trash2, RefreshCw, Plus, X,
  ChevronRight, ChevronDown, CheckCircle2, AlertCircle, Loader2,
  Download, Tag, FolderOpen, Shield, BarChart2, MessageSquare,
} from 'lucide-react'
import api from '../api/client'
import DocumentExplorer from '../components/DocumentExplorer'
import PipelineStageIndicator from '../components/PipelineStageIndicator'
import DocumentPipelineReport from '../components/DocumentPipelineReport'
import { openCyberAssistant } from '../components/cyberAssistant'


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
  if (!b) return '0 B'
  if (b < 1024) return `${b} B`
  if (b < 1048576) return `${(b / 1024).toFixed(0)} KB`
  return `${(b / 1048576).toFixed(1)} MB`
}

// ── Drop Zone ─────────────────────────────────────────────────────────────────
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
          } else { readAll([...acc, ...batch]) }
        })
      }
      readAll([])
    } else { resolve([]) }
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
      onClick={() => !uploading && inputRef.current?.click()}
      className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors mb-4
        ${dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'}
        ${uploading ? 'opacity-60 cursor-not-allowed' : ''}`}
    >
      <input ref={inputRef} type="file" multiple className="hidden"
        onChange={e => onFiles(Array.from(e.target.files || []))} />
      <Upload size={24} className="mx-auto text-gray-300 mb-2" />
      <p className="text-sm text-gray-500">Drop files or folders here, or click to upload</p>
      <p className="text-xs text-gray-400 mt-1">PDF, Word, Excel, PowerPoint, Visio, images, text</p>
    </div>
  )
}

// ── Document Row ──────────────────────────────────────────────────────────────
function DocRow({ doc, libraryId, processingProgress, onDelete, onReparse, onReindex, onExplore, onPipelineReport }) {
  const [downloading, setDownloading] = useState(false)

  const download = async () => {
    setDownloading(true)
    try {
      const res = await api.get(
        `/enterprise-policies/libraries/${libraryId}/documents/${doc.id}/download`,
        { responseType: 'blob' }
      )
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url; a.download = doc.filename; a.click()
      URL.revokeObjectURL(url)
    } catch { alert('Download failed') }
    setDownloading(false)
  }

  const canReparse = doc.parse_status === 'failed'
  const canReindex = ['complete', 'indexed', 'index_failed'].includes(doc.parse_status)
  const isActive   = ['queued', 'indexing', 'processing', 'pending'].includes(doc.parse_status)

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

      {['failed', 'index_failed'].includes(doc.parse_status) && doc.parse_error && (
        <span
          className={`text-xs max-w-[180px] truncate ${
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
              { type: 'library', resource_id: String(libraryId), context_json: { library_kind: 'policy' } },
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
          <button onClick={() => onReparse(doc.id)}
            className="p-1 text-blue-500 hover:text-blue-700" title="Retry parse">
            <RefreshCw size={13} />
          </button>
        )}
        {canReindex && (
          <button onClick={() => onReindex(doc.id)}
            className="p-1 text-purple-500 hover:text-purple-700" title="Index NIST controls via LLM">
            <Tag size={13} />
          </button>
        )}
        {isActive && (
          <span className="text-xs text-gray-400 italic px-1">In queue</span>
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

// ── Library Card ──────────────────────────────────────────────────────────────
function LibraryCard({ library, onDeleted }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadErrors, setUploadErrors] = useState([])
  const [explorerDoc, setExplorerDoc] = useState(null)
  const [reportDoc, setReportDoc] = useState(null)

  const { data: docs = [], refetch } = useQuery({
    queryKey: ['ep-docs', library.id],
    queryFn: () => api.get(`/enterprise-policies/libraries/${library.id}/documents`).then(r => r.data),
    enabled: open,
    refetchInterval: (query) =>
      query.state.data?.some(d => ['pending', 'processing', 'indexing', 'queued'].includes(d.parse_status))
        ? 1000 : false,
  })

  const hasProcessing = docs.some(d => d.parse_status === 'processing')
  const { data: processingProgress } = useQuery({
    queryKey: ['ep-progress', library.id],
    queryFn: () => api.get(`/enterprise-policies/libraries/${library.id}/processing-progress`).then(r => r.data),
    enabled: open && hasProcessing,
    refetchInterval: hasProcessing ? 1000 : false,
  })

  const deleteMut = useMutation({
    mutationFn: (docId) => api.delete(`/enterprise-policies/libraries/${library.id}/documents/${docId}`),
    onSuccess: () => { refetch(); qc.invalidateQueries(['ep-libraries']) },
  })

  const uploadFiles = async (files) => {
    setUploading(true)
    setUploadErrors([])
    const errs = []
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      try {
        await api.post(`/enterprise-policies/libraries/${library.id}/documents`, form)
      } catch (e) {
        errs.push(`${file.name}: ${e.response?.data?.detail || e.message}`)
      }
    }
    setUploadErrors(errs)
    refetch()
    qc.invalidateQueries(['ep-libraries'])
    setUploading(false)
  }

  const reparse = async (docId) => {
    try {
      await api.post(`/enterprise-policies/libraries/${library.id}/documents/${docId}/reparse`)
      refetch()
    } catch (e) { alert('Reparse failed: ' + (e?.response?.data?.detail || e?.message)) }
  }

  const reindex = async (docId) => {
    try {
      await api.post(`/enterprise-policies/libraries/${library.id}/documents/${docId}/reindex`)
      refetch()
    } catch (e) { alert('Reindex failed: ' + (e?.response?.data?.detail || e?.message)) }
  }

  const indexed = docs.filter(d => d.parse_status === 'indexed').length
  const active  = docs.filter(d => ['indexing','queued'].includes(d.parse_status)).length

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden mb-4">
      {/* Card header */}
      <div
        className="flex items-center gap-3 px-5 py-4 cursor-pointer hover:bg-gray-50 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <BookOpen size={18} className="text-blue-600 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-gray-900">{library.name}</span>
          </div>
          {library.description && (
            <p className="text-sm text-gray-500 truncate mt-0.5">{library.description}</p>
          )}
          <div className="flex items-center gap-3 mt-1">
            <span className="text-xs text-gray-400">{library.document_count} document{library.document_count !== 1 ? 's' : ''}</span>
            {open && docs.length > 0 && (
              <span className={`text-xs font-medium ${indexed === docs.length ? 'text-green-600' : active > 0 ? 'text-blue-500' : 'text-amber-600'}`}>
                {indexed}/{docs.length} indexed{active > 0 ? ` · ${active} active` : ''}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={(e) => {
              e.stopPropagation()
              openCyberAssistant({
                mode: 'workspace',
                title: `${library.name} Policy Assistant`,
                attachments: [
                  { type: 'library', resource_id: String(library.id), context_json: { library_kind: 'policy' } },
                ],
              })
            }}
            className="p-1.5 text-violet-500 hover:text-violet-700 transition-colors rounded"
            title="Ask AI about this policy library"
          >
            <MessageSquare size={15} />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (window.confirm(`Delete library "${library.name}" and all its documents?`)) onDeleted(library.id)
            }}
            className="p-1.5 text-gray-300 hover:text-red-500 transition-colors rounded"
            title="Delete library"
          >
            <Trash2 size={15} />
          </button>
          {open ? <ChevronDown size={16} className="text-gray-400" /> : <ChevronRight size={16} className="text-gray-400" />}
        </div>
      </div>

      {/* Expanded body */}
      {open && (
        <div className="border-t border-gray-100 px-5 py-4">
          <DropZone onFiles={uploadFiles} uploading={uploading} />

          {uploading && (
            <p className="text-xs text-blue-600 flex items-center gap-1 mb-3">
              <Loader2 size={12} className="animate-spin" /> Uploading…
            </p>
          )}
          {uploadErrors.map((e, i) => (
            <p key={i} className="text-xs text-red-500 mb-1 flex items-center gap-1">
              <AlertCircle size={11} />{e}
            </p>
          ))}

          {docs.length > 0 ? (
            <>
              <div className="flex items-center justify-between px-1">
                <span className={`text-xs font-medium ${
                  indexed === docs.length ? 'text-emerald-600'
                  : active > 0 ? 'text-blue-500'
                  : 'text-amber-600'
                }`}>
                  {indexed}/{docs.length} indexed{active > 0 ? ` · ${active} active` : ''}
                </span>
                <div className="flex-1 mx-3 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      indexed === docs.length ? 'bg-emerald-500' : active > 0 ? 'bg-blue-400' : 'bg-amber-400'
                    }`}
                    style={{ width: `${Math.round((indexed / docs.length) * 100)}%` }}
                  />
                </div>
                <span className="text-xs text-gray-400">{Math.round((indexed / docs.length) * 100)}%</span>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg px-3 py-1">
                {docs.map(doc => (
                  <DocRow key={doc.id} doc={doc} libraryId={library.id}
                    processingProgress={processingProgress}
                    onDelete={(id) => deleteMut.mutate(id)}
                    onReparse={reparse} onReindex={reindex}
                    onExplore={setExplorerDoc} onPipelineReport={setReportDoc}
                  />
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
          policyLibraryId={library.id}
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

// ── New Library Modal ─────────────────────────────────────────────────────────
function NewLibraryModal({ onClose, onCreate }) {
  const [form, setForm] = useState({ name: '', description: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const save = async () => {
    if (!form.name.trim()) { setError('Name is required'); return }
    setSaving(true)
    setError('')
    try {
      const { data } = await api.post('/enterprise-policies/libraries', form)
      onCreate(data)
      onClose()
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to create library')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-semibold text-gray-900">New Policy Library</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Library Name <span className="text-red-400">*</span></label>
            <input
              type="text" value={form.name} placeholder="e.g. Information Security Policies"
              onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
            <textarea
              value={form.description} rows={3}
              placeholder="Optional description of this policy library…"
              onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none"
            />
          </div>

          {error && (
            <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <AlertCircle size={14} />{error}
            </div>
          )}
        </div>

        <div className="flex gap-3 mt-6">
          <button onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 rounded-lg py-2 text-sm hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={save} disabled={saving}
            className="flex-1 bg-blue-600 text-white rounded-lg py-2 text-sm hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Creating…' : 'Create Library'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function EnterprisePolicies() {
  const qc = useQueryClient()
  const [showModal, setShowModal] = useState(false)

  const { data: libraries = [], isLoading } = useQuery({
    queryKey: ['ep-libraries'],
    queryFn: () => api.get('/enterprise-policies/libraries').then(r => r.data),
  })

  const deleteMut = useMutation({
    mutationFn: (id) => api.delete(`/enterprise-policies/libraries/${id}`),
    onSuccess: () => qc.invalidateQueries(['ep-libraries']),
  })

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Shield size={24} className="text-blue-600" />
            Enterprise Policy Library
          </h1>
          <p className="text-gray-500 mt-1 text-sm">
            Organization-wide policy documents. Documents uploaded here are indexed against NIST 800-53 controls
            and available to supplement project assessments.
          </p>
        </div>
        <button
          onClick={() => openCyberAssistant({
            mode: 'workspace',
            title: 'Enterprise Policy Assistant',
            attachments: [{ type: 'general', resource_id: 'general', context_json: { label: 'Enterprise Policy Library' } }],
          })}
          className="flex items-center gap-2 border border-violet-300 text-violet-600 px-4 py-2.5 rounded-xl text-sm font-medium hover:bg-violet-50 transition-colors shadow-sm flex-shrink-0"
        >
          <MessageSquare size={16} />
          Ask AI
        </button>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2.5 rounded-xl text-sm font-medium hover:bg-blue-700 transition-colors shadow-sm flex-shrink-0 ml-4"
        >
          <Plus size={16} />New Library
        </button>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 mb-6 text-sm text-blue-800">
        <FolderOpen size={16} className="text-blue-500 flex-shrink-0 mt-0.5" />
        <p>
          Policy documents are parsed, chunked, and indexed against NIST 800-53 Rev 5 controls at upload time.
          Click any <strong>Indexed</strong> filename to explore how the document was tagged.
        </p>
      </div>

      {/* Library list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <Loader2 size={20} className="animate-spin mr-2" />Loading libraries…
        </div>
      ) : libraries.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <BookOpen size={32} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">No policy libraries yet.</p>
          <p className="text-xs mt-1">Create a library to start uploading enterprise policy documents.</p>
        </div>
      ) : (
        libraries.map(lib => (
          <LibraryCard
            key={lib.id}
            library={lib}
            onDeleted={(id) => deleteMut.mutate(id)}
          />
        ))
      )}

      {showModal && (
        <NewLibraryModal
          onClose={() => setShowModal(false)}
          onCreate={() => qc.invalidateQueries(['ep-libraries'])}
        />
      )}
    </div>
  )
}
