import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  X, File, ChevronDown, ChevronUp, Search, Tag,
  Layers, AlertCircle, Loader2, Hash, FileSearch, MessageSquare,
} from 'lucide-react'
import api from '../api/client'
import { ControlReferenceButton } from './ControlReference'
import { openCyberAssistant } from './cyberAssistant'

// Confidence → color
function confidenceColor(c) {
  if (c >= 0.75) return 'bg-green-100 text-green-800 border-green-200'
  if (c >= 0.55) return 'bg-blue-100 text-blue-800 border-blue-200'
  return 'bg-gray-100 text-gray-600 border-gray-200'
}
function confidenceBar(c) {
  if (c >= 0.75) return 'bg-green-400'
  if (c >= 0.55) return 'bg-blue-400'
  return 'bg-gray-300'
}

function ControlBadge({ tag }) {
  const [tip, setTip] = useState(false)
  return (
    <div className="relative inline-block">
      <span
        className={`inline-flex items-center gap-1 text-xs font-mono font-semibold px-2 py-0.5 rounded border cursor-pointer ${confidenceColor(tag.confidence)}`}
        onMouseEnter={() => setTip(true)}
        onMouseLeave={() => setTip(false)}
      >
        {tag.control_id}
        <span className="font-normal opacity-60">{Math.round(tag.confidence * 100)}%</span>
      </span>
      <ControlReferenceButton controlId={tag.control_id} iconOnly className="ml-1 align-middle" />
      {tip && tag.notes && (
        <div className="absolute z-50 bottom-full left-0 mb-1 w-64 bg-gray-900 text-white text-xs rounded px-2 py-1.5 shadow-lg pointer-events-none">
          {tag.notes}
        </div>
      )}
    </div>
  )
}

function ChunkRow({ chunk, expanded, onToggle, highlight }) {
  const hasNoTags = chunk.tags.length === 0
  const matchesFilter = !highlight || chunk.tags.some(t =>
    t.control_id.toLowerCase().includes(highlight.toLowerCase())
  )

  if (!matchesFilter) return null

  // Highlight search term in content
  const contentPreview = chunk.content.slice(0, 300)

  return (
    <div className={`border rounded-lg mb-2 overflow-hidden ${hasNoTags ? 'border-gray-100 bg-gray-50' : 'border-gray-200 bg-white'}`}>
      {/* Chunk header */}
      <button
        onClick={onToggle}
        className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-1.5 flex-shrink-0 mt-0.5">
          <span className="text-xs font-mono text-gray-400 w-8 text-right">#{chunk.chunk_index + 1}</span>
          {expanded ? <ChevronUp size={13} className="text-gray-400" /> : <ChevronDown size={13} className="text-gray-400" />}
        </div>

        <div className="flex-1 min-w-0">
          {/* Section + page info */}
          <div className="flex items-center gap-3 mb-1.5">
            {chunk.section_title && (
              <span className="text-xs font-medium text-gray-600 truncate">{chunk.section_title}</span>
            )}
            {chunk.page_number && (
              <span className="text-xs text-gray-400 flex-shrink-0">p.{chunk.page_number}</span>
            )}
            <span className="text-xs text-gray-400 flex-shrink-0">{chunk.token_count} tokens</span>
          </div>

          {/* Content preview */}
          <p className="text-xs text-gray-500 leading-relaxed line-clamp-2">{contentPreview}{chunk.content.length > 300 ? '...' : ''}</p>

          {/* Control tags */}
          {chunk.tags.length > 0 ? (
            <div className="flex flex-wrap gap-1 mt-2">
              {chunk.tags.map(t => <ControlBadge key={t.control_id} tag={t} />)}
            </div>
          ) : (
            <span className="mt-2 inline-block text-xs text-gray-400 italic">No controls tagged</span>
          )}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 bg-gray-50">
          <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed max-h-80 overflow-y-auto">
            {chunk.content}
          </pre>
          {chunk.tags.length > 0 && (
            <div className="mt-3 space-y-2">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Tagged Controls</p>
              {chunk.tags.map(t => (
                <div key={t.control_id} className="flex items-start gap-3">
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <span className={`inline-flex items-center text-xs font-mono font-bold px-2 py-0.5 rounded border ${confidenceColor(t.confidence)}`}>
                      {t.control_id}
                    </span>
                    <ControlReferenceButton controlId={t.control_id} iconOnly />
                    <div className="flex items-center gap-1">
                      <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${confidenceBar(t.confidence)}`} style={{ width: `${Math.round(t.confidence * 100)}%` }} />
                      </div>
                      <span className="text-xs text-gray-500">{Math.round(t.confidence * 100)}%</span>
                    </div>
                  </div>
                  <p className="text-xs text-gray-600 leading-relaxed">{t.notes}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function DocumentExplorer({ projectId, providerId, policyLibraryId, procedureLibraryId, doc, onClose }) {
  // Build the correct chunks URL based on which owner type is provided
  const chunksUrl = procedureLibraryId
    ? `/enterprise-procedures/libraries/${procedureLibraryId}/documents/${doc.id}/chunks`
    : policyLibraryId
      ? `/enterprise-policies/libraries/${policyLibraryId}/documents/${doc.id}/chunks`
      : providerId
        ? `/common-controls/providers/${providerId}/documents/${doc.id}/chunks`
        : `/projects/${projectId}/documents/${doc.id}/chunks`
  const [search, setSearch] = useState('')
  const [expandedChunks, setExpandedChunks] = useState(new Set())
  const [filterFamily, setFilterFamily] = useState('ALL')
  const [showUntaggedOnly, setShowUntaggedOnly] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['doc-chunks', chunksUrl],
    queryFn: () => api.get(chunksUrl).then(r => r.data),
    staleTime: 30_000,
  })

  const toggleChunk = (id) => {
    setExpandedChunks(prev => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  const expandAll = () => setExpandedChunks(new Set(data?.chunks?.map(c => c.id) || []))
  const collapseAll = () => setExpandedChunks(new Set())

  // Derive unique control families from tags
  const families = useMemo(() => {
    if (!data?.chunks) return []
    const fams = new Set()
    data.chunks.forEach(c => c.tags.forEach(t => fams.add(t.control_id.split('-')[0])))
    return ['ALL', ...Array.from(fams).sort()]
  }, [data])

  // Filter chunks
  const visibleChunks = useMemo(() => {
    if (!data?.chunks) return []
    return data.chunks.filter(c => {
      if (showUntaggedOnly && c.tags.length > 0) return false
      if (filterFamily !== 'ALL' && !c.tags.some(t => t.control_id.startsWith(filterFamily + '-'))) return false
      if (search && !c.tags.some(t => t.control_id.toLowerCase().includes(search.toLowerCase())) &&
          !c.content.toLowerCase().includes(search.toLowerCase()) &&
          !(c.section_title || '').toLowerCase().includes(search.toLowerCase())) return false
      return true
    })
  }, [data, search, filterFamily, showUntaggedOnly])

  const totalTagged = data?.chunks?.filter(c => c.tags.length > 0).length || 0
  const totalUntagged = (data?.total_chunks || 0) - totalTagged

  return (
    <div className="fixed inset-0 z-50 flex items-stretch" onClick={onClose}>
      {/* Backdrop */}
      <div className="flex-1 bg-black/40" />

      {/* Drawer */}
      <div
        className="w-full max-w-3xl bg-white shadow-2xl flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-200 bg-gray-50 flex-shrink-0">
          <div className="flex items-start gap-3 min-w-0">
            <FileSearch size={20} className="text-blue-600 flex-shrink-0 mt-0.5" />
            <div className="min-w-0">
              <h2 className="font-semibold text-gray-900 text-sm truncate">{doc.filename}</h2>
              <p className="text-xs text-gray-500 mt-0.5">Evidence Explorer - control-linked evidence excerpts</p>
            </div>
          </div>
          <div className="ml-3 flex items-center gap-2">
            <button
              type="button"
              onClick={() => openCyberAssistant({
                mode: 'workspace',
                title: `${doc.filename} Assistant`,
                projectId: projectId ?? null,
                attachments: [{
                  type: 'document',
                  resource_id: String(doc.id),
                  context_json: {
                    label: `Document: ${doc.filename}`,
                    filename: doc.filename,
                    provider_id: providerId ?? null,
                    policy_library_id: policyLibraryId ?? null,
                    procedure_library_id: procedureLibraryId ?? null,
                  },
                }],
              })}
              className="inline-flex items-center gap-1.5 rounded-lg border border-violet-200 bg-violet-50 px-2.5 py-1.5 text-xs font-medium text-violet-700 hover:bg-violet-100 transition-colors"
              title={`Ask AI about ${doc.filename}`}
            >
              <MessageSquare size={13} />
              Ask AI
            </button>
            <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700 flex-shrink-0">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Stats bar */}
        {data && (
          <div className="grid grid-cols-4 divide-x divide-gray-100 border-b border-gray-200 flex-shrink-0">
            {[
              { icon: <Layers size={14} />, label: 'Chunks', value: data.total_chunks },
              { icon: <Tag size={14} />, label: 'Tags', value: data.total_tags },
              { icon: <Hash size={14} />, label: 'Controls', value: data.unique_controls },
              { icon: <File size={14} />, label: 'Untagged', value: totalUntagged, warn: totalUntagged > 0 },
            ].map(({ icon, label, value, warn }) => (
              <div key={label} className={`flex items-center gap-2 px-4 py-3 ${warn && value > 0 ? 'bg-amber-50' : ''}`}>
                <span className={warn && value > 0 ? 'text-amber-500' : 'text-gray-400'}>{icon}</span>
                <div>
                  <div className={`text-lg font-bold leading-none ${warn && value > 0 ? 'text-amber-700' : 'text-gray-800'}`}>{value}</div>
                  <div className="text-xs text-gray-400">{label}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Parse error banner */}
        {data?.parse_error && (
          <div className="flex items-start gap-2 px-5 py-2.5 bg-amber-50 border-b border-amber-100 text-xs text-amber-800 flex-shrink-0">
            <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
            {data.parse_error}
          </div>
        )}

        {/* Filters */}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-gray-100 flex-shrink-0 bg-white">
          <div className="relative flex-1">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Search evidence, controls, section titles..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
          </div>
          <select
            value={filterFamily}
            onChange={e => setFilterFamily(e.target.value)}
            className="text-xs border border-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
          >
            {families.map(f => <option key={f}>{f}</option>)}
          </select>
          <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer flex-shrink-0">
            <input type="checkbox" checked={showUntaggedOnly} onChange={e => setShowUntaggedOnly(e.target.checked)} className="rounded" />
            Untagged only
          </label>
          <div className="flex gap-1 flex-shrink-0">
            <button onClick={expandAll} className="text-xs text-blue-600 hover:text-blue-800 px-1">Expand all</button>
            <span className="text-gray-300">|</span>
            <button onClick={collapseAll} className="text-xs text-blue-600 hover:text-blue-800 px-1">Collapse</button>
          </div>
        </div>

        {/* Chunk list */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading && (
            <div className="flex items-center justify-center py-16 text-gray-400">
              <Loader2 size={20} className="animate-spin mr-2" />
              Loading evidence...
            </div>
          )}
          {isError && (
            <div className="flex items-center justify-center py-16 text-red-500 text-sm gap-2">
              <AlertCircle size={16} />Failed to load document chunks
            </div>
          )}
          {data && visibleChunks.length === 0 && (
            <div className="text-center py-12 text-gray-400 text-sm">
              {data.total_chunks === 0
                ? 'Document has no evidence excerpts yet - it may still be parsing.'
                : 'No evidence excerpts match the current filter.'}
            </div>
          )}
          {data && visibleChunks.map(chunk => (
            <ChunkRow
              key={chunk.id}
              chunk={chunk}
              expanded={expandedChunks.has(chunk.id)}
              onToggle={() => toggleChunk(chunk.id)}
              highlight={search}
            />
          ))}
        </div>

        {/* Footer count */}
        {data && (
          <div className="px-5 py-2 border-t border-gray-100 text-xs text-gray-400 flex-shrink-0 bg-gray-50">
            Showing {visibleChunks.length} of {data.total_chunks} evidence excerpts
            {filterFamily !== 'ALL' && ` - filtered to ${filterFamily} family`}
            {showUntaggedOnly && ' - untagged only'}
          </div>
        )}
      </div>
    </div>
  )
}
