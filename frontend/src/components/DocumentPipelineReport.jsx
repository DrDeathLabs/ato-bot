/**
 * DocumentPipelineReport — slide-over panel showing ingestion quality metrics
 * for a single document: pipeline funnel, control distribution, evidence units.
 */
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, ChevronLeft, ChevronRight, Filter, AlertCircle, CheckCircle, Zap, Layers, Tag, File } from 'lucide-react'
import api from '../api/client'
import { ControlReferenceButton } from './ControlReference'

// ── Colour helpers ─────────────────────────────────────────────────────────────

const STRENGTH_COLOR = {
  strong:       'bg-green-100 text-green-800 border-green-200',
  moderate:     'bg-blue-100 text-blue-800 border-blue-200',
  weak:         'bg-yellow-100 text-yellow-800 border-yellow-200',
  insufficient: 'bg-gray-100 text-gray-600 border-gray-200',
}

const STRENGTH_BAR = {
  strong:       'bg-green-500',
  moderate:     'bg-blue-500',
  weak:         'bg-yellow-400',
  insufficient: 'bg-gray-300',
}

const ARTIFACT_LABELS = {
  policy:                   'Policy',
  procedure:                'Procedure',
  implementation_statement: 'Impl. Statement',
  technical_config:         'Technical Config',
  operational:              'Operational',
  test_evidence:            'Test Evidence',
  management:               'Management',
  diagram_narrative:        'Diagram/Narrative',
  audit_artifact:           'Audit Artifact',
  other:                    'Other',
}

// ── Funnel bar ─────────────────────────────────────────────────────────────────

function FunnelRow({ label, value, max, color = 'bg-blue-500', sub }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs text-gray-600">
        <span>{label}</span>
        <span className="font-medium tabular-nums">{value.toLocaleString()}{sub && <span className="text-gray-400"> ({pct}%)</span>}</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-2 rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ── Evidence unit card ─────────────────────────────────────────────────────────

function UnitCard({ unit }) {
  const [expanded, setExpanded] = useState(false)
  const cls = unit.classification

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-start gap-2 px-3 py-2 bg-gray-50 border-b border-gray-200">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap gap-1 items-center">
            {cls?.control_ids?.map(c => (
              <span key={c} className="inline-flex items-center gap-1">
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono font-medium bg-indigo-100 text-indigo-800 border border-indigo-200">
                  {c}
                </span>
                <ControlReferenceButton controlId={c} iconOnly />
              </span>
            ))}
            {cls?.enhancement_ids?.slice(0, 3).map(e => (
              <span key={e} className="inline-flex items-center gap-1">
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono text-gray-500 bg-gray-100 border border-gray-200">
                  {e}
                </span>
                <ControlReferenceButton controlId={e} iconOnly />
              </span>
            ))}
            {(!cls?.control_ids?.length) && (
              <span className="text-xs text-gray-400 italic">No controls identified</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {cls?.evidence_strength && (
            <span className={`text-xs font-medium px-1.5 py-0.5 rounded border ${STRENGTH_COLOR[cls.evidence_strength] || 'bg-gray-100 text-gray-600'}`}>
              {cls.evidence_strength}
            </span>
          )}
          {cls?.artifact_type && (
            <span className="text-xs text-gray-500 bg-white border border-gray-200 px-1.5 py-0.5 rounded">
              {ARTIFACT_LABELS[cls.artifact_type] || cls.artifact_type}
            </span>
          )}
          {unit.page_numbers?.length > 0 && (
            <span className="text-xs text-gray-400">p.{unit.page_numbers[0]}</span>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="px-3 py-2">
        {unit.section_path && (
          <div className="text-xs text-gray-400 mb-1 truncate" title={unit.section_path}>
            § {unit.section_path}
          </div>
        )}
        <p className={`text-xs text-gray-700 leading-relaxed whitespace-pre-wrap ${expanded ? '' : 'line-clamp-4'}`}>
          {unit.content}
        </p>
        {(unit.content_truncated || unit.content?.length > 300) && (
          <button
            onClick={() => setExpanded(v => !v)}
            className="mt-1 text-xs text-blue-600 hover:underline"
          >
            {expanded ? 'Show less' : 'Show more'}
          </button>
        )}
        {cls?.explanation && (
          <div className="mt-2 pt-2 border-t border-gray-100">
            <p className="text-xs text-gray-500 italic leading-relaxed">{cls.explanation}</p>
            {cls.model_name && (
              <span className="text-xs text-gray-400">via {cls.model_name}</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function DocumentPipelineReport({ documentId, documentName, onClose }) {
  const PAGE_SIZE = 20

  const [page, setPage]               = useState(0)
  const [controlFilter, setControlFilter] = useState('')
  const [strengthFilter, setStrengthFilter] = useState('')
  const [activeControl, setActiveControl]  = useState(null)

  // Reset page when filters change
  useEffect(() => { setPage(0) }, [controlFilter, strengthFilter, activeControl])

  const effectiveControl = activeControl || controlFilter || undefined
  const effectiveStrength = strengthFilter || undefined

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['pipeline-report', documentId, page, effectiveControl, effectiveStrength],
    queryFn: () =>
      api.get(`/ingestion-config/document-report/${documentId}`, {
        params: {
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
          ...(effectiveControl ? { control_filter: effectiveControl } : {}),
          ...(effectiveStrength ? { strength_filter: effectiveStrength } : {}),
        },
      }).then(r => r.data),
    enabled: !!documentId,
  })

  const funnel   = data?.funnel
  const run      = data?.run
  const dist     = data?.control_distribution || []
  const units    = data?.evidence_units || []
  const total    = data?.total_filtered ?? data?.total_units ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)

  const strengthCounts = data?.strength_counts || {}
  const artifactCounts = data?.artifact_counts || {}
  const totalUnits = funnel?.evidence_units || 1

  const clearFilters = () => {
    setControlFilter('')
    setStrengthFilter('')
    setActiveControl(null)
  }
  const hasFilter = effectiveControl || effectiveStrength

  return (
    /* Slide-over backdrop */
    <div className="fixed inset-0 z-50 flex justify-end" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      {/* Panel */}
      <div className="relative w-full max-w-3xl bg-white shadow-2xl flex flex-col h-full overflow-hidden">

        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-200 bg-gray-50 flex-shrink-0">
          <Layers size={18} className="text-indigo-600 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-gray-900 truncate">Pipeline Report</h2>
            <p className="text-xs text-gray-500 truncate">{documentName}</p>
          </div>
          {run && (
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full border flex-shrink-0 ${
              run.status === 'complete' ? 'bg-green-50 text-green-700 border-green-200' :
              run.status === 'failed'   ? 'bg-red-50 text-red-700 border-red-200' :
              'bg-yellow-50 text-yellow-700 border-yellow-200'
            }`}>
              {run.status}
            </span>
          )}
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0">
            <X size={18} />
          </button>
        </div>

        {isLoading && (
          <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
            Loading report…
          </div>
        )}

        {isError && (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-sm px-8 text-center">
            {error?.response?.status === 404 ? (
              <>
                <AlertCircle size={24} className="text-amber-400" />
                <p className="font-medium text-gray-700">No pipeline run found for this document</p>
                <p className="text-gray-500 max-w-sm">
                  This document was indexed before the new ingestion pipeline was introduced.
                  Use <strong>Re-index</strong> on the document to run it through the new pipeline
                  and generate a report.
                </p>
              </>
            ) : (
              <>
                <AlertCircle size={20} className="text-red-400" />
                <span className="text-red-500">Failed to load report</span>
              </>
            )}
          </div>
        )}

        {data && (
          <div className="flex-1 overflow-y-auto">

            {/* ── Processing funnel ─────────────────────────────── */}
            <section className="px-5 py-4 border-b border-gray-100">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Pipeline Funnel</h3>
              <div className="space-y-2">
                <FunnelRow label="Lines parsed"           value={funnel.lines_parsed}           max={funnel.lines_parsed}           color="bg-gray-400" />
                <FunnelRow label="Lines screened"         value={funnel.lines_screened}         max={funnel.lines_parsed}           color="bg-gray-400" sub />
                <FunnelRow label="Above NIST threshold"   value={funnel.lines_above_threshold}  max={funnel.lines_parsed}           color="bg-blue-400" sub />
                <FunnelRow label="Evidence units created" value={funnel.evidence_units}         max={funnel.lines_parsed}           color="bg-indigo-500" sub />
                <FunnelRow label="Units classified"       value={funnel.units_classified}       max={funnel.evidence_units || 1}    color="bg-purple-500" sub />
                <FunnelRow label="Units embedded"         value={funnel.units_embedded}         max={funnel.evidence_units || 1}    color="bg-green-500" sub />
              </div>
              {run?.error_message && (
                <div className="mt-3 flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
                  <AlertCircle size={12} className="mt-0.5 flex-shrink-0" />
                  <span><strong>Stage {run.error_stage}:</strong> {run.error_message}</span>
                </div>
              )}
            </section>

            {/* ── Strength + Artifact breakdown ─────────────────── */}
            <section className="px-5 py-4 border-b border-gray-100 grid grid-cols-2 gap-6">
              {/* Evidence strength */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Evidence Strength</h3>
                <div className="space-y-1.5">
                  {['strong','moderate','weak','insufficient'].map(s => {
                    const count = strengthCounts[s] || 0
                    const pct = totalUnits > 0 ? Math.round((count / totalUnits) * 100) : 0
                    return (
                      <div key={s} className="flex items-center gap-2">
                        <button
                          onClick={() => setStrengthFilter(v => v === s ? '' : s)}
                          className={`flex-1 flex items-center gap-2 text-left rounded px-1.5 py-0.5 transition-colors ${strengthFilter === s ? 'ring-1 ring-indigo-400 bg-indigo-50' : 'hover:bg-gray-50'}`}
                        >
                          <div className={`h-2 rounded-full flex-shrink-0 ${STRENGTH_BAR[s]}`} style={{ width: `${Math.max(pct, 2)}%`, minWidth: '6px', maxWidth: '60%' }} />
                          <span className="text-xs text-gray-600 capitalize">{s}</span>
                        </button>
                        <span className="text-xs font-medium text-gray-700 tabular-nums w-8 text-right">{count}</span>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Artifact type */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Artifact Types</h3>
                <div className="space-y-1">
                  {Object.entries(artifactCounts)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 6)
                    .map(([type, count]) => (
                      <div key={type} className="flex justify-between text-xs">
                        <span className="text-gray-600 truncate">{ARTIFACT_LABELS[type] || type}</span>
                        <span className="font-medium text-gray-700 tabular-nums ml-2">{count}</span>
                      </div>
                    ))
                  }
                </div>
              </div>
            </section>

            {/* ── Control distribution ──────────────────────────── */}
            {dist.length > 0 && (
              <section className="px-5 py-4 border-b border-gray-100">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Control Coverage <span className="text-gray-400 font-normal">({dist.length} controls)</span>
                  </h3>
                  {activeControl && (
                    <button onClick={() => setActiveControl(null)} className="text-xs text-indigo-600 hover:underline flex items-center gap-1">
                      <X size={10} /> Clear filter
                    </button>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-x-6 gap-y-1 max-h-48 overflow-y-auto pr-1">
                  {dist.slice(0, 40).map(({ control_id, count, strong, moderate, weak }) => (
                    <button
                      key={control_id}
                      onClick={() => setActiveControl(v => v === control_id ? null : control_id)}
                      className={`flex items-center gap-2 text-left rounded px-1.5 py-1 transition-colors ${activeControl === control_id ? 'bg-indigo-50 ring-1 ring-indigo-300' : 'hover:bg-gray-50'}`}
                    >
                      <span className="flex items-center gap-1 w-20 flex-shrink-0">
                        <span className="font-mono text-xs font-medium text-indigo-700">{control_id}</span>
                        <ControlReferenceButton controlId={control_id} iconOnly />
                      </span>
                      {/* Mini stacked bar */}
                      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden flex">
                        {strong   > 0 && <div className="bg-green-500 h-2"  style={{ width: `${(strong/count)*100}%` }} />}
                        {moderate > 0 && <div className="bg-blue-400 h-2"   style={{ width: `${(moderate/count)*100}%` }} />}
                        {weak     > 0 && <div className="bg-yellow-400 h-2" style={{ width: `${(weak/count)*100}%` }} />}
                      </div>
                      <span className="text-xs text-gray-500 tabular-nums w-6 text-right flex-shrink-0">{count}</span>
                    </button>
                  ))}
                </div>
              </section>
            )}

            {/* ── Evidence units ────────────────────────────────── */}
            <section className="px-5 py-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Evidence Units
                  {hasFilter
                    ? <span className="ml-1 text-indigo-600"> — filtered ({total})</span>
                    : <span className="text-gray-400 font-normal"> ({total})</span>
                  }
                </h3>
                {hasFilter && (
                  <button onClick={clearFilters} className="text-xs text-indigo-600 hover:underline flex items-center gap-1">
                    <X size={10} /> Clear filters
                  </button>
                )}
              </div>

              {/* Inline control search filter */}
              <div className="flex gap-2 mb-3">
                <div className="relative flex-1">
                  <Filter size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    value={controlFilter}
                    onChange={e => setControlFilter(e.target.value)}
                    placeholder="Filter by control ID (e.g. AC-2)"
                    className="w-full pl-7 pr-3 py-1.5 text-xs border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  />
                </div>
                <select
                  value={strengthFilter}
                  onChange={e => setStrengthFilter(e.target.value)}
                  className="text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                >
                  <option value="">All strengths</option>
                  <option value="strong">Strong</option>
                  <option value="moderate">Moderate</option>
                  <option value="weak">Weak</option>
                  <option value="insufficient">Insufficient</option>
                </select>
              </div>

              {units.length === 0 ? (
                <p className="text-xs text-gray-400 text-center py-6">No evidence units match the current filters.</p>
              ) : (
                <div className="space-y-3">
                  {units.map(unit => <UnitCard key={unit.id} unit={unit} />)}
                </div>
              )}

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-3 border-t border-gray-100">
                  <button
                    onClick={() => setPage(p => Math.max(0, p - 1))}
                    disabled={page === 0}
                    className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900 disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <ChevronLeft size={14} /> Previous
                  </button>
                  <span className="text-xs text-gray-500">
                    Page {page + 1} of {totalPages}
                  </span>
                  <button
                    onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                    disabled={page >= totalPages - 1}
                    className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900 disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    Next <ChevronRight size={14} />
                  </button>
                </div>
              )}
            </section>

          </div>
        )}
      </div>
    </div>
  )
}
