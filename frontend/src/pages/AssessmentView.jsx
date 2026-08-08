import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Download, CheckCircle, AlertTriangle, XCircle, MinusCircle,
  ChevronDown, ChevronRight, LayoutList, Rows3, RefreshCw, Wrench,
  StickyNote, Clock, Shield, ArrowUpRight, RotateCcw, Keyboard,
  ChevronUp, SkipForward, Info, Sparkles, PencilLine, Maximize2, X,
  Scale, MessageSquare, Send, File, ClipboardList, FlaskConical, Pause,
} from 'lucide-react'
import api from '../api/client'
import ClosureWorkflow from '../components/ClosureWorkflow'
import { ControlReferenceButton } from '../components/ControlReference'
import { openCyberAssistant } from '../components/cyberAssistant'

// Authenticated file download helper (sends JWT via api client)
const downloadByUrl = async (url, filename) => {
  try {
    const res = await api.get(url, { responseType: 'blob' })
    const href = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = href; a.download = filename; a.click()
    URL.revokeObjectURL(href)
  } catch (e) {
    alert('Download failed: ' + (e.response?.data?.detail || e.message))
  }
}

// Numeric sort: AC-2 < AC-11 < AC-11(1) < AC-11(2)
const parseControlId = (id) => {
  const m = id.match(/^([A-Z]+)-(\d+)(?:\((\d+)\))?/)
  if (!m) return { fam: id, num: 0, enh: 0 }
  return { fam: m[1], num: parseInt(m[2]), enh: parseInt(m[3] || '0') }
}
const sortByControlId = (a, b) => {
  const pa = parseControlId(a.control_id)
  const pb = parseControlId(b.control_id)
  if (pa.fam !== pb.fam) return pa.fam.localeCompare(pb.fam)
  if (pa.num !== pb.num) return pa.num - pb.num
  return pa.enh - pb.enh
}

const fmt12hr = (dt) => {
  if (!dt) return null
  return new Date(dt).toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  })
}

const fmtDate = (dt) => {
  if (!dt) return null
  return new Date(dt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
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

const cleanCatalogText = (text) => {
  if (!text) return ''
  return text
    .replace(/\{\{[^}]+\}\}/g, '[org-defined]')
    .replace(/\s+/g, ' ')
    .replace(/\s*;\s*/g, '; ')
    .trim()
}

const formatCriteriaLines = (text) => {
  const cleaned = cleanCatalogText(text)
  if (!cleaned) return []

  const normalized = cleaned
    .replace(/:\s+(?=[A-Z[])/g, ':\n')
    .replace(/;\s+and\s+/gi, ';\n')
    .replace(/;\s+(?=[A-Z[])/g, ';\n')
    .replace(/\.\s+(?=Review and update|Designate|Develop|Establish|Define|Maintain|Ensure)/g, '.\n')

  return normalized
    .split('\n')
    .map(line => line.trim().replace(/[;.]$/, '').trim())
    .filter(Boolean)
}

const splitSummaryLines = (text) => {
  if (!text) return []
  return text
    .replace(/\\n/g, '\n')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
}

const statusLabel = (status) => ({
  met: 'Met',
  partially_met: 'Partially met',
  partial: 'Partially met',
  not_met: 'Not met',
  non_compliant: 'Not met',
  compliant: 'Met',
})[status] || String(status || 'Needs review').replace(/_/g, ' ')

const titleCaseLabel = (text) => String(text || '')
  .replace(/_/g, ' ')
  .replace(/\s+/g, ' ')
  .trim()
  .toLowerCase()
  .replace(/\b\w/g, (char) => char.toUpperCase())

const formatObjectiveDisplayText = (text) => {
  let value = cleanCatalogText(text)
  if (!value) return 'Objective requirement unavailable.'
  value = value
    .replace(/\bthe\s+\[org-defined\]\s+(?=access control policy|access control procedures)/gi, 'the ')
    .replace(/\bto\s+\[org-defined\]/gi, 'to defined recipients')
    .replace(/\bfollowing\s+\[org-defined\]/gi, 'following defined requirements')
    .replace(/\[org-defined\]/gi, 'organization-defined values')
    .replace(/\s+/g, ' ')
    .trim()
  value = value.charAt(0).toUpperCase() + value.slice(1)
  if (!/[.!?]$/.test(value)) value += '.'
  return value
}

const plural = (count, singular, pluralWord = `${singular}s`) => (
  Number(count) === 1 ? singular : pluralWord
)

const cleanFindingDetail = (text) => {
  const value = cleanCatalogText(text)
  if (!value) return ''
  if (/Bucket=|effective_support=|evidence_quality=|critical=true|weight=/i.test(value)) return ''
  return value
}

const formatStoredDeficiencyLine = (line) => {
  const value = String(line || '').trim()
  if (!value) return ''
  if (/Bucket=|effective_support=|evidence_quality=|critical=true|weight=/i.test(value)) {
    const objectiveId = value.split(':')[0]?.trim()
    return `${objectiveId || 'Objective'}: Evidence does not fully demonstrate this objective.`
  }
  return value
}

const formatObjectiveFinding = (objective) => {
  const objectiveId = objective?.objective_id || 'Objective'
  const label = statusLabel(objective?.status)
  const missingEvidence = cleanFindingDetail(objective?.missing_evidence)
  const rationale = cleanFindingDetail(objective?.rationale)
  const objectiveText = formatObjectiveDisplayText(objective?.objective_text)
  const detail = missingEvidence
    || rationale
    || (objectiveText ? `Evidence does not fully demonstrate: ${objectiveText}` : 'Evidence does not fully demonstrate this objective.')
  return `${objectiveId} (${label}): ${detail}`
}

const readableDeterminationSummary = ({ determination, policySummary, objectives, corroboration }) => {
  const objectiveRows = Array.isArray(objectives) ? objectives : []
  const total = Number(policySummary?.total ?? objectiveRows.length ?? 0)
  if (!total && !determination?.evidence_summary) return 'No evidence summary available.'

  const met = Number(policySummary?.met ?? objectiveRows.filter((row) => row.status === 'met').length)
  const partial = Number(policySummary?.partial ?? objectiveRows.filter((row) => row.status === 'partially_met').length)
  const notMet = Number(policySummary?.not_met ?? objectiveRows.filter((row) => row.status === 'not_met').length)
  const unresolved = Array.isArray(policySummary?.unresolved_objectives)
    ? policySummary.unresolved_objectives.length
    : partial + notMet
  const critical = Array.isArray(policySummary?.critical_failures) ? policySummary.critical_failures.length : 0
  const documents = Number(corroboration?.supporting_documents ?? 0)

  if (total) {
    const statusText = `${met} ${plural(met, 'objective')} met, ${partial} partially met, and ${notMet} not met`
    const unresolvedText = unresolved
      ? `${unresolved} ${plural(unresolved, 'objective')} still need${unresolved === 1 ? 's' : ''} evidence review${critical ? `, including ${critical} critical ${plural(critical, 'objective')}` : ''}.`
      : 'All objectives are supported by the reviewed evidence.'
    const documentText = documents
      ? `The determination cites evidence from ${documents} supporting ${plural(documents, 'document')}.`
      : 'No supporting documents were cited for this determination.'
    return `Reviewed ${total} ${plural(total, 'objective')}: ${statusText}. ${unresolvedText} ${documentText}`
  }

  return determination?.evidence_summary || 'No evidence summary available.'
}

const isGenericObjectiveBasis = (text) => (
  !text
  || /^the reviewed evidence supports this assessment objective\.?$/i.test(String(text).trim())
  || /^the reviewed evidence does not fully demonstrate this assessment objective\.?$/i.test(String(text).trim())
)

const shortEvidenceQuote = (text, max = 260) => {
  const cleaned = cleanEvidenceExcerpt(text)
  if (!cleaned) return ''
  if (cleaned.length <= max) return cleaned
  const clipped = cleaned.slice(0, max)
  const lastStop = Math.max(clipped.lastIndexOf('. '), clipped.lastIndexOf('; '), clipped.lastIndexOf(', '))
  return `${clipped.slice(0, lastStop > 120 ? lastStop + 1 : max).trim()}...`
}

const objectiveBasisText = (objective, detail = {}, reviews = [], docMap = null) => {
  const missingEvidence = cleanFindingDetail(objective?.missing_evidence)
  const rationale = cleanFindingDetail(objective?.rationale)
  const usefulRationale = isGenericObjectiveBasis(rationale) ? '' : rationale
  const supporting = (reviews || []).filter((item) => item.review_role === 'supporting')
  const contradictory = (reviews || []).filter((item) => item.review_role === 'contradictory')
  const partial = (reviews || []).filter((item) => item.review_role === 'partial')
  const strongest = distinctEvidenceItems(supporting)
    .sort((a, b) => evidenceRelevance(b) - evidenceRelevance(a))[0]
  const sourceTitle = strongest ? evidenceSourceTitle(strongest, docMap) : ''
  const supportingDocs = Number(detail?.objective_corroboration?.supporting_documents || 0)
  const sourceTypes = detail?.objective_corroboration?.source_types || []
  const artifactTypes = detail?.objective_corroboration?.artifact_types || []
  const coverageParts = [
    supportingDocs ? `${supportingDocs} supporting document${supportingDocs === 1 ? '' : 's'}` : null,
    sourceTypes.length > 1 ? `${sourceTypes.length} source types` : null,
    artifactTypes.length > 1 ? `${artifactTypes.length} artifact types` : null,
  ].filter(Boolean)
  const coverageText = coverageParts.length ? coverageParts.join(', ') : 'mapped supporting evidence'
  const contradictionText = contradictory.length
    ? `${contradictory.length} contradictory item${contradictory.length === 1 ? '' : 's'} mapped for review`
    : 'no contradictory evidence mapped'

  if (objective?.status === 'met') {
    if (usefulRationale) return usefulRationale
    if (contradictory.length) {
      return `Met, but ${contradictionText}. Open Review Sources to confirm the contradictory item does not affect the determination.`
    }
    return ''
  }
  if (missingEvidence) return missingEvidence
  if (usefulRationale) return usefulRationale
  if (partial.length > 0 || supporting.length > 0) {
    return `Not fully satisfied. Some evidence is mapped to this objective, but the assessment still needs direct source material that demonstrates the full requirement. ${sourceTitle ? `Best available citation: ${sourceTitle}. ` : ''}${contradictionText}.`
  }
  return 'Not fully satisfied. No direct supporting evidence was mapped to this objective.'
}

const cleanEvidenceNote = (text) => {
  const value = cleanCatalogText(text)
  if (!value) return ''
  return value.replace(/\s*\[objectives=.*?\]\s*$/i, '').trim()
}

const evidenceMetaText = (item) => (
  [
    item.source_type,
    item.artifact_type,
    item.document_type,
    item.document_intent,
    item.evidence_strength ? `${item.evidence_strength.replace(/_/g, ' ')} strength` : null,
  ].filter(Boolean).join(' | ')
)

const cleanEvidenceExcerpt = (text) => {
  const value = cleanCatalogText(text)
  if (!value) return ''
  return value
}

const objectiveEvidenceCount = (detail, reviews) => (
  Number(detail?.evidence_map_summary?.considered_packets ?? reviews.length ?? 0)
)

const objectivePromptCount = (detail, reviews) => {
  const promptCount = detail?.evidence_map_summary?.prompt_packets
  if (promptCount != null) return Number(promptCount)
  return (reviews || []).filter((item) => item.used_in_prompt).length
}

const evidenceRelevance = (item) => Number(item?.objective_relevance_score ?? item?.relevance_score ?? 0)

const evidenceFingerprint = (item) => {
  const text = cleanEvidenceExcerpt(item?.excerpt) || cleanEvidenceNote(item?.rationale)
  const normalized = text
    .replace(/^\.\.\.\s*/, '')
    .replace(/\s*\.\.\.$/, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
  if (normalized.length > 80) return normalized.slice(0, 360)
  return [
    item?.document_id || 'no-document',
    normalized || item?.unit_id || 'no-text',
  ].join('|')
}

const distinctEvidenceItems = (items) => {
  const seen = new Map()
  ;(items || []).forEach((item) => {
    const key = evidenceFingerprint(item)
    const existing = seen.get(key)
    if (!existing) {
      seen.set(key, { ...item, _similarCount: 1 })
      return
    }
    existing._similarCount += 1
    if (evidenceRelevance(item) > evidenceRelevance(existing)) {
      seen.set(key, { ...item, _similarCount: existing._similarCount })
    }
  })
  return Array.from(seen.values())
}

const evidenceTitle = (label) => {
  const value = String(label || '').trim()
  if (!value) return 'Evidence item'
  return value
    .replace(/\.(docx|pdf|xlsx|csv|txt)$/i, '')
    .replace(/^TESTPKG[_-]/i, '')
    .replace(/_/g, ' ')
}

const resolveEvidenceDocument = (item, docMap) => {
  if (!item || !docMap) return null
  if (item.document_id != null && docMap[`id:${item.document_id}`]) return docMap[`id:${item.document_id}`]
  const label = String(item.citation_label || item.source || '').trim()
  if (label && docMap[label]) return docMap[label]
  const cleaned = label
    .replace(/^(?:Document|Excerpt)\s+\d+[:\s]+/i, '')
    .replace(/\s*\((?:Document|Excerpt)\s+\d+\)\s*$/i, '')
    .trim()
  return cleaned ? docMap[cleaned] : null
}

const evidenceSourceTitle = (item, docMap) => {
  const docRef = resolveEvidenceDocument(item, docMap)
  if (docRef?.filename) return evidenceTitle(docRef.filename)
  if (item?.citation_label) return evidenceTitle(item.citation_label)
  if (item?.document_id) return `Document ${item.document_id}`
  return 'Evidence item'
}

const normalizeEvidenceMatch = (text) => String(text || '')
  .replace(/^(?:Document|Excerpt)\s+\d+[:\s]+/i, '')
  .replace(/\s*\((?:Document|Excerpt)\s+\d+\)\s*$/i, '')
  .replace(/\.(docx|pdf|xlsx|csv|txt)$/i, '')
  .replace(/[_-]+/g, ' ')
  .replace(/\s+/g, ' ')
  .trim()
  .toLowerCase()

const citationObjectiveLabel = (citation, fallback = '') => (
  citation?.objective_id
  || citation?.objective
  || citation?.control_objective
  || citation?.criteria_id
  || citation?.control_id
  || fallback
  || ''
)

const findCitationEvidenceUnit = (citation, triage, docMap) => {
  if (!citation || !triage?.length) return null
  const source = citation.source || citation.document || ''
  const cleanSource = source
    .replace(/^(?:Document|Excerpt)\s+\d+[:\s]+/i, '')
    .replace(/\s*\((?:Document|Excerpt)\s+\d+\)\s*$/i, '')
    .trim()
  const docRef = docMap ? (docMap[source] ?? docMap[cleanSource]) : null
  const sourceKey = normalizeEvidenceMatch(cleanSource || source)
  const quoteKey = normalizeEvidenceMatch(citation.excerpt || citation.quote)
  const objectiveKey = normalizeEvidenceMatch(citationObjectiveLabel(citation))

  let best = null
  let bestScore = 0
  ;(triage || []).forEach((item) => {
    let score = 0
    if (citation.unit_id && item.unit_id === citation.unit_id) score += 100
    if (citation.document_id && item.document_id === citation.document_id) score += 60
    if (docRef?.id && item.document_id === docRef.id) score += 50

    const itemLabel = normalizeEvidenceMatch(item.citation_label)
    const itemText = normalizeEvidenceMatch(`${item.excerpt || ''} ${item.rationale || ''}`)
    if (sourceKey && itemLabel && (itemLabel.includes(sourceKey) || sourceKey.includes(itemLabel))) score += 25
    if (objectiveKey && itemText.includes(objectiveKey)) score += 20
    if (quoteKey && itemText.includes(quoteKey.slice(0, Math.min(quoteKey.length, 80)))) score += 30
    score += Math.min(evidenceRelevance(item), 5)

    if (score > bestScore) {
      best = item
      bestScore = score
    }
  })
  return bestScore >= 20 ? best : null
}

const looksLikeAssessmentNarrative = (text) => (
  /^(the excerpt|this excerpt|evidence (shows|documents|confirms)|the implemented setting|the evidence|source evidence|the system satisfies|this supports)\b/i
    .test(String(text || '').trim())
)

const evidenceRoleLabel = (role) => ({
  supporting: 'Supporting',
  contradictory: 'Contradictory',
  partial: 'Partial',
  context: 'Context',
  irrelevant: 'Context',
})[role] || String(role || 'Evidence').replace(/_/g, ' ')

const evidenceRoleConfig = {
  supporting: {
    label: 'Supporting Evidence',
    empty: 'No supporting evidence was mapped to this objective.',
    tone: 'emerald',
  },
  contradictory: {
    label: 'Contradictory Evidence',
    empty: 'No contradictory evidence was mapped to this objective.',
    tone: 'red',
  },
  partial: {
    label: 'Partial or Future-State Evidence',
    empty: 'No partial or future-state evidence was mapped to this objective.',
    tone: 'amber',
  },
  context: {
    label: 'Context Evidence',
    empty: 'No context evidence was mapped to this objective.',
    tone: 'slate',
  },
}

function EvidenceReviewCard({ item, role, index, docMap, onOpenEvidence }) {
  const note = cleanEvidenceNote(item.rationale)
  const excerpt = cleanEvidenceExcerpt(item.excerpt)
  const docRef = resolveEvidenceDocument(item, docMap)
  const title = evidenceSourceTitle(item, docMap)
  return (
    <article key={`${role}-${item.unit_id || index}`} className="rounded-md border border-gray-200 bg-white px-3 py-2">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between mb-1">
        <div className="flex flex-wrap items-center gap-2">
          {docRef?.download_url ? (
            <button
              type="button"
              onClick={() => downloadByUrl(docRef.download_url, docRef.filename || title)}
              className="text-xs font-semibold text-blue-700 hover:text-blue-900 hover:underline text-left"
              title={`Open ${docRef.filename || title}`}
            >
              {title}
            </button>
          ) : (
            <span className="text-xs font-semibold text-gray-900">{title}</span>
          )}
          {item.used_in_prompt && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700">
              cited in assessment
            </span>
          )}
        </div>
        <span className="text-[11px] text-gray-500">
          Relevance {evidenceRelevance(item).toFixed(2)}
        </span>
      </div>
      {!!evidenceMetaText(item) && (
        <p className="text-xs text-gray-500 mb-1">{evidenceMetaText(item)}</p>
      )}
      {item.keyword_hits?.length > 0 && (
        <p className="text-[11px] text-sky-700 mb-1">
          Matched terms: {item.keyword_hits.slice(0, 8).join(', ')}
        </p>
      )}
      {excerpt ? (
        <div className="mt-2 border-l-2 border-blue-300 pl-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-700 mb-1">Source Excerpt</p>
          <p className="text-sm text-gray-800 leading-relaxed">{excerpt}</p>
        </div>
      ) : (
        <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
          <p className="text-xs font-semibold text-amber-800">Source excerpt not captured</p>
          <p className="text-xs text-amber-700 mt-0.5">This item has assessment context, but no stored source excerpt to quote directly.</p>
        </div>
      )}
      {item._similarCount > 1 && (
        <p className="text-xs text-indigo-600 mt-2">
          {item._similarCount} overlapping source excerpts were collapsed into this preview card.
        </p>
      )}
      {note && (
        <details className="mt-2 rounded-md border border-gray-100 bg-gray-50 px-3 py-2">
          <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-gray-500">
            Assessment Interpretation
          </summary>
          <p className="text-xs text-gray-600 leading-relaxed mt-2">{note}</p>
        </details>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onOpenEvidence?.({ item, title, docRef, excerpt, note })}
          className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100"
        >
          <Maximize2 size={11} />
          Open source
        </button>
        {docRef?.download_url && (
          <button
            type="button"
            onClick={() => downloadByUrl(docRef.download_url, docRef.filename || title)}
            className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-100"
          >
            <Download size={11} />
            Open document
          </button>
        )}
      </div>
    </article>
  )
}

const parseManualReviewReasons = (notes) => {
  if (!notes || !notes.includes('Manual review reasons:')) return []
  return notes
    .split('Manual review reasons:', 2)[1]
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

const getDisplayReviewReasons = (finding) =>
  parseManualReviewReasons(finding?.notes).filter((reason) => reason !== 'inherited_support_requires_review')

const needsDisplayReview = (finding) =>
  Boolean(finding?.needs_manual_review && getDisplayReviewReasons(finding).length > 0)

const buildEvidenceAssistantPrompt = ({
  controlId,
  citationLabel,
  triageRole,
  excerpt,
}) => {
  const scope = citationLabel || `the selected evidence for ${controlId}`
  const evidenceRole = triageRole || 'relevant'
  const excerptNote = excerpt
    ? `Use the attached excerpt as the primary grounding source:\n"${excerpt}"`
    : 'Use the attached evidence context as the grounding source.'

  return (
    `Explain how ${scope} affects control ${controlId}. ` +
    `State whether it appears ${evidenceRole}, what assessment objective(s) it most likely supports or challenges, ` +
    `how strong the evidence is, and what limitations or missing context an assessor should note. ` +
    `Keep the explanation grounded in the attached control and evidence only.\n\n${excerptNote}`
  )
}

// â”€â”€ AI Generate Button â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function AiGenerateButton({ section, payload, onGenerated, className = '' }) {
  const [loading, setLoading] = useState(false)

  const generate = async () => {
    setLoading(true)
    try {
      const resp = await api.post('/ai-assist/notes', { section, ...payload })
      onGenerated(resp.data.text)
    } catch (e) {
      const detail = e.response?.data?.detail
      const msg = typeof detail === 'string' ? detail
        : Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('; ')
        : detail ? JSON.stringify(detail)
        : (e.message || 'Unknown error')
      alert('AI generation failed: ' + msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <button
      type="button"
      onClick={generate}
      disabled={loading}
      title="Generate with AI"
      className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded border border-violet-200 text-violet-600 bg-violet-50 hover:bg-violet-100 hover:border-violet-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors ${className}`}
    >
      <Sparkles size={11} className={loading ? 'animate-spin' : ''} />
      {loading ? 'Generating...' : 'AI Draft'}
    </button>
  )
}

// â”€â”€ Expanding Textarea â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Preview textarea that opens a centered modal overlay for comfortable editing
function ExpandingTextarea({ value, onChange, className = '', placeholder = '', rows, disabled, readOnly, aiSection, aiPayload, ...props }) {
  const [open, setOpen] = useState(false)
  const modalRef = useRef(null)

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
      {/* Read-only preview textarea â€” clicking opens modal */}
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
                ref={modalRef}
                autoFocus
                value={value || ''}
                onChange={onChange}
                placeholder={placeholder}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-300"
                style={{ minHeight: '50vh' }}
              />
            </div>
            {/* Footer */}
            <div className="flex items-center justify-between px-5 py-3 border-t border-gray-100">
              <div>
                {aiSection && aiPayload && (
                  <AiGenerateButton
                    section={aiSection}
                    payload={aiPayload}
                    onGenerated={(text) => onChange({ target: { value: text } })}
                  />
                )}
              </div>
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

// â”€â”€ Override Indicator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Small badge shown when assessor has set a manual override on a control
function OverrideIndicator({ override }) {
  if (!override) return null
  const hasManualStatus = !!override.manual_status
  const hasApplicability = !!override.applicability
  if (!hasManualStatus && !hasApplicability) return null
  const parts = []
  if (hasManualStatus) parts.push(`Status: ${override.manual_status.replace(/_/g, ' ')}`)
  if (hasApplicability) parts.push(`App: ${override.applicability.replace(/_/g, ' ')}`)
  return (
    <span
      title={`Assessor overrides active - ${parts.join(' | ')}`}
      className="inline-flex items-center gap-0.5 text-[9px] font-semibold bg-purple-100 text-purple-700 border border-purple-200 px-1 py-0.5 rounded ml-1 leading-none"
    >
      <PencilLine size={8} />M
    </span>
  )
}

const STATUS_CONFIG = {
  compliant: { label: 'Compliant', color: 'bg-green-600 text-white', dot: 'bg-green-600', icon: CheckCircle, cardBg: 'bg-green-50', cardBorder: 'border-green-300', numColor: 'text-green-700' },
  partially_compliant: { label: 'Partial', color: 'bg-amber-500 text-white', dot: 'bg-amber-500', icon: AlertTriangle, cardBg: 'bg-amber-50', cardBorder: 'border-amber-300', numColor: 'text-amber-700' },
  non_compliant: { label: 'Non-Compliant', color: 'bg-red-600 text-white', dot: 'bg-red-600', icon: XCircle, cardBg: 'bg-red-50', cardBorder: 'border-red-300', numColor: 'text-red-700' },
  not_applicable: { label: 'N/A', color: 'bg-slate-400 text-white', dot: 'bg-slate-400', icon: MinusCircle, cardBg: 'bg-slate-100', cardBorder: 'border-slate-300', numColor: 'text-slate-600' },
  not_reviewed: { label: 'Pending', color: 'bg-orange-500 text-white', dot: 'bg-orange-500', icon: MinusCircle, cardBg: 'bg-orange-50', cardBorder: 'border-orange-300', numColor: 'text-orange-700' },
}

const FAMILY_NAMES = {
  AC: 'Access Control', AT: 'Awareness & Training', AU: 'Audit & Accountability',
  CA: 'Assessment & Authorization', CM: 'Configuration Management', CP: 'Contingency Planning',
  IA: 'Identification & Authentication', IR: 'Incident Response', MA: 'Maintenance',
  MP: 'Media Protection', PE: 'Physical & Environmental', PL: 'Planning',
  PM: 'Program Management', PS: 'Personnel Security', PT: 'PII Processing',
  RA: 'Risk Assessment', SA: 'System Acquisition', SC: 'System & Comms Protection',
  SI: 'System & Info Integrity', SR: 'Supply Chain Risk',
}

// Returns the status to display â€” manual override takes precedence over finding status
const effectiveStatus = (findingStatus, override) =>
  override?.manual_status || findingStatus

function StatusBadge({ status, override }) {
  const displayStatus = effectiveStatus(status, override)
  const cfg = STATUS_CONFIG[displayStatus] || STATUS_CONFIG.not_reviewed
  const Icon = cfg.icon
  const isOverridden = override?.manual_status && override.manual_status !== status
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${cfg.color} ${isOverridden ? 'ring-2 ring-purple-400 ring-offset-1' : ''}`}>
      <Icon size={10} />
      {cfg.label}
    </span>
  )
}

function OverrideBadges({ f }) {
  const manualReviewReasons = getDisplayReviewReasons(f)
  const manualReviewLabel = manualReviewReasons.includes('weak_evidence')
    ? 'Evidence Thin'
    : manualReviewReasons.includes('contradictory_evidence')
      ? 'Contradiction'
      : manualReviewReasons.includes('inherited_support_requires_review')
        ? 'Inherited Review'
        : 'Needs Review'
  return (
    <span className="flex items-center gap-1 flex-wrap">
      {needsDisplayReview(f) && (
        <span
          className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-800"
          title={manualReviewReasons.length ? `Reviewer attention: ${manualReviewReasons.join(', ')}` : 'Reviewer attention required'}
        >
          <Wrench size={9} /> {manualReviewLabel}
        </span>
      )}
      {f.carried_forward && (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-gray-100 text-gray-500">
          <RotateCcw size={9} /> Carried Forward
        </span>
      )}
      {f.applicability_changed && (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700" title={`Was: ${f.prev_status || 'unknown'}`}>
          <AlertTriangle size={9} /> Applicability Changed
        </span>
      )}
      {f.override_applied === 'satisfied' && (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-green-100 text-green-700">
          <CheckCircle size={9} /> Satisfied
        </span>
      )}
      {f.override_applied === 'inherited' && (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-blue-100 text-blue-700">
          <ArrowUpRight size={9} /> Inherited
        </span>
      )}
      {f.override_applied === 'not_applicable' && (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-gray-100 text-gray-500">
          <MinusCircle size={9} /> N/A (Override)
        </span>
      )}
      {f.override_applied === 'applicable' && (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-yellow-100 text-yellow-700">
          <AlertTriangle size={9} /> Forced Applicable
        </span>
      )}
      {f.synthesized_narrative && (
        <span
          className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700"
          title="Implementation statement was auto-synthesized from gap analysis - no Stage 3 LLM narrative pass was made. Re-run this control to produce a full SSP narrative."
        >
          <Sparkles size={9} /> Synthesized Narrative
        </span>
      )}
    </span>
  )
}

// â”€â”€ Manual Status Override â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const STATUS_LABELS = {
  compliant: 'Compliant',
  partially_compliant: 'Partially Compliant',
  non_compliant: 'Non-Compliant',
  not_applicable: 'Not Applicable',
}

const STATUS_RANK = { compliant: 3, partially_compliant: 2, non_compliant: 1, not_applicable: 0 }

function ManualStatusOverride({ finding, override, onUpsert }) {
  const [showForm, setShowForm] = useState(false)
  const [selectedStatus, setSelectedStatus] = useState(finding.status)
  const [evidence, setEvidence] = useState('')

  const existing = override?.manual_status
  const isUpgrade = STATUS_RANK[selectedStatus] > STATUS_RANK[finding.status]

  const submit = () => {
    if (isUpgrade && !evidence.trim()) {
      alert('Evidence is required when upgrading a status determination.')
      return
    }
    onUpsert({ manual_status: selectedStatus, manual_status_rationale: evidence.trim() || null })
    setShowForm(false)
    setEvidence('')
  }

  const clear = () => {
    if (!window.confirm('Remove manual status override? The control will be re-assessed by the LLM on the next run.')) return
    onUpsert({ clear_manual_status: true })
  }

  return (
    <div>
      <p className="text-xs font-semibold text-gray-500 mb-2">MANUAL STATUS OVERRIDE</p>
      {existing ? (
        <div className="flex items-start justify-between gap-3 p-3 rounded-lg border border-purple-200 bg-purple-50">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-purple-800">Manually set: {STATUS_LABELS[existing]}</span>
              <span className="text-xs bg-purple-200 text-purple-800 px-1.5 py-0.5 rounded font-medium">Protected</span>
            </div>
            {override.manual_status_rationale && (
              <p className="text-xs text-purple-700 mt-0.5">{override.manual_status_rationale}</p>
            )}
            <p className="text-xs text-purple-500 mt-0.5">
              Set by {override.manual_status_set_by || 'assessor'} - automated assessment cannot change this
            </p>
          </div>
          <div className="flex gap-1 flex-shrink-0">
            <button onClick={() => { setSelectedStatus(existing); setShowForm(true) }}
              className="text-xs border border-purple-300 text-purple-700 hover:bg-purple-100 px-2 py-1 rounded">
              Change
            </button>
            <button onClick={clear}
              className="text-xs border border-red-200 text-red-600 hover:bg-red-50 px-2 py-1 rounded">
              Clear
            </button>
          </div>
        </div>
      ) : (
        <div>
          {!showForm ? (
            <button onClick={() => { setSelectedStatus(finding.status); setShowForm(true) }}
              className="text-xs border border-gray-200 text-gray-600 hover:border-purple-300 hover:text-purple-700 px-3 py-1.5 rounded">
              Set Manual Status Override
            </button>
          ) : null}
        </div>
      )}

      {showForm && (
        <div className="mt-2 border border-purple-200 rounded-lg p-3 bg-white">
          <p className="text-xs font-semibold text-gray-600 mb-2">Select Status</p>
          <div className="grid grid-cols-2 gap-1.5 mb-3">
            {Object.entries(STATUS_LABELS).map(([val, label]) => (
              <button
                key={val}
                onClick={() => setSelectedStatus(val)}
                className={`text-xs px-2 py-1.5 rounded border text-left transition-colors ${
                  selectedStatus === val
                    ? 'border-purple-500 bg-purple-50 text-purple-800 font-semibold'
                    : 'border-gray-200 text-gray-600 hover:border-gray-300'
                }`}
              >{label}</button>
            ))}
          </div>
          {isUpgrade && (
            <div className="mb-2 p-2 rounded bg-amber-50 border border-amber-200">
              <p className="text-xs text-amber-800 font-medium mb-1">Upgrading status requires evidence</p>
              <p className="text-xs text-amber-700">Provide documentation or evidence that justifies the improved determination.</p>
            </div>
          )}
          <ExpandingTextarea
            value={evidence}
            onChange={e => setEvidence(e.target.value)}
            rows={3}
            placeholder={isUpgrade ? 'Required: cite specific evidence supporting this determination...' : 'Optional: rationale or notes for this override...'}
            className={`w-full text-xs ${
              isUpgrade && !evidence.trim() ? 'border-amber-300' : 'border-gray-200'
            }`}
            aiSection="manual_status_rationale"
            aiPayload={{ control_id: finding.control_id, control_title: finding.control_title, current_status: finding.status, target_status: selectedStatus }}
          />
          <div className="flex items-center gap-2 mt-2">
            <button onClick={submit}
              className="text-xs bg-purple-700 text-white px-3 py-1 rounded hover:bg-purple-800">
              Set Override
            </button>
            <button onClick={() => { setShowForm(false); setEvidence('') }}
              className="text-xs text-gray-500 hover:text-gray-700 border px-3 py-1 rounded">
              Cancel
            </button>
            <AiGenerateButton section="manual_status_rationale" payload={{ control_id: finding.control_id, control_title: finding.control_title, current_status: finding.status, target_status: selectedStatus }} onGenerated={setEvidence} />
          </div>
        </div>
      )}
    </div>
  )
}

// â”€â”€ Assessor Actions Panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function AssessorActions({ finding, override, onUpsert }) {
  const [rationale, setRationale] = useState('')
  const [riskRationale, setRiskRationale] = useState('')
  const [riskExpiry, setRiskExpiry] = useState('')
  const [satisfiedRationale, setSatisfiedRationale] = useState('')
  const [showSatisfiedModal, setShowSatisfiedModal] = useState(false)
  const [showRiskModal, setShowRiskModal] = useState(false)
  const [showNaModal, setShowNaModal] = useState(false)
  const [showInheritedModal, setShowInheritedModal] = useState(false)

  const displayStatus = effectiveStatus(finding.status, override)
  const isNa = displayStatus === 'not_applicable'
  const isNonCompliant = ['non_compliant', 'partially_compliant'].includes(displayStatus)

  return (
    <div className="mt-4 border border-indigo-100 rounded-xl bg-indigo-50/30">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-indigo-100">
        <Shield size={13} className="text-indigo-400" />
        <p className="text-xs font-semibold text-indigo-600 uppercase tracking-wide">Assessor Actions</p>
      </div>
      <div className="px-4 py-3 space-y-4">

        {/* â”€â”€ Applicability Section â”€â”€ */}
        <div>
          <p className="text-xs font-semibold text-gray-500 mb-2">APPLICABILITY</p>
          {override?.applicability === 'not_applicable' ? (
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs text-gray-600">Not Applicable (Assessor Override)</span>
                {override.applicability_rationale && (
                  <p className="text-xs text-gray-400 mt-0.5">{override.applicability_rationale}</p>
                )}
                {override.applicability_set_by && (
                  <p className="text-xs text-gray-400">Set by {override.applicability_set_by} on {fmtDate(override.applicability_set_at)}</p>
                )}
              </div>
              <button
                onClick={() => onUpsert({ applicability: 'applicable', applicability_rationale: null })}
                className="text-xs text-blue-600 hover:text-blue-800 border border-blue-200 px-2 py-1 rounded ml-4 flex-shrink-0"
              >Mark as Applicable</button>
            </div>
          ) : override?.applicability === 'inherited' ? (
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs text-gray-600">Inherited from Provider</span>
                {override.applicability_rationale && (
                  <p className="text-xs text-gray-400 mt-0.5">{override.applicability_rationale}</p>
                )}
                {override.applicability_set_by && (
                  <p className="text-xs text-gray-400">Set by {override.applicability_set_by} on {fmtDate(override.applicability_set_at)}</p>
                )}
              </div>
              <div className="flex gap-1 ml-4 flex-shrink-0">
                <button
                  onClick={() => onUpsert({ applicability: 'applicable', applicability_rationale: null })}
                  className="text-xs text-blue-600 hover:text-blue-800 border border-blue-200 px-2 py-1 rounded"
                >Mark Applicable</button>
                <button
                  onClick={() => setShowNaModal(true)}
                  className="text-xs text-gray-600 hover:text-gray-800 border border-gray-200 px-2 py-1 rounded"
                >Mark N/A</button>
              </div>
            </div>
          ) : isNa && !override?.applicability ? (
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500 italic">Auto-determined Not Applicable</span>
              <button
                onClick={() => onUpsert({ applicability: 'applicable', applicability_rationale: 'Assessor override: control is applicable' })}
                className="text-xs text-blue-600 hover:text-blue-800 border border-blue-200 px-2 py-1 rounded ml-4 flex-shrink-0"
              >Mark as Applicable (Override)</button>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500">Currently assessed as applicable</span>
              <div className="flex gap-1 ml-4 flex-shrink-0">
                <button
                  onClick={() => setShowNaModal(true)}
                  className="text-xs text-gray-600 hover:text-gray-800 border border-gray-200 px-2 py-1 rounded"
                >Mark as Not Applicable</button>
                <button
                  onClick={() => setShowInheritedModal(true)}
                  className="text-xs text-blue-600 hover:text-blue-800 border border-blue-200 px-2 py-1 rounded"
                >Mark as Inherited</button>
              </div>
            </div>
          )}
        </div>

        {/* â”€â”€ N/A Rationale Modal â”€â”€ */}
        {showNaModal && (
          <div className="border border-gray-200 rounded-lg p-3 bg-white">
            <p className="text-xs font-semibold text-gray-600 mb-1.5">Rationale for Not Applicable</p>
            <ExpandingTextarea
              value={rationale}
              onChange={e => setRationale(e.target.value)}
              rows={2}
              placeholder="Why is this control not applicable?"
              className="w-full text-xs"
              aiSection="applicability_rationale"
              aiPayload={{ control_id: finding.control_id, control_title: finding.control_title, current_status: finding.status }}
            />
            <div className="flex items-center gap-2 mt-2">
              <button
                onClick={() => { onUpsert({ applicability: 'not_applicable', applicability_rationale: rationale || null }); setShowNaModal(false); setRationale('') }}
                className="text-xs bg-gray-700 text-white px-3 py-1 rounded hover:bg-gray-800"
              >Confirm N/A</button>
              <button onClick={() => { setShowNaModal(false); setRationale('') }} className="text-xs text-gray-500 hover:text-gray-700 border px-3 py-1 rounded">Cancel</button>
              <AiGenerateButton section="applicability_rationale" payload={{ control_id: finding.control_id, control_title: finding.control_title, current_status: finding.status }} onGenerated={setRationale} />
            </div>
          </div>
        )}

        {/* â”€â”€ Inherited Modal â”€â”€ */}
        {showInheritedModal && (
          <div className="border border-gray-200 rounded-lg p-3 bg-white">
            <p className="text-xs font-semibold text-gray-600 mb-1.5">Provider / Platform that owns this control</p>
            <ExpandingTextarea
              value={rationale}
              onChange={e => setRationale(e.target.value)}
              rows={2}
              placeholder="e.g. AWS handles physical security (PE controls)"
              className="w-full text-xs"
              aiSection="applicability_rationale"
              aiPayload={{ control_id: finding.control_id, control_title: finding.control_title, current_status: 'inherited' }}
            />
            <div className="flex items-center gap-2 mt-2">
              <button
                onClick={() => { onUpsert({ applicability: 'inherited', applicability_rationale: rationale || null }); setShowInheritedModal(false); setRationale('') }}
                className="text-xs bg-blue-700 text-white px-3 py-1 rounded hover:bg-blue-800"
              >Confirm Inherited</button>
              <button onClick={() => { setShowInheritedModal(false); setRationale('') }} className="text-xs text-gray-500 hover:text-gray-700 border px-3 py-1 rounded">Cancel</button>
              <AiGenerateButton section="applicability_rationale" payload={{ control_id: finding.control_id, control_title: finding.control_title, current_status: 'inherited' }} onGenerated={setRationale} />
            </div>
          </div>
        )}

        {/* â”€â”€ Satisfied Section â”€â”€ */}
        <div>
          <p className="text-xs font-semibold text-gray-500 mb-2">SATISFIED</p>
          {override?.satisfied ? (
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs text-green-700 font-medium">Marked as Satisfied - future runs will carry this finding forward</span>
                {override.satisfied_rationale && (
                  <p className="text-xs text-gray-400 mt-0.5">{override.satisfied_rationale}</p>
                )}
                {override.satisfied_set_by && (
                  <p className="text-xs text-gray-400">Set by {override.satisfied_set_by} on {fmtDate(override.satisfied_set_at)}</p>
                )}
              </div>
              <button
                onClick={() => onUpsert({ satisfied: false, satisfied_rationale: null })}
                className="text-xs text-red-600 hover:text-red-800 border border-red-200 px-2 py-1 rounded ml-4 flex-shrink-0"
              >Remove Satisfied</button>
            </div>
          ) : finding.status === 'compliant' ? (
            <div>
              <button
                onClick={() => setShowSatisfiedModal(true)}
                className="text-xs text-green-700 hover:text-green-900 border border-green-200 bg-green-50 px-3 py-1.5 rounded"
              >Mark as Satisfied (carry forward on next run)</button>
              {showSatisfiedModal && (
                <div className="mt-2 border border-gray-200 rounded-lg p-3 bg-white">
                  <p className="text-xs font-semibold text-gray-600 mb-1.5">Rationale (optional)</p>
                  <ExpandingTextarea
                    value={satisfiedRationale}
                    onChange={e => setSatisfiedRationale(e.target.value)}
                    rows={2}
                    placeholder="Why is this control considered permanently satisfied?"
                    className="w-full text-xs"
                    aiSection="satisfied_rationale"
                    aiPayload={{ control_id: finding.control_id, control_title: finding.control_title, current_status: finding.status, implementation_statement: finding.implementation_statement }}
                  />
                  <div className="flex items-center gap-2 mt-2">
                    <button
                      onClick={() => { onUpsert({ satisfied: true, satisfied_rationale: satisfiedRationale || null }); setShowSatisfiedModal(false); setSatisfiedRationale('') }}
                      className="text-xs bg-green-700 text-white px-3 py-1 rounded hover:bg-green-800"
                    >Confirm Satisfied</button>
                    <button onClick={() => { setShowSatisfiedModal(false); setSatisfiedRationale('') }} className="text-xs text-gray-500 hover:text-gray-700 border px-3 py-1 rounded">Cancel</button>
                    <AiGenerateButton section="satisfied_rationale" payload={{ control_id: finding.control_id, control_title: finding.control_title, current_status: finding.status, implementation_statement: finding.implementation_statement }} onGenerated={setSatisfiedRationale} />
                  </div>
                </div>
              )}
            </div>
          ) : (
            <span className="text-xs text-gray-400 italic">Only compliant controls can be marked satisfied</span>
          )}
        </div>

        {/* â”€â”€ Manual Status Override â”€â”€ */}
        <ManualStatusOverride finding={finding} override={override} onUpsert={onUpsert} />

        {/* â”€â”€ Accepted Risk Section â”€â”€ */}
        {isNonCompliant && (
          <div>
            <p className="text-xs font-semibold text-gray-500 mb-2">ACCEPTED RISK</p>
            {override?.risk_accepted ? (
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs text-orange-700 font-medium">Risk Accepted</span>
                  {override.risk_acceptance_rationale && (
                    <p className="text-xs text-gray-600 mt-0.5">{override.risk_acceptance_rationale}</p>
                  )}
                  {override.risk_accepted_by && (
                    <p className="text-xs text-gray-400">Accepted by {override.risk_accepted_by} on {fmtDate(override.risk_accepted_at)}</p>
                  )}
                  {override.risk_acceptance_expiry && (
                    <p className="text-xs text-orange-500">Expires {fmtDate(override.risk_acceptance_expiry)}</p>
                  )}
                </div>
                <button
                  onClick={() => onUpsert({ risk_accepted: false, risk_acceptance_rationale: null, risk_acceptance_expiry: null })}
                  className="text-xs text-red-600 hover:text-red-800 border border-red-200 px-2 py-1 rounded ml-4 flex-shrink-0"
                >Revoke Acceptance</button>
              </div>
            ) : (
              <div>
                <button
                  onClick={() => setShowRiskModal(true)}
                  className="text-xs text-orange-700 hover:text-orange-900 border border-orange-200 bg-orange-50 px-3 py-1.5 rounded"
                >Accept Risk</button>
                {showRiskModal && (
                  <div className="mt-2 border border-gray-200 rounded-lg p-3 bg-white">
                    <p className="text-xs font-semibold text-gray-600 mb-1.5">Risk Acceptance Rationale</p>
                    <ExpandingTextarea
                      value={riskRationale}
                      onChange={e => setRiskRationale(e.target.value)}
                      rows={3}
                      placeholder="Document the business justification for accepting this risk..."
                      className="w-full text-xs"
                      aiSection="risk_rationale"
                      aiPayload={{ control_id: finding.control_id, control_title: finding.control_title, current_status: finding.status, gaps: finding.gaps }}
                    />
                    <div className="mt-2">
                      <p className="text-xs font-semibold text-gray-600 mb-1">Expiry Date (optional)</p>
                      <input
                        type="date"
                        value={riskExpiry}
                        onChange={e => setRiskExpiry(e.target.value)}
                        className="text-xs border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-300"
                      />
                    </div>
                    <div className="flex gap-2 mt-2">
                      <button
                        onClick={() => {
                          onUpsert({
                            risk_accepted: true,
                            risk_acceptance_rationale: riskRationale || null,
                            risk_acceptance_expiry: riskExpiry ? new Date(riskExpiry).toISOString() : null,
                          })
                          setShowRiskModal(false)
                          setRiskRationale('')
                          setRiskExpiry('')
                        }}
                        className="text-xs bg-orange-700 text-white px-3 py-1 rounded hover:bg-orange-800"
                      >Confirm Risk Acceptance</button>
                      <button onClick={() => { setShowRiskModal(false); setRiskRationale(''); setRiskExpiry('') }} className="text-xs text-gray-500 hover:text-gray-700 border px-3 py-1 rounded">Cancel</button>
                      <AiGenerateButton section="risk_rationale" payload={{ control_id: finding.control_id, control_title: finding.control_title, current_status: finding.status, gaps: finding.gaps }} onGenerated={setRiskRationale} />
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// â”€â”€ Inline notes editor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function NotesEditor({ findingId, initialNotes, projectId, assessmentId, onSaved }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(initialNotes || '')

  const save = async () => {
    try {
      await api.patch(
        `/projects/${projectId}/assessments/${assessmentId}/findings/${findingId}/notes`,
        { notes: text.trim() || null }
      )
      onSaved()
      setEditing(false)
    } catch (e) {
      alert('Save failed: ' + (e.response?.data?.detail || e.message))
    }
  }

  if (editing) {
    return (
      <div className="space-y-1.5">
        <ExpandingTextarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          placeholder="Add analyst notes for this control..."
          className="w-full text-sm"
          aiSection="control_notes"
          aiPayload={{ finding_id: findingId }}
        />
        <div className="flex items-center gap-2">
          <button onClick={save} className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700">Save</button>
          <button onClick={() => { setEditing(false); setText(initialNotes || '') }}
            className="text-xs text-gray-500 hover:text-gray-700 px-3 py-1 rounded border">Cancel</button>
          <AiGenerateButton
            section="control_notes"
            payload={{ finding_id: findingId }}
            onGenerated={setText}
          />
        </div>
      </div>
    )
  }

  return (
    <button onClick={() => setEditing(true)}
      className="flex items-start gap-2 w-full text-left group mt-2">
      <StickyNote size={13} className="text-gray-400 group-hover:text-blue-400 mt-0.5 flex-shrink-0 transition-colors" />
      {text ? (
        <span className="text-xs text-gray-700 whitespace-pre-wrap">{text}</span>
      ) : (
        <span className="text-xs text-gray-400 italic group-hover:text-gray-600 transition-colors">Add analyst notes...</span>
      )}
    </button>
  )
}

function ControlHistory({ projectId, controlId }) {
  const { data: history = [], isLoading } = useQuery({
    queryKey: ['control-history', projectId, controlId],
    queryFn: () => api.get(`/projects/${projectId}/activity-log`, {
      params: { control_id: controlId, limit: 50 }
    }).then(r => r.data),
  })

  const actionIcons = {
    llm_assessed: 'AI',
    carried_forward: '<-',
    override_not_applicable: 'NA',
    override_applicable: 'OK',
    override_inherited: 'INH',
    override_cleared: 'CLR',
    marked_satisfied: 'OK',
    satisfied_removed: 'RM',
    risk_accepted: '!',
    risk_acceptance_removed: 'CLR',
    notes_updated: 'NOTE',
    manual_resolved: 'EDIT',
    reviewer_accepted: 'OK',
    reviewer_override: 'EDIT',
    reviewer_revision: 'REV',
    retry_queued: 'RETRY',
    manual_status_set: 'EDIT',
    manual_status_cleared: 'CLR',
  }

  const actionColors = {
    llm_assessed: 'text-blue-700 bg-blue-50 border-blue-200',
    carried_forward: 'text-gray-600 bg-gray-50 border-gray-200',
    override_not_applicable: 'text-orange-700 bg-orange-50 border-orange-200',
    override_applicable: 'text-green-700 bg-green-50 border-green-200',
    override_inherited: 'text-indigo-700 bg-indigo-50 border-indigo-200',
    override_cleared: 'text-gray-600 bg-gray-50 border-gray-200',
    marked_satisfied: 'text-green-700 bg-green-50 border-green-200',
    satisfied_removed: 'text-gray-600 bg-gray-50 border-gray-200',
    risk_accepted: 'text-amber-700 bg-amber-50 border-amber-200',
    risk_acceptance_removed: 'text-gray-600 bg-gray-50 border-gray-200',
    notes_updated: 'text-purple-700 bg-purple-50 border-purple-200',
    manual_resolved: 'text-blue-700 bg-blue-50 border-blue-200',
    reviewer_accepted: 'text-green-700 bg-green-50 border-green-200',
    reviewer_override: 'text-blue-700 bg-blue-50 border-blue-200',
    reviewer_revision: 'text-amber-700 bg-amber-50 border-amber-200',
    retry_queued: 'text-gray-600 bg-gray-50 border-gray-200',
    manual_status_set: 'text-purple-700 bg-purple-50 border-purple-200',
    manual_status_cleared: 'text-gray-600 bg-gray-50 border-gray-200',
  }

  const [open, setOpen] = useState(false)

  if (isLoading) return <div className="text-xs text-gray-400 py-2">Loading history...</div>
  if (history.length === 0) return <div className="text-xs text-gray-400 py-2 italic">No activity recorded for this control.</div>

  return (
    <div className="mt-4 border-t border-gray-100 pt-4">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 w-full text-left group"
      >
        <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Control Activity Log</h4>
        <span className="text-xs text-gray-400 group-hover:text-gray-600">({history.length})</span>
        <ChevronDown size={13} className={`text-gray-400 ml-auto transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="space-y-2 mt-3">
          {history.map(entry => (
            <div key={entry.id} className={`flex gap-3 p-2 rounded-lg border text-xs ${actionColors[entry.action_type] || 'text-gray-600 bg-gray-50 border-gray-200'}`}>
              <span className="text-base leading-none mt-0.5 shrink-0">{actionIcons[entry.action_type] || '*'}</span>
              <div className="min-w-0 flex-1">
                <p className="font-medium leading-snug">{entry.action_summary}</p>
                <p className="text-xs opacity-70 mt-0.5">
                  {entry.performed_by === 'system' ? 'System' : entry.performed_by}
                  {' - '}
                  {new Date(entry.performed_at).toLocaleString('en-US', {
                    month: 'short', day: 'numeric', year: 'numeric',
                    hour: 'numeric', minute: '2-digit', hour12: true
                  })}
                  {entry.assessment_id && ` - Assessment #${entry.assessment_id}`}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// â”€â”€ Shared finding detail sub-components â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

/**
 * Normalize text that may contain:
 *   - literal backslash-n sequences (\n stored as two chars)
 *   - real newlines
 *   - inline numbered steps without newlines ("1. ... 2. ...")
 * Returns an array of clean step strings, or a single-element array.
 */
function parseSteps(raw) {
  if (!raw) return []
  // Replace literal \n (two-char sequence) with real newlines
  const text = raw.replace(/\\n/g, '\n')
  // Try splitting on real newlines first
  let lines = text.split('\n').map(s => s.trim()).filter(s => s.length > 2)
  // If we only got one chunk, try splitting inline numbered steps: "1. ... 2. ..."
  if (lines.length <= 1) {
    lines = text.split(/(?=\s*\d+\.\s)/).map(s => s.trim()).filter(Boolean)
  }
  // Strip leading numbering from each line
  return lines.map(s => s.replace(/^\s*\d+[.)]\s*/, '').trim()).filter(s => s.length > 2)
}

function RemediationPlan({ text }) {
  if (!text) return null
  const steps = parseSteps(text)
  return (
    <div className="mb-4">
      <p className="text-xs font-semibold text-orange-500 mb-2 uppercase tracking-wide">Remediation Plan</p>
      {steps.length > 1 ? (
        <ol className="space-y-2">
          {steps.map((step, i) => (
            <li key={i} className="flex gap-3 text-sm text-gray-700">
              <span className="flex-shrink-0 w-5 h-5 rounded-full bg-orange-100 text-orange-600 text-xs font-bold flex items-center justify-center mt-0.5">{i + 1}</span>
              <span className="flex-1 leading-relaxed">{step}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{text.replace(/\\n/g, '\n')}</p>
      )}
    </div>
  )
}

/** Render any LLM-generated text block: normalize \n and preserve whitespace */
function TextBlock({ text, className = 'text-sm text-gray-700' }) {
  if (!text) return null
  const normalized = text.replace(/\\n/g, '\n')
  return <p className={`${className} leading-relaxed whitespace-pre-wrap`}>{normalized}</p>
}

function normalizeIdentifier(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '')
}

const GENERIC_GUIDANCE_FACTS = [
  'State the current implemented behavior',
  'Name the responsible role and the operational record or repository that proves the implementation.',
  'State how the control is verified, by whom, and on what cadence.',
  'Tie the implementation to a concrete evidence record such as a ticket, log, report, matrix, or approval entry.',
]

const GENERIC_EVIDENCE_EXAMPLES = [
  'Verification record or approval entry',
  'Operational ticket, change record, or retained control evidence package',
]

function filterDisplayedRequiredFacts(facts = []) {
  const normalizedFacts = facts.map((fact) => String(fact))
  const specificFacts = normalizedFacts.filter(
    (fact) => !GENERIC_GUIDANCE_FACTS.some((generic) => fact.startsWith(generic))
  )
  return specificFacts.length > 0 ? specificFacts : normalizedFacts
}

function filterDisplayedEvidenceExamples(examples = []) {
  const normalizedExamples = examples.map((example) => String(example))
  const specificExamples = normalizedExamples.filter(
    (example) => !GENERIC_EVIDENCE_EXAMPLES.includes(example)
  )
  return specificExamples.length > 0 ? specificExamples : normalizedExamples
}

function EvidenceCitations({ citations, docMap, projectId, assessmentId, controlId, controlTitle }) {
  const [openEvidence, setOpenEvidence] = useState(null)
  const upperId = controlId?.toUpperCase?.() || controlId
  const { data: triage = [] } = useQuery({
    queryKey: ['control-triage', assessmentId, upperId],
    queryFn: async () => {
      const res = await api.get(`/projects/${projectId}/assessments/${assessmentId}/controls/${upperId}/triage`)
      return res.data
    },
    enabled: !!projectId && !!assessmentId && !!upperId && !!citations?.length,
    retry: false,
  })
  const distinctTriage = useMemo(
    () => distinctEvidenceItems(triage),
    [triage]
  )
  if (!citations?.length) return null
  return (
    <div className="mb-3">
      <p className="text-xs font-semibold text-blue-500 mb-2 uppercase tracking-wide">Evidence</p>
      <div className="space-y-2">
        {citations.map((e, i) => {
          if (typeof e === 'string') {
            return (
              <div key={i} className="flex gap-2 items-start text-xs text-gray-600 bg-blue-50 border border-blue-100 rounded-lg px-3 py-2">
                <span className="text-blue-300 flex-shrink-0 mt-0.5">*</span>
                <span>{e}</span>
              </div>
            )
          }
          const source = e?.source || e?.document || ''
          const citationText = cleanEvidenceExcerpt(e?.quote)
          const explicitExcerpt = cleanEvidenceExcerpt(e?.excerpt)
          const rel    = e?.relevance || e?.relevance_note || ''
          // Strip all legacy "Document N" variants stored by older assessments:
          //   prefix:  "Document 1: filename.pdf"
          //   suffix:  "filename.pdf (Document 1)"
          //   bare:    "Document 1"  (no filename - unresolvable, stays as-is)
          const cleanSource = source
            .replace(/^(?:Document|Excerpt)\s+\d+[:\s]+/i, '')   // strip prefix "Document N: "
            .replace(/\s*\((?:Document|Excerpt)\s+\d+\)\s*$/i, '') // strip suffix " (Document N)"
            .trim()
          // Try exact match first, then cleaned match
            const matchedUnit = findCitationEvidenceUnit(e, distinctTriage, docMap)
            const matchedDocRef = resolveEvidenceDocument(matchedUnit, docMap)
            const docRef = (docMap ? (docMap[source] ?? docMap[cleanSource]) : null) ?? matchedDocRef
            const displayTitle = evidenceTitle(cleanSource || source || `Evidence for ${controlId}`)
            const quoteAsExcerpt = citationText && !looksLikeAssessmentNarrative(citationText)
            const sourceExcerpt = cleanEvidenceExcerpt(matchedUnit?.excerpt) || explicitExcerpt || (quoteAsExcerpt ? citationText : '')
            const interpretation = cleanEvidenceNote(
              e?.rationale
              || (!quoteAsExcerpt ? citationText : '')
              || matchedUnit?.rationale
              || ''
            )
            const objectiveLabel = citationObjectiveLabel(e, rel)
            return (
              <div key={i} className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs space-y-2">
                {source && (
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                    {docRef?.download_url
                      ? <button onClick={() => downloadByUrl(docRef.download_url, cleanSource)}
                           className="font-semibold text-sm text-blue-700 hover:text-blue-900 hover:underline text-left leading-snug"
                           title={`Download ${cleanSource}`}>
                          {displayTitle}
                      </button>
                      : <p className="font-semibold text-sm text-blue-700 leading-snug" title={cleanSource}>{displayTitle}</p>
                    }
                    {objectiveLabel && <p className="mt-1 text-xs text-gray-500">{objectiveLabel}</p>}
                    </div>
                    <button
                      type="button"
                      onClick={() => openCyberAssistant({
                        mode: 'control',
                        title: `${controlId} Evidence Assistant`,
                        projectId: Number(projectId),
                        assessmentId: Number(assessmentId),
                        initialPrompt: buildEvidenceAssistantPrompt({
                          controlId,
                          citationLabel: cleanSource || source || `Evidence for ${controlId}`,
                          triageRole: null,
                          excerpt: sourceExcerpt || interpretation || rel || '',
                        }),
                        hiddenInitialMessage: true,
                        attachments: [
                          {
                            type: 'control',
                            resource_id: String(controlId),
                            context_json: {
                              control_id: controlId,
                              label: `Control: ${controlId}`,
                              control_title: controlTitle,
                              assessment_id: Number(assessmentId),
                            },
                          },
                          {
                            type: 'evidence',
                            resource_id: String(docRef?.id || `${controlId}-${i}`),
                            context_json: {
                              label: cleanSource ? `Evidence: ${cleanSource}` : `Evidence for ${controlId}`,
                              source_label: cleanSource || source || `Evidence for ${controlId}`,
                              excerpt: sourceExcerpt || interpretation || rel || '',
                              download_url: docRef?.download_url || null,
                            },
                          },
                        ],
                      })}
                      className="inline-flex items-center gap-1 rounded-md border border-violet-200 bg-violet-50 px-2 py-1 text-[11px] font-medium text-violet-700 hover:bg-violet-100 transition-colors flex-shrink-0"
                      title="Ask AI about this evidence"
                    >
                      <MessageSquare size={11} />
                      Ask AI
                    </button>
                  </div>
                )}
              {sourceExcerpt ? (
                <div className="border-l-2 border-blue-300 pl-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-700 mb-1">Source Excerpt</p>
                  <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{sourceExcerpt}</p>
                </div>
              ) : (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                  <p className="text-xs font-semibold text-amber-800">Source excerpt not captured</p>
                  <p className="text-xs text-amber-700 mt-0.5">This citation has assessment context, but no stored source excerpt to quote directly.</p>
                </div>
              )}
              {interpretation && (
                <details className="rounded-md border border-blue-100 bg-white/70 px-3 py-2">
                  <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                    Assessment Interpretation
                  </summary>
                  <p className="text-xs text-gray-700 leading-relaxed mt-2 whitespace-pre-wrap">{interpretation}</p>
                </details>
              )}
              <div className="flex flex-wrap gap-2 pt-1">
                {(sourceExcerpt || interpretation) && (
                  <button
                    type="button"
                    onClick={() => setOpenEvidence({ title: displayTitle, sourceExcerpt, interpretation, rel: objectiveLabel, docRef })}
                    className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <Maximize2 size={11} />
                    Open source
                  </button>
                )}
                {docRef?.download_url && (
                  <button
                    type="button"
                    onClick={() => downloadByUrl(docRef.download_url, cleanSource)}
                    className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-white px-2 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-50"
                  >
                    <Download size={11} />
                    Open document
                  </button>
                )}
              </div>
              {!source && !sourceExcerpt && !interpretation && !rel && <p className="text-gray-600">{JSON.stringify(e)}</p>}
            </div>
          )
        })}
      </div>
      {openEvidence && (
        <div
          className="fixed inset-0 z-[10000] bg-black/50 flex items-center justify-center p-4"
          onClick={() => setOpenEvidence(null)}
        >
          <div
            className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[86vh] flex flex-col"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-gray-100">
              <div>
                <p className="text-xs font-semibold text-gray-500 mb-1">Source Citation</p>
                <h3 className="text-base font-bold text-gray-900">{openEvidence.title}</h3>
                {openEvidence.rel && <p className="text-xs text-gray-500 mt-1">{openEvidence.rel}</p>}
              </div>
              <button
                type="button"
                onClick={() => setOpenEvidence(null)}
                className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                title="Close evidence"
              >
                <X size={18} />
              </button>
            </div>
            <div className="overflow-y-auto px-5 py-4">
              <div className="space-y-4">
                {openEvidence.sourceExcerpt ? (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-blue-700 mb-2">Source Excerpt</p>
                    <p className="text-sm text-gray-900 leading-relaxed whitespace-pre-wrap">{openEvidence.sourceExcerpt}</p>
                  </div>
                ) : (
                  <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                    <p className="text-xs font-semibold text-amber-800">Source excerpt not captured</p>
                    <p className="text-xs text-amber-700 mt-0.5">This citation has assessment context, but no stored source excerpt to quote directly.</p>
                  </div>
                )}
                {openEvidence.interpretation && (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Assessment Interpretation</p>
                    <p className="text-sm text-gray-900 leading-relaxed whitespace-pre-wrap">{openEvidence.interpretation}</p>
                  </div>
                )}
              </div>
            </div>
            <div className="flex justify-between gap-3 px-5 py-3 border-t border-gray-100">
              <div>
                {openEvidence.docRef?.download_url && (
                  <button
                    type="button"
                    onClick={() => downloadByUrl(openEvidence.docRef.download_url, openEvidence.docRef.filename || openEvidence.title)}
                    className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100"
                  >
                    <Download size={14} />
                    Open document
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={() => setOpenEvidence(null)}
                className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function RollupBadge({ readiness }) {
  const cfg = {
    ready_for_review: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    ready_with_risk: 'bg-amber-100 text-amber-700 border-amber-200',
    significant_risk: 'bg-red-100 text-red-700 border-red-200',
    insufficient_evidence: 'bg-slate-100 text-slate-600 border-slate-200',
  }[readiness] || 'bg-slate-100 text-slate-600 border-slate-200'
  const label = {
    ready_for_review: 'Ready for Review',
    ready_with_risk: 'Ready with Risk',
    significant_risk: 'Significant Risk',
    insufficient_evidence: 'Insufficient Evidence',
  }[readiness] || readiness || 'Pending'
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${cfg}`}>{label}</span>
}

function AssessmentRollupCard({
  projectId,
  assessmentId,
  assessmentStatus,
  assessment,
  editingNotes,
  setEditingNotes,
  notesText,
  setNotesText,
  updateAssessmentNotes,
  pageCounts,
  findings,
  reviewAttentionCount,
  dissentCount,
  onOpenNeedsReview,
  onOpenDissents,
}) {
  const [showSourceHelp, setShowSourceHelp] = useState(false)
  const [showUnitsHelp, setShowUnitsHelp] = useState(false)
  const [showRiskHelp, setShowRiskHelp] = useState(false)
  const { data: rollup, isLoading } = useQuery({
    queryKey: ['assessment-rollup', assessmentId],
    queryFn: async () => {
      try {
        const res = await api.get(`/projects/${projectId}/assessments/${assessmentId}/rollup`)
        return res.data
      } catch (e) {
        if (e.response?.status === 404) return null
        throw e
      }
    },
    enabled: assessmentStatus === 'complete',
    retry: false,
  })

  if (assessmentStatus !== 'complete') return null
  if (isLoading) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl px-5 py-4 mb-4">
        <p className="text-sm text-gray-500">Loading ATO support rollup...</p>
      </div>
    )
  }
  if (!rollup) return null

  const counts = rollup.summary?.counts || {}
  const sourceMix = rollup.summary?.source_mix || {}
  const sourceDocuments = rollup.summary?.source_documents || {}
  const sourceControls = rollup.summary?.source_controls || {}
  const highRisk = rollup.summary?.high_risk_controls || []

  return (
    <div className="bg-white border border-gray-200 rounded-xl px-5 py-4 mb-4">
      <div className="mb-3">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Assessment Notes</p>
            {counts.synthesized_narratives > 0 && (
              <span
                className="inline-flex items-center rounded-full bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600 border border-slate-200"
                title={`${counts.synthesized_narratives} fallback narrative${counts.synthesized_narratives !== 1 ? 's were' : ' was'} auto-built from earlier analysis.`}
              >
                {counts.synthesized_narratives} fallback narrative{counts.synthesized_narratives === 1 ? '' : 's'}
              </span>
            )}
          </div>
          {editingNotes ? (
            <div className="space-y-2">
              <ExpandingTextarea
                value={notesText}
                onChange={(e) => setNotesText(e.target.value)}
                rows={3}
                placeholder="Add notes, observations, or context for this assessment run..."
                className="w-full text-sm"
                aiSection="assessment_notes"
                aiPayload={{
                  assessment_stats: {
                    compliant: pageCounts.compliant || 0,
                    partial: pageCounts.partially_compliant || 0,
                    non_compliant: pageCounts.non_compliant || 0,
                    na: pageCounts.not_applicable || 0,
                    total: pageCounts.total_controls || findings.length,
                  }
                }}
              />
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={updateAssessmentNotes}
                  className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700">Save</button>
                <button onClick={() => { setEditingNotes(false); setNotesText(assessment?.notes || '') }}
                  className="text-xs text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded border">Cancel</button>
                <AiGenerateButton
                  section="assessment_notes"
                  payload={{
                    assessment_stats: {
                      compliant: pageCounts.compliant || 0,
                      partial: pageCounts.partially_compliant || 0,
                      non_compliant: pageCounts.non_compliant || 0,
                      na: pageCounts.not_applicable || 0,
                      total: pageCounts.total_controls || findings.length,
                    }
                  }}
                  onGenerated={setNotesText}
                />
              </div>
            </div>
          ) : (
            <button
              onClick={() => { setEditingNotes(true); setNotesText(assessment?.notes || '') }}
              className="flex items-start gap-2 w-full text-left group"
            >
              <StickyNote size={14} className="text-gray-400 group-hover:text-blue-400 mt-0.5 flex-shrink-0 transition-colors" />
              {assessment?.notes ? (
                <span className="text-sm text-gray-800 whitespace-pre-wrap line-clamp-4">{assessment.notes}</span>
              ) : (
                <span className="text-sm text-gray-400 italic group-hover:text-gray-600 transition-colors">
                  Click to add notes about this assessment run...
                </span>
              )}
            </button>
          )}
        </div>

      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="rounded-lg border border-sky-100 bg-sky-50 px-3 py-3">
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="text-xs font-semibold text-sky-700 uppercase tracking-wide">Evidence Sources</p>
            <button
              type="button"
              onClick={() => setShowSourceHelp((current) => !current)}
              className="inline-flex items-center gap-1 text-[11px] text-sky-700 hover:text-sky-900"
              title="Explain how source coverage works"
            >
              <Info size={12} />
              Help
            </button>
          </div>
          {showSourceHelp && (
            <div className="mb-3 rounded-lg border border-sky-200 bg-white/80 px-3 py-2 text-xs text-sky-900 leading-relaxed">
              <p className="font-semibold mb-1">What this shows</p>
              <p>
                These counts show which source documents were actually used in this assessment and how many controls
                they supported.
              </p>
              <p className="mt-2">
                This is not a raw directory count. A project can contain more files than appear here if some documents
                did not contribute triaged evidence for this assessment.
              </p>
            </div>
          )}
          <div className="space-y-2 text-sm text-gray-700">
            {[
              ['Project', 'project'],
              ['Common Controls', 'common_control'],
              ['Enterprise Policies', 'policy'],
              ['Enterprise Procedures', 'procedure'],
            ].map(([label, key]) => (
              <div key={key} className="flex items-start justify-between gap-3">
                <span>{label}</span>
                <div className="text-right text-xs">
                  <div><span className="font-semibold">{sourceDocuments[key] || 0}</span> docs used</div>
                  <div className="text-sky-700"><span className="font-semibold">{sourceControls[key] || 0}</span> ctrls supported</div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-3">
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="text-xs font-semibold text-blue-700 uppercase tracking-wide">Evidence Units</p>
            <button
              type="button"
              onClick={() => setShowUnitsHelp((current) => !current)}
              className="inline-flex items-center gap-1 text-[11px] text-blue-700 hover:text-blue-900"
              title="Explain how evidence units work"
            >
              <Info size={12} />
              Help
            </button>
          </div>
          {showUnitsHelp && (
            <div className="mb-3 rounded-lg border border-blue-200 bg-white/80 px-3 py-2 text-xs text-blue-900 leading-relaxed">
              <p className="font-semibold mb-1">What this shows</p>
              <p>
                These counts are evidence units triaged into the assessment. An evidence unit is an expanded excerpt
                built from a triggering line plus surrounding context, so it is usually larger than a sentence fragment
                but smaller than a full document.
              </p>
              <p className="mt-2">
                A single document can produce many evidence units, and the same source can support many controls. These
                are the actual evidence objects classified, embedded, retrieved, and analyzed during the assessment.
              </p>
            </div>
          )}
          <div className="space-y-1 text-sm text-gray-700">
            <div className="flex justify-between gap-3"><span>Project</span><span className="font-semibold">{sourceMix.project || 0}</span></div>
            <div className="flex justify-between gap-3"><span>Common Controls</span><span className="font-semibold">{sourceMix.common_control || 0}</span></div>
            <div className="flex justify-between gap-3"><span>Enterprise Policies</span><span className="font-semibold">{sourceMix.policy || 0}</span></div>
            <div className="flex justify-between gap-3"><span>Enterprise Procedures</span><span className="font-semibold">{sourceMix.procedure || 0}</span></div>
          </div>
        </div>
        <div className="rounded-lg border border-red-100 bg-red-50 px-3 py-3">
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="text-xs font-semibold text-red-700 uppercase tracking-wide">Highest Risk Controls</p>
            <button
              type="button"
              onClick={() => setShowRiskHelp((current) => !current)}
              className="inline-flex items-center gap-1 text-[11px] text-red-700 hover:text-red-900"
              title="Explain how high risk controls are chosen"
            >
              <Info size={12} />
              Help
            </button>
          </div>
          {showRiskHelp && (
            <div className="mb-3 rounded-lg border border-red-200 bg-white/80 px-3 py-2 text-xs text-red-900 leading-relaxed">
              <p className="font-semibold mb-1">What this shows</p>
              <p>
                This is a prioritized short list from the current rollup, not every risky control. It favors
                non-compliant controls, larger gap counts, and controls that also have AI dissents.
              </p>
              <p className="mt-2">
                Use it as a quick triage view of where to look first, not as a complete inventory of every partial or
                review-needed control in the assessment.
              </p>
            </div>
          )}
          {highRisk.length === 0 ? (
            <p className="text-sm text-gray-600">No high-risk controls flagged in the current rollup.</p>
          ) : (
            <div className="space-y-1.5">
              {highRisk.slice(0, 4).map(item => (
                <div key={item.control_id} className="text-sm text-gray-700">
                  <span className="font-mono font-semibold text-red-700">{item.control_id}</span>{' '}
                  <span>{item.status.replace(/_/g, ' ')}</span>
                  {item.challenged && <span className="ml-1 text-violet-700 font-medium">- AI dissent</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ControlWorkbench({ projectId, assessmentId, controlId, docMap }) {
  const [tab, setTab] = useState('summary')
  const [expandedObjectiveId, setExpandedObjectiveId] = useState(null)
  const [allEvidenceModal, setAllEvidenceModal] = useState(null)
  const [evidenceModal, setEvidenceModal] = useState(null)
  const upperId = controlId?.toUpperCase?.() || controlId
  const base = `/projects/${projectId}/assessments/${assessmentId}/controls/${upperId}`
  const optionalGet = async (url, fallback) => {
    try {
      const res = await api.get(url)
      return res.data
    } catch (e) {
      if (e.response?.status === 404) return fallback
      throw e
    }
  }

  const { data: criteria } = useQuery({
    queryKey: ['control-criteria', assessmentId, upperId],
    queryFn: () => optionalGet(`${base}/criteria`, null),
    enabled: !!upperId,
    retry: false,
  })
  const { data: determination } = useQuery({
    queryKey: ['control-determination', assessmentId, upperId],
    queryFn: () => optionalGet(`${base}/determination`, null),
    enabled: !!upperId,
    retry: false,
  })
  const { data: objectives = [] } = useQuery({
    queryKey: ['control-objectives', assessmentId, upperId],
    queryFn: () => optionalGet(`${base}/objectives`, []),
    enabled: !!upperId,
    retry: false,
  })
  const { data: triage = [] } = useQuery({
    queryKey: ['control-triage', assessmentId, upperId],
    queryFn: () => optionalGet(`${base}/triage`, []),
    enabled: !!upperId,
    retry: false,
  })
  const { data: challenge } = useQuery({
    queryKey: ['control-challenge', assessmentId, upperId],
    queryFn: () => optionalGet(`${base}/challenge`, null),
    enabled: !!upperId,
    retry: false,
  })
  const { data: objectiveEvidence } = useQuery({
    queryKey: ['control-objective-evidence', assessmentId, upperId],
    queryFn: () => optionalGet(`${base}/objective-evidence`, { control_id: upperId, objective_reviews: [] }),
    enabled: !!upperId,
    retry: false,
  })

  const corroboration = determination?.objective_summary?.corroboration || null
  const policySummary = determination?.objective_summary || {}
  const totalityReview = policySummary?.totality_review || null
  const objectiveDetails = useMemo(() => {
    const rows = policySummary?.objective_details || []
    const map = {}
    rows.forEach((row) => {
      if (row?.objective_id) map[row.objective_id] = row
    })
    return map
  }, [policySummary])
  const objectiveEvidenceMap = useMemo(() => {
    const rows = objectiveEvidence?.objective_reviews || []
    const map = {}
    rows.forEach((row) => {
      if (row?.objective_id) map[row.objective_id] = row
    })
    return map
  }, [objectiveEvidence])
  const policyManualReviewReasons = policySummary?.manual_review_reasons || []
  const criticalFailures = policySummary?.critical_failures || []
  const criteriaLines = useMemo(
    () => formatCriteriaLines(criteria?.control_statement),
    [criteria?.control_statement]
  )
  const deficiencyLines = useMemo(
    () => {
      const objectiveFindings = (objectives || [])
        .filter((objective) => objective?.status && objective.status !== 'met')
        .map(formatObjectiveFinding)
        .filter(Boolean)
      if (objectiveFindings.length > 0) return objectiveFindings
      return splitSummaryLines(determination?.deficiency_summary)
        .map(formatStoredDeficiencyLine)
        .filter(Boolean)
    },
    [determination?.deficiency_summary, objectives]
  )
  const determinationSummaryText = useMemo(
    () => readableDeterminationSummary({ determination, policySummary, objectives, corroboration }),
    [determination, policySummary, objectives, corroboration]
  )
  const corroborationExamples = useMemo(
    () => (corroboration?.supporting_examples || []).map(item => item.filename).filter(Boolean),
    [corroboration]
  )
  const distinctTriage = useMemo(
    () => distinctEvidenceItems(triage),
    [triage]
  )
  const objectiveCounts = useMemo(() => {
    const counts = { total: objectives.length, met: 0, partial: 0, notMet: 0, other: 0 }
    ;(objectives || []).forEach((objective) => {
      if (objective.status === 'met') counts.met += 1
      else if (objective.status === 'partially_met') counts.partial += 1
      else if (objective.status === 'not_met') counts.notMet += 1
      else counts.other += 1
    })
    return counts
  }, [objectives])
  const sortedObjectives = useMemo(() => {
    const rank = (objective) => {
      const detail = objectiveDetails[objective.objective_id] || {}
      if (detail.critical && objective.status !== 'met') return 0
      if (objective.status === 'not_met') return 1
      if (objective.status === 'partially_met') return 2
      if ((detail.manual_flags || []).length > 0) return 3
      if (objective.status === 'met') return 5
      return 4
    }
    return [...(objectives || [])].sort((a, b) => rank(a) - rank(b) || String(a.objective_id).localeCompare(String(b.objective_id)))
  }, [objectives, objectiveDetails])
  const reviewPriorityObjectives = useMemo(
    () => sortedObjectives.filter((objective) => {
      const detail = objectiveDetails[objective.objective_id] || {}
      return objective.status !== 'met' || (detail.manual_flags || []).length > 0
    }),
    [sortedObjectives, objectiveDetails]
  )
  const evidenceWarnings = useMemo(() => {
    const warnings = []
    const supportingDocs = Number(corroboration?.supporting_documents || 0)
    const sourceTypes = corroboration?.source_types || []
    const artifactTypes = corroboration?.artifact_types || []
    if (distinctTriage.length > 0 && distinctTriage.some((item) => !cleanEvidenceExcerpt(item.excerpt))) {
      warnings.push('Some evidence rows have no captured source excerpt.')
    }
    if (supportingDocs === 1 && triage.length > 0) warnings.push('Evidence is concentrated in one supporting document.')
    if (supportingDocs > 1 && supportingDocs < 3 && triage.length >= 20) warnings.push(`Evidence volume is high, but it is spread across only ${supportingDocs} supporting documents.`)
    if (artifactTypes.length > 0 && !artifactTypes.some((type) => /validation|verification|record|configuration|technical/i.test(type))) {
      warnings.push('No technical validation or verification artifact type is represented.')
    }
    if (criticalFailures.length > 0) warnings.push(`${criticalFailures.length} critical objective failure${criticalFailures.length === 1 ? '' : 's'} remain.`)
    return warnings
  }, [corroboration, criticalFailures, distinctTriage, triage.length])

  if (!criteria && !determination && objectives.length === 0 && triage.length === 0 && !challenge) {
    return (
      <div className="border-t border-blue-100 pt-3 mt-3">
        <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Assessment Workbench</p>
          <p className="text-sm text-gray-600">
            This control does not have staged assessor data yet. Re-run the assessment to populate criteria,
            evidence triage, objective determinations, and challenge records for this workbench.
          </p>
        </div>
      </div>
    )
  }

  const tabBtn = (id, label) => (
    <button
      onClick={() => setTab(id)}
      className={`px-3 py-1.5 text-xs font-semibold rounded-full border transition-colors ${
        tab === id ? 'bg-indigo-700 text-white border-indigo-700' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
      }`}
    >
      {label}
    </button>
  )

  return (
    <div className="border-t border-blue-100 pt-3 mt-3">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Control Review</p>
          <p className="text-xs text-gray-500">Decision, blockers, objective checklist, source review, and traceability for this control.</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {tabBtn('summary', 'Summary')}
          {tabBtn('objectives', `Objectives (${objectives.length})`)}
          {tabBtn('evidence', `Evidence Map (${triage.length})`)}
          {tabBtn('traceability', 'Traceability')}
          {challenge?.dissent_note && tabBtn('challenge', 'AI Dissent')}
        </div>
      </div>

      {tab === 'summary' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-gray-200 bg-white px-4 py-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Decision Snapshot</p>
                <p className="text-base font-bold text-gray-900">{criteria?.control_title || upperId}</p>
                <p className="mt-2 text-sm text-gray-700 leading-relaxed">{determinationSummaryText}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                <StatusBadge status={determination?.status || 'not_reviewed'} />
                <span className="text-xs px-2 py-1 rounded-full bg-slate-100 text-slate-700">
                  {determination?.confidence_score != null ? `${(determination.confidence_score * 100).toFixed(0)}% confidence` : 'No confidence score'}
                </span>
                <span className="text-xs px-2 py-1 rounded-full bg-blue-50 text-blue-700">
                  {objectiveCounts.met}/{objectiveCounts.total} objectives met
                </span>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-2">
              <div className="rounded-md border border-emerald-100 bg-emerald-50 px-3 py-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">Met</p>
                <p className="text-lg font-bold text-emerald-800">{objectiveCounts.met}</p>
              </div>
              <div className="rounded-md border border-amber-100 bg-amber-50 px-3 py-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700">Partial</p>
                <p className="text-lg font-bold text-amber-800">{objectiveCounts.partial}</p>
              </div>
              <div className="rounded-md border border-red-100 bg-red-50 px-3 py-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-red-700">Not Met</p>
                <p className="text-lg font-bold text-red-800">{objectiveCounts.notMet}</p>
              </div>
              <div className="rounded-md border border-blue-100 bg-blue-50 px-3 py-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-700">Evidence</p>
                <p className="text-lg font-bold text-blue-800">{distinctTriage.length}</p>
              </div>
            </div>
          </div>

          {(deficiencyLines.length > 0 || evidenceWarnings.length > 0) && (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              {deficiencyLines.length > 0 && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-red-700 mb-2">Blocking Issues</p>
                  <div className="space-y-2">
                    {deficiencyLines.slice(0, 6).map((line, index) => (
                      <div key={`${upperId}-summary-deficiency-${index}`} className="flex gap-2 text-sm text-red-800 leading-relaxed">
                        <AlertTriangle size={13} className="text-red-400 flex-shrink-0 mt-0.5" />
                        <span>{line}</span>
                      </div>
                    ))}
                    {deficiencyLines.length > 6 && (
                      <p className="text-xs text-red-600">+{deficiencyLines.length - 6} more issue{deficiencyLines.length - 6 === 1 ? '' : 's'} in the objective checklist.</p>
                    )}
                  </div>
                </div>
              )}
              {evidenceWarnings.length > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-amber-700 mb-2">Evidence Quality Warnings</p>
                  <div className="space-y-2">
                    {evidenceWarnings.map((warning, index) => (
                      <div key={`${upperId}-evidence-warning-${index}`} className="flex gap-2 text-sm text-amber-800 leading-relaxed">
                        <Info size={13} className="text-amber-500 flex-shrink-0 mt-0.5" />
                        <span>{warning}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="rounded-lg border border-gray-200 bg-white px-4 py-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between mb-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-600">Review Queue</p>
                <p className="text-xs text-gray-500">Objectives needing attention are listed first. Met objectives stay available in the checklist.</p>
              </div>
              <button
                type="button"
                onClick={() => setTab('objectives')}
                className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
              >
                <LayoutList size={13} />
                Open Objective Checklist
              </button>
            </div>
            {reviewPriorityObjectives.length > 0 ? (
              <div className="space-y-2">
                {reviewPriorityObjectives.slice(0, 5).map((objective) => {
                  const detail = objectiveDetails[objective.objective_id] || {}
                  const reviews = objectiveEvidenceMap[objective.objective_id]?.reviews || []
                  return (
                    <button
                      key={`summary-${objective.objective_id}`}
                      type="button"
                      onClick={() => {
                        setExpandedObjectiveId(objective.objective_id)
                        setTab('objectives')
                      }}
                      className="w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-left hover:bg-blue-50 hover:border-blue-200 transition-colors"
                    >
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <p className="text-xs font-semibold text-gray-700">{objective.objective_id}</p>
                          <p className="text-sm text-gray-800 leading-relaxed mt-1">{objectiveBasisText(objective, detail, reviews, docMap)}</p>
                        </div>
                        <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full flex-shrink-0 ${
                          objective.status === 'met' ? 'bg-emerald-100 text-emerald-700' :
                          objective.status === 'partially_met' ? 'bg-amber-100 text-amber-700' :
                          'bg-red-100 text-red-700'
                        }`}>
                          {statusLabel(objective.status)}
                        </span>
                      </div>
                      {(detail.critical || (detail.manual_flags || []).length > 0) && (
                        <p className="mt-2 text-xs text-amber-700">
                          {[detail.critical ? 'critical objective' : null, ...(detail.manual_flags || []).map((flag) => flag.replace(/_/g, ' '))].filter(Boolean).join(', ')}
                        </p>
                      )}
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="rounded-md border border-emerald-100 bg-emerald-50 px-3 py-2">
                <p className="text-sm text-emerald-800">No blocking or partial objectives are currently flagged for this control.</p>
              </div>
            )}
          </div>
        </div>
      )}

        {tab === 'traceability' && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3">
            <p className="text-xs font-semibold text-indigo-700 mb-2 uppercase tracking-wide">Criteria Package</p>
            <p className="text-sm font-semibold text-gray-900 mb-1">{criteria?.control_title}</p>
            <p className="text-xs text-gray-600 mb-2">{(criteria?.assessment_objectives || []).length} objective(s)</p>
            {criteriaLines.length > 0 ? (
              <div className="space-y-2">
                <p className="text-sm text-gray-700 leading-relaxed">{criteriaLines[0]}</p>
                {criteriaLines.length > 1 && (
                  <div className="space-y-1.5 pl-1">
                    {criteriaLines.slice(1).map((line, index) => (
                      <div key={`${upperId}-criteria-${index}`} className="flex gap-2 text-sm text-gray-700 leading-relaxed">
                        <span className="text-indigo-400 flex-shrink-0 mt-0.5">•</span>
                        <span>{line}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{cleanCatalogText(criteria?.control_statement)}</p>
            )}
          </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-4 py-3">
              <p className="text-xs font-semibold text-emerald-700 mb-2 uppercase tracking-wide">Control Determination</p>
              <div className="flex items-center gap-2 mb-2">
                <StatusBadge status={determination?.status || 'not_reviewed'} />
                <span className="text-xs text-gray-500">
                  {determination?.confidence_score != null ? `${(determination.confidence_score * 100).toFixed(0)}% confidence` : 'No confidence score'}
                </span>
              </div>
              {!!policySummary?.policy_version && (
                <div className="mb-3 rounded-lg border border-indigo-200 bg-white/80 px-3 py-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-indigo-700 mb-2">Policy Adjudication</p>
                  <div className="flex flex-wrap gap-2 mb-2">
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700">
                      Policy v{policySummary.policy_version}
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
                      Support {(Number(policySummary.weighted_support_score || 0) * 100).toFixed(0)}%
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                      Evidence {(Number(policySummary.evidence_quality_index || 0) * 100).toFixed(0)}%
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">
                      Contradiction {(Number(policySummary.contradiction_index || 0) * 100).toFixed(0)}%
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-700">
                      {policySummary.total || 0} objectives
                    </span>
                  </div>
                  {(criticalFailures.length > 0 || policyManualReviewReasons.length > 0) && (
                    <div className="space-y-1">
                      {criticalFailures.length > 0 && (
                        <p className="text-xs text-red-700">
                          Critical failures: {criticalFailures.join(', ')}
                        </p>
                      )}
                      {policyManualReviewReasons.length > 0 && (
                        <p className="text-xs text-amber-700">
                          Manual review triggers: {policyManualReviewReasons.map((reason) => reason.replace(/_/g, ' ')).join(', ')}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}
              <p className="text-sm text-gray-700 leading-relaxed mb-2">{determinationSummaryText}</p>
              {totalityReview && (
                <div className="mb-3 rounded-lg border border-violet-200 bg-white/80 px-3 py-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-violet-700 mb-2">Objective Totality Review</p>
                  <div className="flex flex-wrap gap-2">
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">
                      {totalityReview.objective_count || 0} objective maps
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700">
                      {totalityReview.total_considered_packet_assignments || 0} evidence links reviewed
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                      {totalityReview.total_prompt_packet_assignments || 0} cited evidence links
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-700">
                      {(policySummary.review_mode || 'legacy').replace(/_/g, ' ')}
                    </span>
                  </div>
                </div>
              )}
              {corroboration && (
                <div className="mb-3 rounded-lg border border-emerald-200 bg-white/80 px-3 py-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700 mb-2">Corroboration</p>
                  <div className="flex flex-wrap gap-2 mb-2">
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
                      {corroboration.supporting_documents || 0} document{(corroboration.supporting_documents || 0) === 1 ? '' : 's'}
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                      {(corroboration.source_types || []).length} source type{(corroboration.source_types || []).length === 1 ? '' : 's'}
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">
                      {(corroboration.artifact_types || []).length} artifact type{(corroboration.artifact_types || []).length === 1 ? '' : 's'}
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">
                      {(corroboration.corroboration_strength || 'none').replace(/_/g, ' ')}
                    </span>
                  </div>
                  {corroborationExamples.length > 0 && (
                    <div>
                      <p className="text-xs text-gray-500 mb-1">Example sources</p>
                      <div className="flex flex-col gap-1.5">
                        {corroborationExamples.slice(0, 6).map((filename) => (
                          <span
                            key={filename}
                            className="block max-w-full rounded-md bg-white border border-emerald-100 px-2 py-1 text-[11px] text-gray-600 break-words leading-snug"
                            title={filename}
                          >
                            {evidenceTitle(filename)}
                          </span>
                        ))}
                        {corroborationExamples.length > 6 && (
                          <span className="text-[11px] px-2 py-0.5 rounded-full bg-white border border-gray-200 text-gray-500">
                            +{corroborationExamples.length - 6} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
              {deficiencyLines.length > 0 && (
                <div className="rounded-lg border border-red-200 bg-white/80 px-3 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-red-700 mb-2">Deficiency Summary</p>
                  <div className="space-y-1.5">
                    {deficiencyLines.map((line, index) => (
                      <div key={`${upperId}-deficiency-${index}`} className="flex gap-2 text-sm text-red-700 leading-relaxed">
                        <span className="text-red-300 flex-shrink-0 mt-0.5">•</span>
                        <span>{line}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
      )}

      {tab === 'objectives' && (
        <div className="space-y-3">
          <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-700 mb-1">Objective Checklist</p>
            <p className="text-sm text-gray-700">
              Objectives are sorted by review priority. Use Review Sources to inspect citations and source excerpts for a specific objective.
            </p>
          </div>
          {sortedObjectives.map(obj => {
            const detail = objectiveDetails[obj.objective_id] || {}
            const objectiveEvidenceEntry = objectiveEvidenceMap[obj.objective_id] || { reviews: [] }
            const reviews = objectiveEvidenceEntry.reviews || []
            const isExpanded = expandedObjectiveId === obj.objective_id
            const supportingReviews = reviews.filter((item) => item.review_role === 'supporting')
            const contradictoryReviews = reviews.filter((item) => item.review_role === 'contradictory')
            const partialReviews = reviews.filter((item) => item.review_role === 'partial')
            const contextReviews = reviews.filter((item) => item.review_role === 'context')
            const evidenceGroups = [
              ['supporting', supportingReviews],
              ['contradictory', contradictoryReviews],
              ['partial', partialReviews],
              ['context', contextReviews],
            ].filter(([role, items]) => items.length > 0 || (role === 'supporting' && reviews.length === 0))
            const previewEvidenceGroups = evidenceGroups.map(([role, items]) => [role, distinctEvidenceItems(items)])
            const consideredCount = objectiveEvidenceCount(detail, reviews)
            const promptCount = objectivePromptCount(detail, reviews)
            const statusTone =
              obj.status === 'met' ? 'emerald' :
              obj.status === 'partially_met' ? 'amber' :
              'red'
            const basisText = objectiveBasisText(obj, detail, reviews, docMap)
            return (
            <div key={obj.objective_id} className={`rounded-lg border bg-white px-4 py-4 ${
              obj.status === 'met' ? 'border-gray-200' :
              obj.status === 'partially_met' ? 'border-amber-200' :
              'border-red-200'
            }`}>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    <span className="text-xs font-semibold text-gray-500">{obj.objective_id}</span>
                    {!!detail.bucket_key && (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700">
                        {titleCaseLabel(detail.bucket_key)}
                      </span>
                    )}
                    {detail.critical && obj.status !== 'met' && (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-50 text-red-700">
                        Critical objective
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-900 leading-relaxed">{formatObjectiveDisplayText(obj.objective_text)}</p>
                </div>
                <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${
                  obj.status === 'met' ? 'bg-emerald-100 text-emerald-700' :
                  obj.status === 'partially_met' ? 'bg-amber-100 text-amber-700' :
                  'bg-red-100 text-red-700'
                }`}>
                  {statusLabel(obj.status)}
                </span>
              </div>

              {basisText && (
                <div className={`mt-3 rounded-lg border px-3 py-2 ${
                  statusTone === 'emerald' ? 'border-emerald-100 bg-emerald-50' :
                  statusTone === 'amber' ? 'border-amber-100 bg-amber-50' :
                  'border-red-100 bg-red-50'
                }`}>
                  <p className={`text-[11px] font-semibold uppercase tracking-wide mb-1 ${
                    statusTone === 'emerald' ? 'text-emerald-700' :
                    statusTone === 'amber' ? 'text-amber-700' :
                    'text-red-700'
                  }`}>
                    Assessment Basis
                  </p>
                  <p className="text-sm text-gray-800 leading-relaxed">{basisText}</p>
                </div>
              )}

              {!!detail.bucket_key && (obj.status !== 'met' || isExpanded || (detail.manual_flags || []).length > 0) && (
                <div className="flex flex-wrap gap-2 mt-3">
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
                    Support {(Number(detail.effective_support || 0) * 100).toFixed(0)}%
                  </span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                    Evidence {(Number(detail.evidence_quality || 0) * 100).toFixed(0)}%
                  </span>
                  {detail.contradiction_ratio != null && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-orange-100 text-orange-700">
                      Contradiction {(Number(detail.contradiction_ratio) * 100).toFixed(0)}%
                    </span>
                  )}
                  {(detail.manual_flags || []).map((flag) => (
                    <span key={flag} className="text-[11px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">
                      {flag.replace(/_/g, ' ')}
                    </span>
                  ))}
                  {detail.bucket_modifier && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">
                      {detail.bucket_modifier}
                    </span>
                  )}
                </div>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setExpandedObjectiveId(isExpanded ? null : obj.objective_id)}
                  className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
                >
                  {isExpanded ? <ChevronUp size={13} /> : <Maximize2 size={13} />}
                  {isExpanded ? 'Hide Sources' : 'Review Sources'}
                </button>
                {reviews.length > 0 && (obj.status !== 'met' || contradictoryReviews.length > 0) && (
                  <span className="text-xs text-gray-500">
                    {(detail.objective_corroboration?.supporting_documents || 0) > 0
                      ? `${detail.objective_corroboration.supporting_documents} supporting document${detail.objective_corroboration.supporting_documents === 1 ? '' : 's'}`
                      : 'Supporting evidence mapped'}
                    {contradictoryReviews.length > 0 ? `, ${contradictoryReviews.length} contradictory item${contradictoryReviews.length === 1 ? '' : 's'}` : ', no contradictory evidence'}
                  </span>
                )}
              </div>

              {isExpanded && (
                <>
              {(detail.evidence_map_summary?.considered_packets || reviews.length > 0) && (
                <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-700 mb-2">Source Review</p>
                  <div className="flex flex-wrap gap-2">
                    {(detail.objective_corroboration?.supporting_documents || 0) > 0 && (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                        {detail.objective_corroboration.supporting_documents} supporting docs
                      </span>
                    )}
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700">
                      model-reviewed source excerpts
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
                      supporting evidence present
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-100 text-red-700">
                      {contradictoryReviews.length ? `${contradictoryReviews.length} contradictory` : 'no contradiction'}
                    </span>
                    {partialReviews.length > 0 && (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">
                        partial evidence present
                      </span>
                    )}
                    {contextReviews.length > 0 && (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-700">
                        context evidence present
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-xs text-slate-600 leading-relaxed">
                    The preview below shows the strongest distinct source excerpts for this objective. The raw evidence map and prompt counts remain available in traceability views.
                  </p>
                </div>
              )}

              <div className="mt-4">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-600 mb-2">Source Excerpts</p>
                <div className="space-y-3">
                  {previewEvidenceGroups.map(([role, items]) => {
                    const config = evidenceRoleConfig[role]
                    const originalItems = evidenceGroups.find(([candidateRole]) => candidateRole === role)?.[1] || []
                    return (
                    <section key={role} className="border border-gray-200 rounded-lg bg-gray-50 px-3 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                        <p className={`text-[11px] font-semibold uppercase tracking-wide ${
                          config.tone === 'emerald' ? 'text-emerald-700' :
                          config.tone === 'red' ? 'text-red-700' :
                          config.tone === 'amber' ? 'text-amber-700' :
                          'text-slate-700'
                        }`}>
                          {config.label}
                        </p>
                        <span className="text-[11px] text-gray-500">
                          {items.length} distinct preview{items.length === 1 ? '' : 's'} from {originalItems.length} match{originalItems.length === 1 ? '' : 'es'}
                        </span>
                      </div>
                      {items.length === 0 ? (
                        <p className="text-sm text-gray-500">{config.empty}</p>
                      ) : (
                        <div className="space-y-2">
                          {items.slice(0, 4).map((item, index) => (
                            <EvidenceReviewCard
                              key={`${role}-${item.unit_id || index}`}
                              item={item}
                              role={role}
                              index={index}
                              docMap={docMap}
                              onOpenEvidence={setEvidenceModal}
                            />
                          ))}
                          {items.length > 4 && (
                            <p className="text-xs text-gray-500">
                              Showing the top 4 distinct snippets by objective relevance. {items.length - 4} additional distinct snippet{items.length - 4 === 1 ? '' : 's'} are in this group.
                            </p>
                          )}
                        </div>
                      )}
                  </section>
                  )})}
                </div>
              </div>

              {reviews.length > 4 && (
                <button
                  type="button"
                  onClick={() => setAllEvidenceModal({
                    objectiveId: obj.objective_id,
                    objectiveText: obj.objective_text,
                    consideredCount,
                    promptCount,
                    groups: evidenceGroups,
                  })}
                  className="mt-3 inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
                >
                  <Maximize2 size={13} />
                  View full evidence map for this objective
                </button>
              )}
                </>
              )}

            </div>
          )})}
        </div>
      )}

        {tab === 'evidence' && (
          <div className="space-y-2">
            {corroboration && (
              <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
                <p className="text-xs font-semibold text-blue-700 uppercase tracking-wide mb-1">Evidence Map Breadth</p>
                <p className="text-sm text-gray-700">
                  This traceability map has {triage.length} triage row{triage.length === 1 ? '' : 's'} across {corroboration.supporting_documents || 0} supporting document{(corroboration.supporting_documents || 0) === 1 ? '' : 's'}. The list below shows {distinctTriage.length} distinct source excerpt{distinctTriage.length === 1 ? '' : 's'} after collapsing repeated objective routing text.
                </p>
              </div>
            )}
            {distinctTriage.map(item => {
              const rationale = cleanEvidenceNote(item.rationale)
              const excerpt = cleanEvidenceExcerpt(item.excerpt)
              const docRef = resolveEvidenceDocument(item, docMap)
              const title = evidenceSourceTitle(item, docMap)
              return (
              <div key={`${item.unit_id}-${item.sort_order}`} className="rounded-lg border border-gray-200 bg-white px-4 py-3">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    {docRef?.download_url ? (
                      <button
                        type="button"
                        onClick={() => downloadByUrl(docRef.download_url, docRef.filename || title)}
                        className="font-semibold text-sm text-blue-700 leading-snug hover:text-blue-900 hover:underline text-left"
                        title={`Open ${docRef.filename || title}`}
                      >
                        {title}
                      </button>
                    ) : (
                      <p className="font-semibold text-sm text-blue-700 leading-snug">{title}</p>
                    )}
                    <div className="flex flex-wrap gap-2 mt-1">
                      <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${
                        item.triage_role === 'supporting' ? 'bg-emerald-100 text-emerald-700' :
                        item.triage_role === 'contradictory' ? 'bg-red-100 text-red-700' :
                        item.triage_role === 'partial' ? 'bg-amber-100 text-amber-700' :
                        'bg-slate-100 text-slate-600'
                      }`}>
                        {evidenceRoleLabel(item.triage_role)}
                      </span>
                      {[item.source_type, item.artifact_type, item.evidence_strength].filter(Boolean).map((label) => (
                        <span key={label} className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                          {String(label).replace(/_/g, ' ')}
                        </span>
                      ))}
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700">
                        Relevance {evidenceRelevance(item).toFixed(2)}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => openCyberAssistant({
                      mode: 'control',
                      title: `${upperId} Evidence Assistant`,
                      projectId: Number(projectId),
                      assessmentId: Number(assessmentId),
                      initialPrompt: buildEvidenceAssistantPrompt({
                        controlId: upperId,
                        citationLabel: item.citation_label || `Evidence for ${upperId}`,
                        triageRole: item.triage_role,
                        excerpt: excerpt || rationale || '',
                      }),
                      hiddenInitialMessage: true,
                      attachments: [
                        {
                          type: 'control',
                          resource_id: String(upperId),
                          context_json: {
                            control_id: upperId,
                            label: `Control: ${upperId}`,
                            control_title: criteria?.control_title || upperId,
                            assessment_id: Number(assessmentId),
                          },
                        },
                        {
                          type: 'evidence',
                          resource_id: String(item.unit_id || `${upperId}-${item.sort_order}`),
                          context_json: {
                            label: item.citation_label || `Evidence for ${upperId}`,
                            source_label: item.citation_label || `Evidence for ${upperId}`,
                            excerpt: excerpt || rationale || '',
                            triage_role: item.triage_role,
                            source_type: item.source_type,
                            artifact_type: item.artifact_type,
                            evidence_strength: item.evidence_strength,
                          },
                        },
                      ],
                    })}
                    className="inline-flex items-center gap-1 rounded-md border border-violet-200 bg-violet-50 px-2 py-1 text-[11px] font-medium text-violet-700 hover:bg-violet-100 transition-colors self-start"
                    title="Ask AI about this evidence"
                  >
                    <MessageSquare size={11} />
                    Ask AI
                  </button>
                </div>
                {excerpt ? (
                  <div className="mt-2 border-l-2 border-blue-300 pl-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-700 mb-1">Source Excerpt</p>
                    <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{excerpt}</p>
                  </div>
                ) : (
                  <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                    <p className="text-xs font-semibold text-amber-800">Source excerpt not captured</p>
                    <p className="text-xs text-amber-700 mt-0.5">This item has assessment context, but no stored source excerpt to quote directly.</p>
                  </div>
                )}
                {rationale && (
                  <details className="mt-2 rounded-md border border-gray-100 bg-gray-50 px-3 py-2">
                    <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                      Assessment Interpretation
                    </summary>
                    <p className="text-xs text-gray-600 leading-relaxed mt-2 whitespace-pre-wrap">{rationale}</p>
                  </details>
                )}
                {item._similarCount > 1 && (
                  <p className="mt-2 text-xs text-indigo-600">{item._similarCount} overlapping triage rows were collapsed into this evidence card.</p>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setEvidenceModal({
                      item,
                      title,
                      docRef,
                      excerpt,
                      note: rationale,
                    })}
                    className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100"
                  >
                    <Maximize2 size={11} />
                    Open source
                  </button>
                  {docRef?.download_url && (
                    <button
                      type="button"
                      onClick={() => downloadByUrl(docRef.download_url, docRef.filename || title)}
                      className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-100"
                    >
                      <Download size={11} />
                      Open document
                    </button>
                  )}
                </div>
              </div>
            )})}
        </div>
      )}

      {tab === 'challenge' && challenge?.dissent_note && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-xs font-semibold text-amber-700 mb-2 uppercase tracking-wide">AI Dissent</p>
          <p className="text-sm text-gray-800 leading-relaxed mb-2">{challenge.dissent_note}</p>
          {challenge.challenged_objectives?.length > 0 && (
            <div className="text-xs text-amber-700">Dissented objectives: {challenge.challenged_objectives.join(', ')}</div>
          )}
        </div>
      )}

      {allEvidenceModal && (
        <div
          className="fixed inset-0 z-[9999] bg-black/50 flex items-center justify-center p-4"
          onClick={() => setAllEvidenceModal(null)}
        >
          <div
            className="bg-white rounded-xl shadow-2xl w-full max-w-5xl max-h-[88vh] flex flex-col"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-gray-100">
              <div>
                <p className="text-xs font-semibold text-gray-500 mb-1">{allEvidenceModal.objectiveId}</p>
                <h3 className="text-base font-bold text-gray-900">Evidence Map for Objective</h3>
                <p className="text-sm text-gray-700 leading-relaxed mt-1">{allEvidenceModal.objectiveText}</p>
                <p className="text-xs text-gray-500 mt-2">
                  Showing all {allEvidenceModal.consideredCount} database snippets that matched this objective. {allEvidenceModal.promptCount} were sent to the assessor model. Repeated snippets are intentionally preserved here for auditability.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setAllEvidenceModal(null)}
                className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                title="Close evidence list"
              >
                <X size={18} />
              </button>
            </div>
            <div className="overflow-y-auto px-5 py-4 space-y-4">
              {allEvidenceModal.groups.map(([role, items]) => {
                const config = evidenceRoleConfig[role]
                return (
                  <section key={`modal-${role}`} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                      <p className={`text-[11px] font-semibold uppercase tracking-wide ${
                        config.tone === 'emerald' ? 'text-emerald-700' :
                        config.tone === 'red' ? 'text-red-700' :
                        config.tone === 'amber' ? 'text-amber-700' :
                        'text-slate-700'
                      }`}>
                        {config.label}
                      </p>
                      <span className="text-[11px] text-gray-500">{items.length} item{items.length === 1 ? '' : 's'}</span>
                    </div>
                    <div className="space-y-2">
                      {items.map((item, index) => (
                        <EvidenceReviewCard
                          key={`modal-${role}-${item.unit_id || index}`}
                          item={item}
                          role={role}
                          index={index}
                          docMap={docMap}
                          onOpenEvidence={setEvidenceModal}
                        />
                      ))}
                    </div>
                  </section>
                )
              })}
            </div>
            <div className="flex justify-end px-5 py-3 border-t border-gray-100">
              <button
                type="button"
                onClick={() => setAllEvidenceModal(null)}
                className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {evidenceModal && (
        <div
          className="fixed inset-0 z-[10000] bg-black/50 flex items-center justify-center p-4"
          onClick={() => setEvidenceModal(null)}
        >
          <div
            className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[86vh] flex flex-col"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-gray-100">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-gray-500 mb-1">Source Excerpt</p>
                <h3 className="text-base font-bold text-gray-900 leading-snug">{evidenceModal.title}</h3>
                <div className="flex flex-wrap gap-2 mt-2">
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700">
                    Relevance {evidenceRelevance(evidenceModal.item).toFixed(2)}
                  </span>
                  {[evidenceModal.item?.source_type, evidenceModal.item?.artifact_type, evidenceModal.item?.evidence_strength].filter(Boolean).map((label) => (
                    <span key={label} className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                      {String(label).replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setEvidenceModal(null)}
                className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                title="Close evidence"
              >
                <X size={18} />
              </button>
            </div>
            <div className="overflow-y-auto px-5 py-4 space-y-4">
              {evidenceModal.excerpt && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Source Excerpt</p>
                  <p className="text-sm text-gray-900 leading-relaxed whitespace-pre-wrap">{evidenceModal.excerpt}</p>
                </div>
              )}
              {evidenceModal.note && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Assessment Interpretation</p>
                  <p className="text-sm text-gray-900 leading-relaxed whitespace-pre-wrap">{evidenceModal.note}</p>
                </div>
              )}
              {!evidenceModal.excerpt && !evidenceModal.note && (
                <p className="text-sm text-gray-500">No excerpt text is available for this evidence item.</p>
              )}
            </div>
            <div className="flex justify-between gap-3 px-5 py-3 border-t border-gray-100">
              <div>
                {evidenceModal.docRef?.download_url && (
                  <button
                    type="button"
                    onClick={() => downloadByUrl(evidenceModal.docRef.download_url, evidenceModal.docRef.filename || evidenceModal.title)}
                    className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100"
                  >
                    <Download size={14} />
                    Open document
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={() => setEvidenceModal(null)}
                className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ControlDetail({ f, projectId, assessmentId, onFindingUpdate, override, onUpsert, docMap }) {
  return (
    <div className="px-4 sm:px-6 lg:px-10 pb-4 pt-2 bg-blue-50/30 border-t border-blue-100">
      {/* Tested at */}
      {f.tested_at && (
        <div className="flex items-center gap-1.5 text-xs text-gray-400 mb-3">
          <Clock size={11} />
          Tested {fmt12hr(f.tested_at)}
        </div>
      )}

      {/* Applicability change detail */}
      {f.applicability_changed && f.prev_status && (
        <div className="mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg">
          <p className="text-xs font-semibold text-amber-700 mb-0.5">Applicability Changed Since Last Run</p>
          <p className="text-xs text-amber-600">
            Previous status: <span className="font-mono font-medium">{f.prev_status}</span>
              {' '}-&gt; Current: <span className="font-mono font-medium">{f.status}</span>
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 2xl:grid-cols-[minmax(0,1fr)_320px] gap-4 items-start">
        <div className="min-w-0">
          <ControlWorkbench
            projectId={projectId}
            assessmentId={assessmentId}
            controlId={f.control_id}
            docMap={docMap}
          />
        </div>

        <aside className="2xl:sticky 2xl:top-4 space-y-4">
          <AssessorActions finding={f} override={override} onUpsert={onUpsert} />

          <div className="rounded-xl border border-gray-200 bg-white px-4 py-3">
            <p className="text-xs font-semibold text-gray-600 mb-2 uppercase tracking-wide">Analyst Notes</p>
            <NotesEditor
              findingId={f.id}
              initialNotes={f.notes}
              projectId={projectId}
              assessmentId={assessmentId}
              onSaved={onFindingUpdate}
            />
          </div>
        </aside>
      </div>

      <details className="mt-4 rounded-xl border border-gray-200 bg-white">
        <summary className="cursor-pointer px-4 py-3 text-xs font-semibold uppercase tracking-wide text-gray-600">
          Supporting Finding Analysis
        </summary>
        <div className="border-t border-gray-100 px-4 py-3">
          {f.implementation_statement && (
            <div className="mb-3">
              <p className="text-xs font-semibold text-gray-500 mb-1">Implementation Statement</p>
              <TextBlock text={f.implementation_statement} />
            </div>
          )}
          {f.gaps?.length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-semibold text-red-500 mb-1">Gaps</p>
              <ul className="space-y-1.5">
                {f.gaps.map((g, i) => (
                  <li key={i} className="text-sm text-gray-700 flex gap-2 leading-relaxed">
                    <span className="text-red-400 flex-shrink-0 mt-0.5">*</span>
                    <span>{typeof g === 'string' ? g.replace(/\\n/g, '\n') : g}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <RemediationPlan text={f.remediation_plan} />
          <EvidenceCitations
            citations={f.evidence_citations}
            docMap={docMap}
            projectId={projectId}
            assessmentId={assessmentId}
            controlId={f.control_id}
            controlTitle={f.control_title}
          />
        </div>
      </details>

      {/* Control History */}
      <ControlHistory projectId={projectId} controlId={f.control_id} />
    </div>
  )
}

function FamilyRollup({ family, findings, defaultOpen, onManualReview, projectId, assessmentId, onFindingUpdate, overrideMap, onUpsert, onExpand, docMap, onAskAssistant = null, onSelectControl = null, selectedControlId = null }) {
  const [open, setOpen] = useState(defaultOpen || false)
  const [expandedControl, setExpandedControl] = useState(null)

  const expand = (id) => {
    setExpandedControl(id)
    if (id && onExpand) onExpand()  // force fresh fetch when opening a row
  }

  const baseFindings = findings.filter(f => !/\(/.test(f.control_id))
  const enhancementMap = {}
  findings.filter(f => /\(/.test(f.control_id)).forEach(f => {
    const base = f.control_id.replace(/\(\d+\)$/, '')
    if (!enhancementMap[base]) enhancementMap[base] = []
    enhancementMap[base].push(f)
  })
  baseFindings.sort(sortByControlId)

  const counts = findings.reduce((acc, f) => { acc[f.status] = (acc[f.status] || 0) + 1; return acc }, {})
  const pct = findings.length ? Math.round(((counts.compliant || 0) / findings.length) * 100) : 0

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden mb-3">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-5 py-3.5 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        {open ? <ChevronDown size={16} className="text-gray-400 flex-shrink-0" /> : <ChevronRight size={16} className="text-gray-400 flex-shrink-0" />}
        <span className="font-mono text-sm font-bold text-blue-700 w-10 flex-shrink-0">{family}</span>
        <span className="font-semibold text-sm text-gray-900 flex-1">{FAMILY_NAMES[family] || family}</span>
        <div className="flex items-center gap-3 text-xs">
          {counts.compliant > 0 && <span className="text-green-700 font-medium">{counts.compliant} compliant</span>}
          {counts.partially_compliant > 0 && <span className="text-amber-600 font-medium">{counts.partially_compliant} partial</span>}
          {counts.non_compliant > 0 && <span className="text-red-700 font-medium">{counts.non_compliant} non-compliant</span>}
          {counts.not_applicable > 0 && <span className="text-slate-500 font-medium">{counts.not_applicable} N/A</span>}
          <span className="text-gray-500 ml-1">{findings.length} total</span>
        </div>
        <div className="w-24 h-1.5 bg-gray-200 rounded-full ml-3 flex-shrink-0">
          <div className="h-1.5 bg-green-600 rounded-full" style={{ width: `${pct}%` }} />
        </div>
      </button>

      {open && (
        <div className="divide-y divide-gray-100">
          {baseFindings.map(f => {
            const enhancements = (enhancementMap[f.control_id] || []).sort(sortByControlId)
            const isExpanded = expandedControl === f.control_id
              || enhancements.some(e => expandedControl === e.control_id)
            return (
              <div key={f.control_id}>
                <button
                  onClick={() => expand(
                    expandedControl === f.control_id ? null
                    : enhancements.some(e => expandedControl === e.control_id) ? null
                    : f.control_id
                  )}
                  className={`w-full flex items-center gap-3 px-5 py-2.5 transition-colors text-left ${
                    selectedControlId === f.control_id ? 'bg-blue-50 hover:bg-blue-100/70' : 'hover:bg-gray-50'
                  }`}
                >
                  {isExpanded ? <ChevronDown size={13} className="text-gray-500 flex-shrink-0" /> : <ChevronRight size={13} className="text-gray-500 flex-shrink-0" />}
                  <span className="flex items-center gap-1 w-24 flex-shrink-0">
                    <span className="font-mono text-xs text-blue-700 font-bold">
                      {f.control_id}
                      <OverrideIndicator override={overrideMap[f.control_id]} />
                    </span>
                    <ControlReferenceButton controlId={f.control_id} iconOnly />
                    {onAskAssistant && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          onAskAssistant(f)
                        }}
                        className="text-violet-600 hover:text-violet-800"
                        title="Ask AI about this control"
                      >
                        <MessageSquare size={12} />
                      </button>
                    )}
                  </span>
                  <span className="text-sm text-gray-800 flex-1 truncate">{f.control_title}</span>
                  <OverrideBadges f={f} />
                  {f.tested_at && (
                    <span className="text-xs text-gray-500 mr-2 hidden lg:block">{fmt12hr(f.tested_at)}</span>
                  )}
                  <span className="text-xs text-gray-500 mr-3">{f.confidence_score != null ? `${(f.confidence_score * 100).toFixed(0)}%` : ''}</span>
                  <StatusBadge status={f.status} override={overrideMap[f.control_id]} />
                  {enhancements.length > 0 && (
                    <span className="ml-2 text-xs text-gray-400">{enhancements.length} enh.</span>
                  )}
                  {(f.status === 'not_reviewed' || needsDisplayReview(f)) && onManualReview && (
                    <button
                      onClick={e => { e.stopPropagation(); onManualReview(f) }}
                      className="ml-2 text-red-500 hover:text-red-700"
                      title="Manual review"
                    >
                      <Wrench size={12} />
                    </button>
                  )}
                  {onSelectControl && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        onSelectControl(f.control_id)
                      }}
                      className={`ml-1 rounded-md border px-2 py-1 text-[11px] font-medium ${
                        selectedControlId === f.control_id
                          ? 'border-blue-300 bg-blue-100 text-blue-800'
                          : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      {selectedControlId === f.control_id ? 'Selected' : 'Inspect'}
                    </button>
                  )}
                </button>

                {isExpanded && (
                  <>
                    <ControlDetail
                      f={f}
                      projectId={projectId}
                      assessmentId={assessmentId}
                      onFindingUpdate={onFindingUpdate}
                      override={overrideMap[f.control_id]}
                      onUpsert={(body) => onUpsert(f.control_id, body)}
                      docMap={docMap}
                    />
                    {/* Enhancements */}
                    {enhancements.length > 0 && (
                      <div className="bg-blue-50/20 border-t border-blue-100">
                        <p className="text-xs font-semibold text-gray-600 px-10 pt-3 pb-1 uppercase tracking-wide">CONTROL ENHANCEMENTS</p>
                        <div className="divide-y divide-blue-100/60">
                          {enhancements.map(e => {
                            const eExpanded = expandedControl === e.control_id
                            return (
                              <div key={e.control_id}>
                                <button
                                  onClick={() => expand(eExpanded ? f.control_id : e.control_id)}
                                  className={`w-full flex items-center gap-3 px-10 py-2 transition-colors text-left ${
                                    selectedControlId === e.control_id ? 'bg-blue-100/70 hover:bg-blue-100' : 'hover:bg-blue-50/30'
                                  }`}
                                >
                                  {eExpanded ? <ChevronDown size={12} className="text-gray-500 flex-shrink-0" /> : <ChevronRight size={12} className="text-gray-500 flex-shrink-0" />}
                                  <span className="flex items-center gap-1 w-24 flex-shrink-0">
                                    <span className="font-mono text-xs text-blue-700 font-bold">{e.control_id}</span>
                                    <ControlReferenceButton controlId={e.control_id} iconOnly />
                                    {onAskAssistant && (
                                      <button
                                        type="button"
                                        onClick={(ev) => {
                                          ev.stopPropagation()
                                          onAskAssistant(e)
                                        }}
                                        className="text-violet-600 hover:text-violet-800"
                                        title="Ask AI about this enhancement"
                                      >
                                        <MessageSquare size={12} />
                                      </button>
                                    )}
                                  </span>
                                  <span className="text-sm text-gray-800 flex-1 truncate">{e.control_title}</span>
                                  <OverrideBadges f={e} />
                                  {e.tested_at && (
                                    <span className="text-xs text-gray-500 mr-2 hidden lg:block">{fmt12hr(e.tested_at)}</span>
                                  )}
                                  <StatusBadge status={e.status} />
                                  {onSelectControl && (
                                    <button
                                      type="button"
                                      onClick={(ev) => {
                                        ev.stopPropagation()
                                        onSelectControl(e.control_id)
                                      }}
                                      className={`ml-1 rounded-md border px-2 py-1 text-[11px] font-medium ${
                                        selectedControlId === e.control_id
                                          ? 'border-blue-300 bg-blue-100 text-blue-800'
                                          : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                                      }`}
                                    >
                                      {selectedControlId === e.control_id ? 'Selected' : 'Inspect'}
                                    </button>
                                  )}
                                </button>
                                {eExpanded && (
                                  <ControlDetail
                                    f={e}
                                    projectId={projectId}
                                    assessmentId={assessmentId}
                                    onFindingUpdate={onFindingUpdate}
                                    override={overrideMap[e.control_id]}
                                    onUpsert={(body) => onUpsert(e.control_id, body)}
                                    docMap={docMap}
                                  />
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// â”€â”€ Cross-run Delta View â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

// â”€â”€ Remediation View â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function RemediationView({ projectId, assessmentId, findings }) {
  const qc = useQueryClient()
  const [remTab, setRemTab] = useState('tools')  // 'tools' | 'closure'
  const [artifactPackageStyle, setArtifactPackageStyle] = useState('standard')
  const [testPackageStyle, setTestPackageStyle] = useState('standard')
  const [testEvidenceMix, setTestEvidenceMix] = useState('balanced')
  const [testTargetProfile, setTestTargetProfile] = useState('passing_ato')

  const isActive = (r) => r?.status === 'running' || r?.status === 'pending'

  const { data: reports = [] } = useQuery({
    queryKey: ['remediation-reports', assessmentId],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/remediation`).then(r => r.data),
    refetchInterval: (query) => (query.state.data || []).some(isActive) ? 2000 : false,
  })

  const { data: autoDocs = [], refetch: refetchDocs } = useQuery({
    queryKey: ['remediation-docs', assessmentId],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/remediation/docs`).then(r => r.data),
    refetchInterval: reports.some(isActive) ? 3000 : false,
  })
  const { data: draftArtifactReport } = useQuery({
    queryKey: ['draft-package-report', assessmentId],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/closure/draft-packages/report`).then(r => r.data),
    enabled: !!assessmentId,
  })

  const guideReport       = reports.find(r => r.report_type === 'guide')
  const artifactsReport   = reports.find(r => r.report_type === 'artifacts')
  const testDatasetReport = reports.find(r => r.report_type === 'test_dataset')

  const startGuide      = useMutation({ mutationFn: () => api.post(`/projects/${projectId}/assessments/${assessmentId}/remediation/guide`),        onSuccess: () => qc.invalidateQueries({ queryKey: ['remediation-reports', assessmentId] }) })
  const startArtifacts  = useMutation({ mutationFn: () => api.post(`/projects/${projectId}/assessments/${assessmentId}/remediation/artifacts`, { package_style: artifactPackageStyle }),     onSuccess: () => qc.invalidateQueries({ queryKey: ['remediation-reports', assessmentId] }) })
  const startTestDataset= useMutation({ mutationFn: () => api.post(`/projects/${projectId}/assessments/${assessmentId}/remediation/test-dataset`, { package_style: testPackageStyle, evidence_mix: testEvidenceMix, target_profile: testTargetProfile }),  onSuccess: () => qc.invalidateQueries({ queryKey: ['remediation-reports', assessmentId] }) })
  const deleteAllDocs   = useMutation({ mutationFn: () => api.delete(`/projects/${projectId}/assessments/${assessmentId}/remediation/docs`),         onSuccess: () => { qc.invalidateQueries({ queryKey: ['remediation-docs', assessmentId] }) } })
  const deleteOneDoc    = useMutation({ mutationFn: (id) => api.delete(`/projects/${projectId}/assessments/${assessmentId}/remediation/docs/${id}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ['remediation-docs', assessmentId] }) } })

  const { data: guideDetail }       = useQuery({ queryKey: ['remediation-report', guideReport?.id],       queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/remediation/${guideReport.id}`).then(r => r.data),       enabled: guideReport?.status === 'complete' })
  const { data: artifactsDetail }   = useQuery({ queryKey: ['remediation-report', artifactsReport?.id],   queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/remediation/${artifactsReport.id}`).then(r => r.data),   enabled: artifactsReport?.status === 'complete' })
  const { data: testDatasetDetail } = useQuery({ queryKey: ['remediation-report', testDatasetReport?.id], queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/remediation/${testDatasetReport.id}`).then(r => r.data), enabled: testDatasetReport?.status === 'complete' })

  const nc = findings.filter(f => f.status === 'non_compliant').length
  const pc = findings.filter(f => f.status === 'partially_compliant').length

  const parseColor = (s) => ({ indexed: 'text-emerald-600', complete: 'text-emerald-600', pending: 'text-gray-400', processing: 'text-blue-500', failed: 'text-red-500', index_failed: 'text-red-500' }[s] || 'text-gray-400')
  const parseLabel = (s) => ({ indexed: 'Indexed', complete: 'Ready', pending: 'Queued...', processing: 'Indexing...', failed: 'Failed', index_failed: 'Index failed' }[s] || s)

  return (
    <div className="space-y-4">
      {/* Sub-tab switcher */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="flex border-b border-gray-200">
          <button onClick={() => setRemTab('tools')}
            className={`flex items-center gap-2 px-5 py-3 text-sm font-medium transition-colors ${
              remTab === 'tools'
                ? 'border-b-2 border-emerald-600 text-emerald-700 bg-emerald-50'
                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            }`}>
            <Wrench size={14} />
            AI Remediation Tools
          </button>
          <button onClick={() => setRemTab('closure')}
            className={`flex items-center gap-2 px-5 py-3 text-sm font-medium transition-colors ${
              remTab === 'closure'
                ? 'border-b-2 border-violet-600 text-violet-700 bg-violet-50'
                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            }`}>
            <Shield size={14} />
            Control Closure Workflow
            {(nc + pc) > 0 && (
              <span className={`text-xs px-1.5 py-0.5 rounded-full font-bold ${remTab === 'closure' ? 'bg-violet-200 text-violet-800' : 'bg-gray-200 text-gray-600'}`}>
                {nc + pc}
              </span>
            )}
          </button>
        </div>
        <div className="px-5 py-3">
          {remTab === 'tools' ? (
            <div>
              <h2 className="text-sm font-bold text-gray-900 mb-0.5 flex items-center gap-2">
                <Wrench size={15} className="text-emerald-600" />
                Gap Closure &amp; Remediation Tools
              </h2>
              <p className="text-xs text-gray-500">
                <span className="text-red-600 font-medium">{nc} non-compliant</span>{' '}|{' '}
                <span className="text-amber-600 font-medium">{pc} partially compliant</span>{' '}
                - generate a guide and remediation artifacts to close these gaps, then re-run the assessment to validate.
              </p>
            </div>
          ) : (
            <div>
              <h2 className="text-sm font-bold text-gray-900 mb-0.5 flex items-center gap-2">
                <Shield size={15} className="text-violet-600" />
                Control Closure Workflow
              </h2>
              <p className="text-xs text-gray-500">
                AI-assisted, evidence-based closure aligned with NIST RMF Execute.
                Work through each finding interactively, generate targeted artifacts, and route them through a documented approval chain.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Tab content */}
      {remTab === 'closure' && (
        <ClosureWorkflow projectId={projectId} assessmentId={assessmentId} findings={findings} />
      )}

      {remTab === 'tools' && (<>
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Control-owner draft remediation report</p>
            <p className="mt-1 text-sm text-emerald-900">
              Use AI-generated draft packages as review material for control owners. Each package stays labeled as draft work until the owner confirms accuracy and supporting records are attached.
            </p>
          </div>
          {draftArtifactReport?.summary && (
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-white px-2.5 py-1 font-semibold text-emerald-800">{draftArtifactReport.summary.controls_needing_action} controls need action</span>
              <span className="rounded-full bg-white px-2.5 py-1 font-semibold text-emerald-800">{draftArtifactReport.summary.drafts_generated} draft packages</span>
              <span className="rounded-full bg-white px-2.5 py-1 font-semibold text-emerald-800">{draftArtifactReport.summary.awaiting_owner_review} awaiting owner review</span>
            </div>
          )}
        </div>
        {draftArtifactReport?.controls?.length > 0 && (
          <div className="mt-4 overflow-hidden rounded-xl border border-emerald-100 bg-white">
            <table className="w-full text-sm">
              <thead className="border-b border-emerald-100 bg-emerald-50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-emerald-900">Control</th>
                  <th className="px-4 py-3 text-left font-medium text-emerald-900">Draft state</th>
                  <th className="px-4 py-3 text-left font-medium text-emerald-900">Draft artifacts</th>
                  <th className="px-4 py-3 text-left font-medium text-emerald-900">Next review step</th>
                </tr>
              </thead>
              <tbody>
                {draftArtifactReport.controls.map((item) => (
                  <tr key={`draft-package-report-${item.control_id}`} className="border-b border-gray-100 align-top">
                    <td className="px-4 py-3">
                      <div className="font-mono text-xs font-semibold text-blue-700">{item.control_id}</div>
                      <div className="mt-1 text-sm text-gray-800">{item.control_title}</div>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">{titleCaseLabel(String(item.state || 'not_started').replace(/_/g, ' '))}</td>
                    <td className="px-4 py-3">
                      {(item.generated_artifacts || []).length > 0 ? (
                        <div className="space-y-2">
                          {item.generated_artifacts.map((artifact) => (
                            <button
                              key={`${item.control_id}-draft-${artifact.document_id}`}
                              type="button"
                              onClick={() => downloadByUrl(artifact.download_url, artifact.filename)}
                              className="block text-left text-sm text-blue-700 hover:underline"
                            >
                              {artifact.artifact_title}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <span className="text-sm text-gray-500">No draft package generated yet.</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">{item.next_approval_step?.label || 'No review step pending'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* (existing tools content below) */}
      {autoDocs.length > 0 && (
        <div className="flex items-center justify-end gap-2">
          <span className="text-xs bg-emerald-100 text-emerald-700 border border-emerald-200 px-2.5 py-1 rounded-full font-medium">
            {autoDocs.length} auto-generated doc{autoDocs.length !== 1 ? 's' : ''}
          </span>
          <button onClick={() => { if (window.confirm(`Remove all ${autoDocs.length} auto-generated documents?`)) deleteAllDocs.mutate() }}
            disabled={deleteAllDocs.isPending}
            className="text-xs text-red-600 border border-red-200 px-2.5 py-1 rounded hover:bg-red-50 disabled:opacity-50">
            Remove All
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <RemediationCard title="Remediation Guide"
          description="A prioritized, step-by-step action plan for every compliance gap - with responsible roles, effort estimates, success criteria, and template policy language."
          icon={<ClipboardList size={28} className="text-blue-600" />} accentColor="blue"
          report={guideReport} detail={guideDetail}
          onAskAssistant={() => openCyberAssistant({
            mode: 'remediation',
            title: 'Remediation Guide Assistant',
            projectId: Number(projectId),
            assessmentId: Number(assessmentId),
            attachments: [{
              type: 'remediation',
              resource_id: guideReport?.id ? String(guideReport.id) : `assessment-${assessmentId}-guide`,
              context_json: {
                label: 'Remediation Guide',
                report_id: guideReport?.id || null,
                assessment_id: Number(assessmentId),
                finding_summary: `${nc} non-compliant, ${pc} partially compliant controls`,
              },
            }],
          })}
          onGenerate={() => startGuide.mutate()} isGenerating={startGuide.isPending}
          onCancel={guideReport?.id ? () => api.post(`/projects/${projectId}/assessments/${assessmentId}/remediation/${guideReport.id}/cancel`).then(() => qc.invalidateQueries({ queryKey: ['remediation-reports', assessmentId] })) : null}
          onReset={guideReport?.id && !['running','pending'].includes(guideReport?.status) ? () => api.delete(`/projects/${projectId}/assessments/${assessmentId}/remediation/${guideReport.id}`).then(() => qc.invalidateQueries({ queryKey: ['remediation-reports', assessmentId] })) : null}
          downloads={guideReport?.status === 'complete' ? [
            { label: 'Word Guide', url: `/api/projects/${projectId}/assessments/${assessmentId}/remediation/${guideReport?.id}/download?fmt=docx` },
            { label: 'Excel Tracker', url: `/api/projects/${projectId}/assessments/${assessmentId}/remediation/${guideReport?.id}/download?fmt=xlsx` },
          ] : []}
          renderContent={(content) => <GuideContent content={content} />}
        />
        <RemediationCard title="Remediation Artifacts"
          icon={<File size={28} className="text-emerald-600" />} accentColor="emerald"
          description="Targeted reassessment-ready artifacts for failing controls. Generates a consolidated package of policy, procedure, SSP, and technical implementation evidence grouped by gap area, then saves the results to your document library for reassessment."
          onAskAssistant={() => openCyberAssistant({
            mode: 'remediation',
            title: 'Remediation Artifacts Assistant',
            projectId: Number(projectId),
            assessmentId: Number(assessmentId),
            attachments: [{
              type: 'remediation',
              resource_id: artifactsReport?.id ? String(artifactsReport.id) : `assessment-${assessmentId}-artifacts`,
              context_json: {
                label: 'Remediation Artifacts',
                report_id: artifactsReport?.id || null,
                assessment_id: Number(assessmentId),
                target_package_style: artifactPackageStyle,
                finding_summary: `${nc} non-compliant, ${pc} partially compliant controls`,
              },
            }],
          })}
          helpContent={
            <>
              <p className="font-semibold">How package style works</p>
              <p><span className="font-medium">Lean:</span> smallest reassessment package, fewer artifact bundles, fastest generation.</p>
              <p><span className="font-medium">Standard:</span> balanced remediation package and the best default.</p>
              <p><span className="font-medium">Robust:</span> more corroborating implementation artifacts and stronger technical support.</p>
              <p className="text-xs text-blue-700">Remediation Artifacts now generate current-state implementation evidence intended to improve reassessment results, not just advisory templates.</p>
            </>
          }
          report={artifactsReport} detail={artifactsDetail}
          setupContent={
            <label className="block text-xs text-gray-600 mb-4">
              <span className="block font-semibold text-gray-500 mb-1">Package Style</span>
              <select value={artifactPackageStyle} onChange={e => setArtifactPackageStyle(e.target.value)} className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white text-sm">
                <option value="lean">Lean</option>
                <option value="standard">Standard</option>
                <option value="robust">Robust</option>
              </select>
            </label>
          }
          onGenerate={() => startArtifacts.mutate()} isGenerating={startArtifacts.isPending}
          onCancel={artifactsReport?.id ? () => api.post(`/projects/${projectId}/assessments/${assessmentId}/remediation/${artifactsReport.id}/cancel`).then(() => qc.invalidateQueries({ queryKey: ['remediation-reports', assessmentId] })) : null}
          onReset={artifactsReport?.id && !['running','pending'].includes(artifactsReport?.status) ? () => api.delete(`/projects/${projectId}/assessments/${assessmentId}/remediation/${artifactsReport.id}`).then(() => qc.invalidateQueries({ queryKey: ['remediation-reports', assessmentId] })) : null}
          downloads={artifactsReport?.status === 'complete' ? [
            { label: 'Download All (Word)', url: `/api/projects/${projectId}/assessments/${assessmentId}/remediation/${artifactsReport?.id}/download` },
          ] : []}
          renderContent={(content) => <ArtifactsContent content={content} />}
        />
      </div>

      {/* Test Dataset Generator â€” full-width card, separate from remediation tools */}
      <div className="bg-gradient-to-r from-violet-50 to-indigo-50 border border-violet-200 rounded-xl p-1">
        <RemediationCard title="Test Dataset Generator"
          description={
            <span>
              Generates a <strong>complete, realistic ATO evidence package</strong> as a consolidated
              set of SSP, policy, procedure, technical, and operational artifacts for a fictitious
              organization. You can target the expected pass profile and compare the next assessment
              against the intended result.{' '}
              <span className="text-violet-700 font-medium">
                All generated documents are indexed automatically for the next assessment run.
              </span>
            </span>
          }
          helpContent={
            <>
              <p className="font-semibold">How the options work</p>
              <p><span className="font-medium">Package Style:</span> Lean creates fewer broad artifacts, Standard is balanced, and Robust creates more supporting artifacts with stronger corroboration.</p>
              <p><span className="font-medium">Evidence Mix:</span> Balanced blends policy, procedure, technical, and operational evidence. Policy Heavy leans toward governance language. Implementation Heavy emphasizes technical and operational proof. Test Heavy emphasizes verification and exercise evidence.</p>
              <p><span className="font-medium">Expected Outcome:</span> Passing ATO targets near-full compliance. Mostly Compliant leaves a few intentional weaknesses. Mixed Realistic creates a more natural spread of compliant, partial, and failed controls. Stress Test is designed to challenge the assessor.</p>
              <p className="text-xs text-blue-700">The generated package is benchmarked against the intended outcome so you can compare expected vs. actual assessment results.</p>
            </>
          }
          icon={<FlaskConical size={28} className="text-violet-600" />}
          report={testDatasetReport} detail={testDatasetDetail}
          onAskAssistant={() => openCyberAssistant({
            mode: 'remediation',
            title: 'Test Dataset Assistant',
            projectId: Number(projectId),
            assessmentId: Number(assessmentId),
            attachments: [{
              type: 'remediation',
              resource_id: testDatasetReport?.id ? String(testDatasetReport.id) : `assessment-${assessmentId}-test-dataset`,
              context_json: {
                label: 'Test Dataset Generator',
                report_id: testDatasetReport?.id || null,
                assessment_id: Number(assessmentId),
                target_package_style: testPackageStyle,
                evidence_mix: testEvidenceMix,
                target_profile: testTargetProfile,
              },
            }],
          })}
          setupContent={
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
              <label className="text-xs text-gray-600">
                <span className="block font-semibold text-gray-500 mb-1">Package Style</span>
                <select value={testPackageStyle} onChange={e => setTestPackageStyle(e.target.value)} className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white text-sm">
                  <option value="lean">Lean</option>
                  <option value="standard">Standard</option>
                  <option value="robust">Robust</option>
                </select>
              </label>
              <label className="text-xs text-gray-600">
                <span className="block font-semibold text-gray-500 mb-1">Evidence Mix</span>
                <select value={testEvidenceMix} onChange={e => setTestEvidenceMix(e.target.value)} className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white text-sm">
                  <option value="balanced">Balanced</option>
                  <option value="policy_heavy">Policy Heavy</option>
                  <option value="implementation_heavy">Implementation Heavy</option>
                  <option value="test_heavy">Test Heavy</option>
                </select>
              </label>
              <label className="text-xs text-gray-600">
                <span className="block font-semibold text-gray-500 mb-1">Expected Outcome</span>
                <select value={testTargetProfile} onChange={e => setTestTargetProfile(e.target.value)} className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white text-sm">
                  <option value="passing_ato">Passing ATO</option>
                  <option value="mostly_compliant">Mostly Compliant</option>
                  <option value="mixed_realistic">Mixed Realistic</option>
                  <option value="stress_test">Stress Test</option>
                </select>
              </label>
            </div>
          }
          onGenerate={() => startTestDataset.mutate()} isGenerating={startTestDataset.isPending}
          onCancel={testDatasetReport?.id ? () => api.post(`/projects/${projectId}/assessments/${assessmentId}/remediation/${testDatasetReport.id}/cancel`).then(() => qc.invalidateQueries({ queryKey: ['remediation-reports', assessmentId] })) : null}
          onReset={testDatasetReport?.id && !['running','pending'].includes(testDatasetReport?.status) ? () => api.delete(`/projects/${projectId}/assessments/${assessmentId}/remediation/${testDatasetReport.id}`).then(() => qc.invalidateQueries({ queryKey: ['remediation-reports', assessmentId] })) : null}
          downloads={[]}
          renderContent={(content) => <TestDatasetContent content={content} />}
        />
      </div>

      {/* Auto-generated document library panel */}
      {autoDocs.length > 0 && (
        <div className="bg-white border border-emerald-200 rounded-xl overflow-hidden">
          <div className="px-5 py-3 bg-emerald-50 border-b border-emerald-100">
            <p className="text-xs font-semibold text-emerald-800">
              Auto-Generated Documents - added to project library | indexed for future assessments
            </p>
          </div>
          <div className="divide-y divide-gray-100">
            {autoDocs.map(doc => (
              <div key={doc.id} className="flex items-center justify-between px-5 py-2.5">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-base flex-shrink-0">[File]</span>
                  <div className="min-w-0">
                    <p className="text-sm text-gray-800 truncate">{doc.filename}</p>
                    <p className="text-xs text-gray-400">{Math.round(doc.file_size_bytes / 1024)} KB</p>
                  </div>
                </div>
                <div className="flex items-center gap-4 flex-shrink-0">
                  <span className={`text-xs font-medium ${parseColor(doc.parse_status)}`}>
                    {parseLabel(doc.parse_status)}
                  </span>
                  <button onClick={() => deleteOneDoc.mutate(doc.id)} disabled={deleteOneDoc.isPending}
                    className="text-xs text-red-500 hover:text-red-700 hover:bg-red-50 px-2 py-0.5 rounded">
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      </>)}
    </div>
  )
}

function RemediationCard({ title, description, icon, accentColor, report, detail, onGenerate, isGenerating, onCancel, onReset, downloads = [], renderContent, setupContent = null, helpContent = null, onAskAssistant = null }) {
  const colors = {
    blue:    { border: 'border-blue-200',    bg: 'bg-blue-50',    btn: 'bg-blue-600 hover:bg-blue-700',       text: 'text-blue-700',    badge: 'bg-blue-100 text-blue-700' },
    emerald: { border: 'border-emerald-200', bg: 'bg-emerald-50', btn: 'bg-emerald-600 hover:bg-emerald-700', text: 'text-emerald-700', badge: 'bg-emerald-100 text-emerald-700' },
    violet:  { border: 'border-violet-200',  bg: 'bg-violet-50',  btn: 'bg-violet-600 hover:bg-violet-700',   text: 'text-violet-700',  badge: 'bg-violet-100 text-violet-700' },
  }
  const c = colors[accentColor] || colors.blue

  const status = report?.status
  const isRunning = status === 'running' || status === 'pending'
  const [showHelp, setShowHelp] = useState(false)

  return (
    <div className={`bg-white border rounded-xl overflow-hidden ${status === 'complete' ? c.border : 'border-gray-200'}`}>
      {/* Card header */}
      <div className={`px-5 py-4 ${status === 'complete' ? c.bg : 'bg-gray-50'} border-b border-gray-100`}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            {icon}
            <div>
              <h3 className="text-sm font-bold text-gray-900">{title}</h3>
              {report?.summary && (
                <p className="text-xs text-gray-500 mt-0.5">
                  {report.summary.total_controls !== undefined
                    ? `${report.summary.non_compliant + (report.summary.partially_compliant || 0)} gaps - ${report.summary.total_actions || report.summary.controls_addressed || 0} actions`
                    : `${report.summary.families_covered || 0} families - ${report.summary.controls_addressed || 0} controls`}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {onAskAssistant && (
              <button
                type="button"
                onClick={onAskAssistant}
                className="inline-flex items-center gap-1 text-xs text-violet-700 hover:text-violet-800 border border-violet-200 bg-white hover:bg-violet-50 px-2.5 py-1 rounded-lg transition-colors"
              >
                <MessageSquare size={12} />
                Ask AI
              </button>
            )}
            {helpContent && (
              <button
                type="button"
                onClick={() => setShowHelp(v => !v)}
                className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 border border-gray-200 bg-white hover:bg-gray-50 px-2 py-1 rounded-lg transition-colors"
              >
                <Info size={12} />
                {showHelp ? 'Hide Help' : 'Help'}
              </button>
            )}
            <StatusPill status={status} accentColor={accentColor} c={c} />
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="px-5 py-4">
        {!report && (
          <p className="text-sm text-gray-500 mb-4">{description}</p>
        )}
        {helpContent && showHelp && (
          <div className="mb-4 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-900 space-y-2">
            {helpContent}
          </div>
        )}
        {setupContent}

        {/* Running state */}
        {isRunning && (() => {
          const detail = report?.progress_detail || ''
          const match = detail.match(/(\d+)\/(\d+)/)
          const done = match ? parseInt(match[1]) : 0
          const total = match ? parseInt(match[2]) : 0
          const pct = total > 0 ? Math.round(done / total * 100) : 0
          const hasProgress = total > 0
          return (
            <div className="flex flex-col gap-2.5 py-3">
              <div className="flex items-center gap-3">
                <RefreshCw size={15} className="animate-spin text-gray-400 flex-shrink-0" />
                <span className="text-sm text-gray-700 flex-1 min-w-0 truncate">
                  {detail || 'Starting up - loading findings...'}
                </span>
                {onCancel && (
                  <button onClick={() => { if (window.confirm('Cancel this generation? Progress will be lost.')) onCancel() }}
                    className="flex-shrink-0 text-xs text-red-600 border border-red-200 bg-red-50 hover:bg-red-100 px-2.5 py-1 rounded-lg font-medium">
                    Cancel
                  </button>
                )}
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                  <div
                    className={`h-2 rounded-full transition-all duration-700 ${hasProgress ? 'bg-blue-500' : 'bg-blue-300 animate-pulse'}`}
                    style={{ width: hasProgress ? `${Math.max(pct, 3)}%` : '8%' }}
                  />
                </div>
                <span className="text-xs font-semibold text-blue-600 tabular-nums flex-shrink-0 w-9 text-right">
                  {hasProgress ? `${pct}%` : '--'}
                </span>
              </div>
              {hasProgress && (
                <p className="text-xs text-gray-400">{done} of {total} families complete - ~1-5 min each</p>
              )}
            </div>
          )
        })()}

        {/* Error / cancelled state */}
        {status === 'failed' && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 mb-2">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-red-700 font-medium mb-0.5">
                  {report?.error_message?.includes('interrupted') ? 'Interrupted by server restart' :
                   report?.error_message?.includes('Cancelled') ? 'Cancelled' : 'Generation failed'}
                </p>
                {report?.error_message && (
                  <p className="text-xs text-red-600">{report.error_message}</p>
                )}
                <p className="text-xs text-red-400 mt-1">Click Generate to retry, or Reset to clear this record entirely.</p>
              </div>
              {onReset && (
                <button
                  onClick={() => { if (window.confirm('Reset this report? The failed record will be deleted and you can start fresh.')) onReset() }}
                  className="flex-shrink-0 flex items-center gap-1 text-xs text-red-700 border border-red-300 bg-white hover:bg-red-100 px-2.5 py-1.5 rounded-lg font-medium transition-colors"
                  title="Delete this failed report and start fresh"
                >
                  <RotateCcw size={11} /> Reset
                </button>
              )}
            </div>
          </div>
        )}

        {/* Complete state â€” show content */}
        {status === 'complete' && detail?.content && (
          <div className="mb-4 max-h-[480px] overflow-y-auto">
            {renderContent(detail.content)}
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div className="px-5 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
        <div className="min-w-0 flex items-center gap-3">
          {report?.created_at && (
            <span className="text-xs text-gray-400">
              {new Date(report.created_at).toLocaleDateString()}
            </span>
          )}
          {report?.progress_detail && status === 'complete' && (
            <span className="text-xs text-emerald-600">{report.progress_detail}</span>
          )}
          {/* Clear button â€” visible on complete and failed reports, hidden while running */}
          {onReset && status !== 'failed' && (
            <button
              onClick={() => { if (window.confirm('Clear this report record? The record will be deleted. Any documents already generated remain in the library.')) onReset() }}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-red-500 transition-colors"
              title="Clear this report record"
            >
              <RotateCcw size={11} /> Clear
            </button>
          )}
        </div>
        <div className="flex gap-2">
          {downloads.map((d) => (
            <button key={d.url} onClick={() => window.open(d.url, '_blank')}
              className="flex items-center gap-1.5 text-xs border border-gray-300 text-gray-600 px-3 py-1.5 rounded-lg hover:bg-white">
              <Download size={12} /> {d.label}
            </button>
          ))}
          <button
            onClick={onGenerate}
            disabled={isGenerating || isRunning}
            className={`flex items-center gap-1.5 text-xs text-white px-3 py-1.5 rounded-lg disabled:opacity-50 ${c.btn}`}>
            {isRunning ? <><RefreshCw size={11} className="animate-spin" /> Generating...</> :
             status === 'complete' ? <><RefreshCw size={11} /> Regenerate</> :
             <><Wrench size={11} /> Generate</>}
          </button>
        </div>
      </div>
    </div>
  )
}

function StatusPill({ status, c }) {
  if (!status) return null
  const configs = {
    pending: { label: 'Queued', cls: 'bg-gray-100 text-gray-600' },
    running: { label: 'Generating...', cls: 'bg-blue-100 text-blue-700 animate-pulse' },
    complete: { label: 'Ready', cls: `${c?.badge || 'bg-green-100 text-green-700'}` },
    failed: { label: 'Failed', cls: 'bg-red-100 text-red-700' },
  }
  const cfg = configs[status] || configs.pending
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0 ${cfg.cls}`}>{cfg.label}</span>
}

function GuideContent({ content }) {
  const [expanded, setExpanded] = useState({})
  const toggle = (key) => setExpanded(e => ({ ...e, [key]: !e[key] }))
  const detectedTools = content.detected_tools || []
  const systemKnowledge = content.system_knowledge || {}
  const collectionPlaybook = content.collection_playbook || []
  const playbookSummary = content.playbook_summary || {}

  return (
    <div className="space-y-3">
      {(detectedTools.length > 0 || systemKnowledge.assertion_count) && (
        <div className="bg-sky-50 border border-sky-200 rounded-lg px-4 py-3">
          <p className="text-sm font-semibold text-sky-900 mb-0.5">Detected stack for real remediation</p>
          <p className="text-xs text-sky-700">
            Tools detected: {detectedTools.map((tool) => tool.tool_name).slice(0, 8).join(', ') || 'None yet'}.
            The guidance below points the assessor to real collection locations instead of invented evidence.
          </p>
        </div>
      )}
      {collectionPlaybook.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Collection Playbook</p>
          <p className="text-sm text-gray-800">{collectionPlaybook.length} tool-aware collection steps prepared</p>
          <p className="text-xs text-gray-500 mt-1">
            Open Architecture &amp; Tools from the project page to confirm the detected stack and re-search missing components.
          </p>
          <p className="text-xs text-gray-500 mt-1">
            Detected-tool guidance: {playbookSummary.detected_tool_entries || 0}
            {' '}| Generic fallback guidance: {playbookSummary.generic_entries || 0}
          </p>
        </div>
      )}
      {(content.sections || []).map((section) => (
        <div key={section.family} className="border border-gray-200 rounded-lg overflow-hidden">
          <button
            onClick={() => toggle(section.family)}
            className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-bold text-gray-500">{section.family}</span>
              <span className="text-sm font-semibold text-gray-800">{section.family_title}</span>
              <span className="text-xs bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded font-medium">
                {section.control_count} control{section.control_count !== 1 ? 's' : ''}
              </span>
            </div>
            {expanded[section.family] ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          {expanded[section.family] && (
            <div className="divide-y divide-gray-100">
              {(section.actions || []).map((action, i) => (
                <div key={i} className="px-4 py-3">
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-blue-700">{action.control_id}</span>
                      <span className="text-xs text-gray-500 truncate max-w-[300px]">{action.gap}</span>
                    </div>
                    <div className="flex gap-1.5 flex-shrink-0">
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">{action.responsible}</span>
                      <span className="text-xs bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded">{action.effort}</span>
                    </div>
                  </div>
                  <div className="mb-1.5">
                    <span className="text-sm font-medium text-gray-700">Action: </span>
                    <TextBlock text={action.action} className="text-sm text-gray-800 inline" />
                  </div>
                  {action.success_criteria && (
                    <div className="mb-1.5">
                      <span className="text-xs font-medium text-gray-500">Done when: </span>
                      <TextBlock text={action.success_criteria} className="text-xs text-gray-500 inline" />
                    </div>
                  )}
                  {action.template_language && (
                    <div className="bg-blue-50 border border-blue-100 rounded px-3 py-2 mt-1.5">
                      <p className="text-xs font-semibold text-blue-700 mb-1">Template language</p>
                      <TextBlock text={action.template_language} className="text-xs text-blue-900 italic" />
                    </div>
                  )}
                  {action.collection_guidance?.length > 0 && (
                    <div className="bg-sky-50 border border-sky-100 rounded px-3 py-2 mt-1.5">
                      <p className="text-xs font-semibold text-sky-700 mb-1">Where to collect real evidence</p>
                      <div className="space-y-2">
                        {action.collection_guidance.slice(0, 2).map((item, idx) => (
                          <div key={idx} className="text-xs text-sky-900">
                            <p className="font-medium">
                              {item.tool_name || item.domain}
                              {!item.detected ? ' (review needed)' : ''}
                            </p>
                            <p className="mt-0.5">Go to: {(item.where_to_go || []).join(' | ')}</p>
                            <p className="mt-0.5">Collect: {(item.collect || []).join(' | ')}</p>
                            <p className="mt-0.5 text-sky-700">Look for: {(item.look_for || []).join(' | ')}</p>
                            {item.collection_steps?.length > 0 && (
                              <div className="mt-1.5">
                                <p className="font-medium text-sky-800">Operator steps</p>
                                <div className="mt-1 space-y-0.5">
                                  {item.collection_steps.slice(0, 3).map((step, stepIdx) => (
                                    <p key={stepIdx}>{stepIdx + 1}. {step}</p>
                                  ))}
                                </div>
                              </div>
                            )}
                            {item.evidence_examples?.length > 0 && (
                              <p className="mt-1.5 text-sky-700">
                                Examples: {item.evidence_examples.slice(0, 3).join(' | ')}
                              </p>
                            )}
                            {!item.detected && item.search_terms?.length > 0 && (
                              <p className="mt-1.5 text-sky-700">
                                Search docs for: {item.search_terms.slice(0, 4).join(' | ')}
                              </p>
                            )}
                            {item.missing_artifact_signal && (
                              <p className="mt-1.5 text-sky-700">
                                Missing signal: {item.missing_artifact_signal}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

const ARTIFACT_TYPE_LABELS = {
  policy_procedure:   { label: 'Policy & Procedure', color: 'bg-blue-100 text-blue-700' },
  completed_form:     { label: 'Completed Form',      color: 'bg-purple-100 text-purple-700' },
  ssp_narrative:      { label: 'SSP Narrative',       color: 'bg-indigo-100 text-indigo-700' },
  procedure:          { label: 'Procedure',            color: 'bg-teal-100 text-teal-700' },
  evidence_template:  { label: 'Technical Evidence',  color: 'bg-amber-100 text-amber-700' },
  technical_artifact: { label: 'Technical Evidence',  color: 'bg-amber-100 text-amber-700' },
  policy:             { label: 'Policy',              color: 'bg-sky-100 text-sky-700' },
  agreement_template: { label: 'Agreement Template',  color: 'bg-rose-100 text-rose-700' },
}

function formatSeconds(value) {
  const secs = Number(value)
  if (!Number.isFinite(secs) || secs < 0) return 'n/a'
  if (secs < 60) return `${secs.toFixed(1)}s`
  return `${(secs / 60).toFixed(1)}m`
}

function ArtifactsContent({ content }) {
  const [expanded, setExpanded] = useState({})
  const toggle = (key) => setExpanded(e => ({ ...e, [key]: !e[key] }))
  const blueprint = content.blueprint || {}
  const validation = content.validation || {}
  const artifactValidation = content.artifact_validation || {}
  const systemKnowledge = content.system_knowledge || {}
  const timing = content.timing || {}

  // Group artifacts by family
  const byFamily = {}
  for (const artifact of (content.artifacts || [])) {
    const fam = artifact.family || 'Other'
    if (!byFamily[fam]) byFamily[fam] = { family: fam, family_title: artifact.family_title, artifacts: [] }
    byFamily[fam].artifacts.push(artifact)
  }
  const families = Object.values(byFamily).sort((a, b) => a.family.localeCompare(b.family))

  const totalDocs = content.summary?.documents_created || (content.artifacts || []).length

  return (
    <div className="space-y-3">
      <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3">
        <p className="text-sm font-semibold text-emerald-800 mb-0.5">
          {totalDocs} evidence artifact{totalDocs !== 1 ? 's' : ''} generated and added to your document library
        </p>
        <p className="text-xs text-emerald-700">
          Each document was tailored to close specific assessment gaps. Review, customize, and re-run the assessment to validate compliance.
          Documents are already queued for indexing - they will appear as evidence in future assessments automatically.
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Artifact Blueprint</p>
          <p className="text-sm text-gray-800">{blueprint.summary?.bundle_count || 0} planned remediation bundles</p>
          <p className="text-xs text-gray-500 mt-1">Package style: {blueprint.summary?.package_style || content.config?.package_style || 'standard'}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Validation</p>
          <p className="text-sm text-gray-800">{validation.controls_addressed || 0} controls across {validation.families_covered?.length || 0} families</p>
          <p className="text-xs text-gray-500 mt-1">Status: {validation.status || 'pending'}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Artifact Readiness</p>
          <p className="text-sm text-gray-800">{artifactValidation.retrieval_viable || 0} of {artifactValidation.document_count || 0} docs ready</p>
          <p className="text-xs text-gray-500 mt-1">Viability: {artifactValidation.package_viability?.viability_score ?? 0}%</p>
          <p className="text-xs text-gray-500 mt-1">Runtime: {formatSeconds(timing.total_secs)}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">System Knowledge</p>
          <p className="text-sm text-gray-800">{systemKnowledge.assertion_count || 0} assertions</p>
          <p className="text-xs text-gray-500 mt-1">Tools: {(systemKnowledge.tools || []).length || 0}</p>
        </div>
      </div>
      {(systemKnowledge.tool_count || systemKnowledge.assertion_count) ? (
        <div className="bg-sky-50 border border-sky-200 rounded-lg px-4 py-3 text-xs text-sky-800">
          Tools detected: {(systemKnowledge.tools || []).map((t) => t.tool_name).slice(0, 6).join(', ') || 'None yet'}
        </div>
      ) : null}
      {families.map((fam) => {
        const key = fam.family
        const isOpen = expanded[key]
        return (
          <div key={key} className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              onClick={() => toggle(key)}
              className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold text-gray-500 w-8">{fam.family}</span>
                <span className="text-sm font-semibold text-gray-800">{fam.family_title}</span>
                <span className="text-xs bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded font-medium">
                  {fam.artifacts.length} doc{fam.artifacts.length !== 1 ? 's' : ''}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">
                  {[...new Set(fam.artifacts.flatMap(a => a.controls_addressed || []))].slice(0, 5).join(', ')}
                  {[...new Set(fam.artifacts.flatMap(a => a.controls_addressed || []))].length > 5 ? '...' : ''}
                </span>
                {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </div>
            </button>
            {isOpen && (
              <div className="divide-y divide-gray-100">
                {fam.artifacts.map((artifact, idx) => {
                  const typeInfo = ARTIFACT_TYPE_LABELS[artifact.artifact_type] || { label: artifact.artifact_type, color: 'bg-gray-100 text-gray-600' }
                  return (
                    <div key={idx} className="px-4 py-3 flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium text-gray-800">{artifact.title}</span>
                          <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${typeInfo.color}`}>
                            {typeInfo.label}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 mt-1">
                          <span className="text-xs text-gray-400">
                            {(artifact.controls_addressed || []).join(', ')}
                          </span>
                          {artifact.doc_id && (
                            <span className="text-xs text-emerald-600 font-medium">Saved to document library</span>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

const TEST_DATASET_TYPE_LABELS = {
  policy:            { label: 'Policy',                  color: 'bg-blue-100 text-blue-700' },
  procedure:         { label: 'Procedure',               color: 'bg-teal-100 text-teal-700' },
  technical_artifact:{ label: 'Technical Artifact',      color: 'bg-orange-100 text-orange-700' },
  ssp_narrative:     { label: 'SSP Narrative',           color: 'bg-indigo-100 text-indigo-700' },
  training_record:   { label: 'Training Record',         color: 'bg-amber-100 text-amber-700' },
}

function TestDatasetContent({ content }) {
  const [expanded, setExpanded] = useState({})
  const toggle = (key) => setExpanded(e => ({ ...e, [key]: !e[key] }))

  const summary = content.summary || {}
  const artifacts = content.artifacts || []
  const blueprint = content.blueprint || {}
  const validation = content.validation || {}
  const artifactValidation = content.artifact_validation || {}
  const systemKnowledge = content.system_knowledge || {}
  const timing = content.timing || {}
  const expected = content.expected_outcomes?.summary || {}
  const benchmark = content.benchmark

  // Group by family
  const byFamily = {}
  for (const a of artifacts) {
    const fam = a.family || 'Other'
    if (!byFamily[fam]) byFamily[fam] = []
    byFamily[fam].push(a)
  }
  const families = Object.keys(byFamily).sort()

  // Count by document type
  const typeCounts = artifacts.reduce((acc, a) => {
    const t = a.artifact_type || 'unknown'
    acc[t] = (acc[t] || 0) + 1
    return acc
  }, {})

  return (
    <div className="space-y-3">
      {/* Summary banner */}
      <div className="bg-violet-50 border border-violet-200 rounded-lg px-4 py-3">
        <p className="text-sm font-semibold text-violet-900 mb-1">
          {summary.documents_created || 0} test dataset documents generated -
          covering {summary.controls_addressed || 0} of {summary.total_controls || 0} controls
          ({summary.impact_baseline || ''} baseline)
        </p>
        <div className="flex flex-wrap gap-1.5 mt-2">
          {Object.entries(typeCounts).map(([type, count]) => {
            const info = TEST_DATASET_TYPE_LABELS[type] || { label: type, color: 'bg-gray-100 text-gray-600' }
            return (
              <span key={type} className={`text-xs px-2 py-0.5 rounded-full font-medium ${info.color}`}>
                {count} {info.label}
              </span>
            )
          })}
        </div>
        <p className="text-xs text-violet-700 mt-2">
          All documents are saved to your project library and queued for indexing.
          Run a new assessment once indexing completes to validate 100% compliance detection.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Blueprint</p>
          <p className="text-sm text-gray-800">{blueprint.summary?.bundle_count || 0} package components</p>
          <p className="text-xs text-gray-500 mt-1">Style: {summary.package_style || content.config?.package_style || 'standard'}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Expected Outcomes</p>
          <p className="text-xs text-gray-600">Compliant: {expected.compliant || 0}</p>
          <p className="text-xs text-gray-600 mt-1">Partial: {expected.partially_compliant || 0}</p>
          <p className="text-xs text-gray-600 mt-1">Non-Compliant: {expected.non_compliant || 0}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Validation</p>
          <p className="text-sm text-gray-800">{validation.bundle_count || 0} bundles across {validation.families_covered?.length || 0} families</p>
          <p className="text-xs text-gray-500 mt-1">Status: {validation.status || 'pending'}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Artifact Readiness</p>
          <p className="text-sm text-gray-800">{artifactValidation.retrieval_viable || 0} of {artifactValidation.document_count || 0} docs ready</p>
          <p className="text-xs text-gray-500 mt-1">Viability: {artifactValidation.package_viability?.viability_score ?? 0}%</p>
          <p className="text-xs text-gray-500 mt-1">Runtime: {formatSeconds(timing.total_secs)}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">System Knowledge</p>
          <p className="text-sm text-gray-800">{systemKnowledge.assertion_count || 0} assertions</p>
          <p className="text-xs text-gray-500 mt-1">Tools: {(systemKnowledge.tools || []).length || 0}</p>
        </div>
      </div>
      {benchmark && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3">
          <p className="text-sm font-semibold text-emerald-800 mb-0.5">Benchmark Comparison</p>
          <p className="text-xs text-emerald-700">
            Assessment #{benchmark.assessment_id} matched {benchmark.match_pct}% of the intended control outcomes.
            {' '}Mismatches: {benchmark.mismatch_count || 0}.
          </p>
        </div>
      )}

      {/* Per-family accordion */}
      {families.map(fam => {
        const famArtifacts = byFamily[fam]
        const isOpen = expanded[fam]
        return (
          <div key={fam} className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              onClick={() => toggle(fam)}
              className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold text-gray-500 w-8">{fam}</span>
                <span className="text-xs bg-violet-100 text-violet-700 px-1.5 py-0.5 rounded font-medium">
                  {famArtifacts.length} doc{famArtifacts.length !== 1 ? 's' : ''}
                </span>
              </div>
              {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {isOpen && (
              <div className="divide-y divide-gray-100">
                {famArtifacts.map((a, idx) => {
                  const typeInfo = TEST_DATASET_TYPE_LABELS[a.artifact_type] || { label: a.artifact_type || 'Document', color: 'bg-gray-100 text-gray-600' }
                  return (
                    <div key={idx} className="px-4 py-2.5 flex items-center gap-3">
                      <span className="font-mono text-xs font-bold text-gray-400 w-16 shrink-0">{a.control_id}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-gray-800 truncate">{a.title}</p>
                      </div>
                      <span className={`text-xs px-1.5 py-0.5 rounded font-medium shrink-0 ${typeInfo.color}`}>
                        {typeInfo.label}
                      </span>
                      {a.doc_id && (
                        <span className="text-xs text-emerald-600 font-medium shrink-0">Indexed</span>
                      )}
                      {a.error && (
                        <span className="text-xs text-red-500 font-medium shrink-0">Error</span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// â”€â”€ Keyboard Review Grid â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Spreadsheet navigation: â†‘â†“ = rows (controls), â†â†’ = columns (RMF functions), Enter = act

// Column definitions â€” id must match handler switch below
const REVIEW_COLS = [
  { id: 'status',        label: 'Status',        width: 'w-36' },
  { id: 'applicability', label: 'Applicability',  width: 'w-36' },
  { id: 'satisfied',     label: 'Satisfied',      width: 'w-28' },
  { id: 'risk',          label: 'Risk Accepted',  width: 'w-32' },
  { id: 'notes',         label: 'Notes',          width: 'w-56' },
]

// Cycle order for applicability column
const APP_CYCLE = [null, 'not_applicable', 'applicable', 'inherited']

function KeyboardReview({ findings, overrideMap, onUpsert, projectId, assessmentId, onFindingUpdate, docMap }) {
  const sorted = useMemo(() => [...findings].sort(sortByControlId), [findings])
  const [row, setRow] = useState(0)          // which control
  const [col, setCol] = useState(0)          // which column (0=status readonly, 1-4 actionable)
  const [modal, setModal] = useState(null)   // { type, cid, title }
  const [modalText, setModalText] = useState('')
  const [riskExpiry, setRiskExpiry] = useState('')
  const [manualStatus, setManualStatus] = useState(null)  // selected status for manual override modal
  const gridRef = useRef(null)
  const modalInputRef = useRef(null)

  const current = sorted[row] || null
  const override = current ? overrideMap[current.control_id] : null

  useEffect(() => { gridRef.current?.focus() }, [])

  const openModal = useCallback((type) => {
    if (!current) return
    const ov = overrideMap[current.control_id]
    // Pre-fill textarea with existing saved content for this field
    const prefill = {
      notes:          current.notes || '',
      na:             ov?.applicability_rationale || '',
      applicable:     ov?.applicability_rationale || '',
      inherited:      ov?.applicability_rationale || '',
      satisfied:      ov?.satisfied_rationale || '',
      risk:           ov?.risk_acceptance_rationale || '',
      manual_status:  ov?.manual_status_rationale || '',
    }
    setModalText(prefill[type] ?? '')
    setRiskExpiry(ov?.risk_acceptance_expiry ? new Date(ov.risk_acceptance_expiry).toISOString().split('T')[0] : '')
    if (type === 'manual_status') {
      setManualStatus(ov?.manual_status || current.status)
    }
    setModal({ type, cid: current.control_id, title: current.control_title })
    setTimeout(() => modalInputRef.current?.focus(), 50)
  }, [current, overrideMap])

  const closeModal = useCallback(() => {
    setModal(null)
    setTimeout(() => gridRef.current?.focus(), 50)
  }, [])

  const submitModal = useCallback(() => {
    if (!modal) return
    const { type, cid } = modal
    if (type === 'na')        onUpsert(cid, { applicability: 'not_applicable', applicability_rationale: modalText || null })
    if (type === 'applicable') onUpsert(cid, { applicability: 'applicable',    applicability_rationale: modalText || null })
    if (type === 'inherited')  onUpsert(cid, { applicability: 'inherited',     applicability_rationale: modalText || null })
    if (type === 'satisfied')  onUpsert(cid, { satisfied: true,  satisfied_rationale: modalText || null })
    if (type === 'unsat')      onUpsert(cid, { satisfied: false, satisfied_rationale: null })
    if (type === 'risk')       onUpsert(cid, { risk_accepted: true,  risk_acceptance_rationale: modalText || null, risk_acceptance_expiry: riskExpiry || null })
    if (type === 'unrisk')     onUpsert(cid, { risk_accepted: false, risk_acceptance_rationale: null })
    if (type === 'manual_status' && manualStatus) {
      const currentFinding = sorted.find(f => f.control_id === cid)
      const isUpgrade = STATUS_RANK[manualStatus] > STATUS_RANK[currentFinding?.status || 'non_compliant']
      if (isUpgrade && !modalText.trim()) {
        alert('Evidence is required when upgrading a status determination.')
        return
      }
      onUpsert(cid, { manual_status: manualStatus, manual_status_rationale: modalText.trim() || null })
    }
    if (type === 'clear_manual_status') onUpsert(cid, { clear_manual_status: true })
    if (type === 'notes') {
      const f = sorted.find(sf => sf.control_id === cid)
      if (f) {
        api.patch(`/projects/${projectId}/assessments/${assessmentId}/findings/${f.id}/notes`, { notes: modalText.trim() || null })
          .then(() => onFindingUpdate())
          .catch(e => alert('Save failed: ' + (e.response?.data?.detail || e.message)))
      }
    }
    closeModal()
  }, [modal, modalText, riskExpiry, onUpsert, closeModal])

  // What "Enter" does for each column on the current control
  const activateCol = useCallback((colIdx) => {
    if (!current) return
    const ov = overrideMap[current.control_id]
    switch (colIdx) {
      case 0: // Status â€” open manual status override modal
        openModal('manual_status')
        break
      case 1: { // Applicability â€” toggle N/A â†” Applicable with rationale modal
        const cur = ov?.applicability ?? null
        if (cur === 'not_applicable') openModal('applicable')
        else openModal('na')
        break
      }
      case 2: // Satisfied â€” toggle
        if (ov?.satisfied) openModal('unsat')
        else openModal('satisfied')
        break
      case 3: // Risk Accepted â€” toggle
        if (ov?.risk_accepted) openModal('unrisk')
        else openModal('risk')
        break
      case 4: // Notes â€” open notes modal
        openModal('notes')
        break
      default: break
    }
  }, [current, overrideMap, onUpsert, openModal])

  const handleKey = useCallback((e) => {
    if (modal) {
      if (e.key === 'Escape') { e.preventDefault(); closeModal() }
      if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); submitModal() }
      return
    }
    switch (e.key) {
      case 'ArrowUp':
        e.preventDefault()
        setRow(r => Math.max(0, r - 1))
        break
      case 'ArrowDown':
        e.preventDefault()
        setRow(r => Math.min(sorted.length - 1, r + 1))
        break
      case 'ArrowLeft':
        e.preventDefault()
        setCol(c => Math.max(0, c - 1))
        break
      case 'ArrowRight':
        e.preventDefault()
        setCol(c => Math.min(REVIEW_COLS.length - 1, c + 1))
        break
      case 'Enter':
        e.preventDefault()
        activateCol(col)
        break
      case 'Escape':
        e.preventDefault()
        break
      default: break
    }
  }, [modal, sorted.length, col, activateCol, closeModal, submitModal])

  // Cell value renderers â€” flex div cells for single-row layout
  const renderCell = (f, colIdx, isActiveRow, isActiveCell) => {
    const ov = overrideMap[f.control_id]
    const width = REVIEW_COLS[colIdx]?.width || 'w-28'
    const cellCls = `flex-shrink-0 ${width} px-3 py-2 text-xs text-center flex items-center justify-center
      ${isActiveCell ? 'ring-2 ring-inset ring-blue-500 bg-blue-100/60 rounded' : ''}`

    switch (colIdx) {
      case 0: // Status
        return (
          <div key={colIdx} className={cellCls}>
            <div className="flex flex-col items-center gap-0.5">
              <StatusBadge status={f.status} override={overrideMap[f.control_id]} />
              {overrideMap[f.control_id]?.manual_status && (
                <span className="text-[9px] bg-purple-100 text-purple-700 px-1 rounded font-semibold leading-none py-0.5">MANUAL</span>
              )}
            </div>
          </div>
        )
      case 1: { // Applicability
        const isNA = effectiveStatus(f.status, ov) === 'not_applicable'
        return (
          <div key={colIdx} className={cellCls}>
            <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
              isNA ? 'bg-slate-200 text-slate-700' : 'bg-green-100 text-green-800'
            }`}>
              {isNA ? 'N/A' : 'Applicable'}
            </span>
          </div>
        )
      }
      case 2: // Satisfied
        return (
          <div key={colIdx} className={cellCls}>
            {ov?.satisfied
              ? <span className="text-green-700 font-semibold text-xs">Yes</span>
              : <span className="text-gray-400 text-xs">-</span>}
          </div>
        )
      case 3: // Risk Accepted
        return (
          <div key={colIdx} className={cellCls}>
            {ov?.risk_accepted
              ? <span className="text-amber-700 font-semibold text-xs">Accepted</span>
              : <span className="text-gray-400 text-xs">-</span>}
          </div>
        )
      case 4: // Notes (truncated)
        return (
          <div key={colIdx} className={`flex-shrink-0 ${width} px-3 py-2 text-xs text-left flex items-center
            ${isActiveCell ? 'ring-2 ring-inset ring-blue-500 bg-blue-100/60 rounded' : ''}`}>
            <span className="block truncate text-gray-600">
              {f.notes
                ? f.notes.replace(/\\n/g, ' ').replace(/\n/g, ' ')
                : <span className="text-gray-300 italic">no notes</span>}
            </span>
          </div>
        )
      default: return <div key={colIdx} className={cellCls} />
    }
  }

  const modalConfig = {
    na:              { title: 'Mark Not Applicable',      label: 'Rationale (optional)',         btn: 'Confirm', color: 'bg-slate-600',   noText: false },
    applicable:      { title: 'Mark as Applicable',       label: 'Rationale (optional)',         btn: 'Confirm', color: 'bg-green-600',   noText: false },
    inherited:       { title: 'Mark as Inherited',        label: 'Provider / rationale (opt.)',  btn: 'Confirm', color: 'bg-indigo-600',  noText: false },
    satisfied:       { title: 'Mark as Satisfied',        label: 'Rationale',                    btn: 'Confirm', color: 'bg-green-700',   noText: false },
    unsat:           { title: 'Remove Satisfied Flag',    label: null,                           btn: 'Remove',  color: 'bg-red-500',     noText: true  },
    risk:            { title: 'Accept Risk',              label: 'Rationale',                    btn: 'Accept',  color: 'bg-amber-600',   noText: false },
    unrisk:          { title: 'Remove Risk Acceptance',   label: null,                           btn: 'Remove',  color: 'bg-red-500',     noText: true  },
    manual_status:   { title: 'Set Manual Status Override', label: null,                         btn: 'Set Override', color: 'bg-purple-700', noText: true },
    clear_manual_status: { title: 'Clear Manual Override', label: null,                         btn: 'Clear',   color: 'bg-red-600',     noText: true  },
    notes:           { title: 'Control Notes',             label: 'Notes',                      btn: 'Save',    color: 'bg-blue-600',    noText: false },
  }
  const mcfg = modal ? modalConfig[modal.type] : null

  // For manual_status modal: is the selected status an upgrade?
  const manualIsUpgrade = modal?.type === 'manual_status' && manualStatus &&
    STATUS_RANK[manualStatus] > STATUS_RANK[sorted.find(f => f.control_id === modal.cid)?.status || 'non_compliant']

  return (
    <div className="flex flex-col gap-2" style={{ height: 'calc(100vh - 185px)', minHeight: 400 }}>

      {/* Single-row focus control â€” changes on â†‘â†“ */}
      <div
        ref={gridRef}
        tabIndex={0}
        onKeyDown={handleKey}
        className="outline-none rounded-xl border border-gray-200 bg-white shrink-0 overflow-hidden"
      >
        {/* Column headers */}
        <div className="flex items-center bg-gray-50 border-b border-gray-200 px-3 py-1.5">
          <span className="text-xs font-semibold text-gray-500 flex-1 min-w-0">
            Control
            <span className="ml-2 font-normal text-gray-400">{row + 1} / {sorted.length}</span>
          </span>
          {REVIEW_COLS.map((c, ci) => (
            <span key={c.id}
              className={`text-xs font-semibold text-center flex-shrink-0 ${c.width}
                ${ci === col ? 'text-blue-700' : 'text-gray-500'}`}>
              {c.label}
              {ci === col && <span className="ml-1 text-blue-400">^</span>}
            </span>
          ))}
        </div>

        {/* Current control row */}
        {current && (
          <div className="flex items-center bg-blue-50 px-3 py-2 gap-0">
            {/* Control ID + title */}
            <div className="flex items-center gap-2 flex-1 min-w-0">
              <span className="inline-block w-1 h-4 bg-blue-600 rounded-full flex-shrink-0" />
              <span className="flex items-center gap-1.5 flex-shrink-0">
                <span className="font-mono text-sm font-bold text-blue-700">{current.control_id}</span>
                <ControlReferenceButton controlId={current.control_id} iconOnly />
              </span>
              <OverrideIndicator override={overrideMap[current.control_id]} />
              <span className="text-sm text-gray-600 truncate">{current.control_title}</span>
            </div>
            {/* Action cells */}
            {REVIEW_COLS.map((_, ci) => renderCell(current, ci, true, ci === col))}
          </div>
        )}
      </div>

      {/* Detail panel â€” always shown for current control */}
      {current && (
        <div className="flex-1 min-h-0 overflow-y-auto bg-white border border-gray-200 rounded-xl px-4 pb-4">
          <div className="sticky top-0 bg-white pt-3 pb-2 border-b border-gray-100 mb-3 flex items-center gap-2">
            <span className="flex items-center gap-1.5">
              <span className="font-mono text-sm font-bold text-blue-700">{current.control_id}</span>
              <ControlReferenceButton controlId={current.control_id} iconOnly />
            </span>
            <StatusBadge status={current.status} override={override} />
            <OverrideBadges f={current} />
          </div>
          <ControlDetail
            f={current}
            projectId={projectId}
            assessmentId={assessmentId}
            onFindingUpdate={onFindingUpdate}
            override={override}
            onUpsert={(body) => onUpsert(current.control_id, body)}
            docMap={docMap}
          />
        </div>
      )}

      {/* Modal */}
      {modal && mcfg && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" onClick={closeModal}>
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4" onClick={e => e.stopPropagation()}>
            <h3 className="text-base font-bold text-gray-900 mb-1">{mcfg.title}</h3>
            <p className="text-xs text-gray-500 mb-4 font-mono">{modal.cid} - {modal.title}</p>

            {/* Manual status override â€” status picker */}
            {modal.type === 'manual_status' && (
              <>
                {override?.manual_status && (
                  <div className="mb-3 flex items-center justify-between p-2 rounded-lg bg-purple-50 border border-purple-200">
                    <span className="text-xs text-purple-700">Currently: <strong>{STATUS_LABELS[override.manual_status]}</strong> (manually set)</span>
                    <button onClick={() => { setModal({ type: 'clear_manual_status', cid: modal.cid, title: modal.title }) }}
                      className="text-xs text-red-600 hover:text-red-800 border border-red-200 px-2 py-0.5 rounded">Clear Override</button>
                  </div>
                )}
                <p className="text-xs font-semibold text-gray-600 mb-2">Select Status</p>
                <div className="grid grid-cols-2 gap-1.5 mb-3">
                  {Object.entries(STATUS_LABELS).map(([val, label]) => (
                    <button key={val} onClick={() => setManualStatus(val)}
                      className={`text-xs px-2 py-2 rounded border text-left transition-colors ${
                        manualStatus === val
                          ? 'border-purple-500 bg-purple-50 text-purple-800 font-semibold'
                          : 'border-gray-200 text-gray-600 hover:border-gray-300'
                      }`}>{label}</button>
                  ))}
                </div>
                {manualIsUpgrade && (
                  <div className="mb-2 p-2 rounded bg-amber-50 border border-amber-200">
                    <p className="text-xs text-amber-800 font-semibold">Upgrading status - evidence required</p>
                  </div>
                )}
                <label className="text-xs font-semibold text-gray-600 block mb-1">
                  {manualIsUpgrade ? 'Evidence (required)' : 'Rationale (optional)'}
                </label>
                <ExpandingTextarea
                  value={modalText}
                  onChange={e => setModalText(e.target.value)}
                  rows={3}
                  className={`w-full text-sm mb-3 ${
                    manualIsUpgrade && !modalText.trim() ? 'border-amber-300' : 'border-gray-200'
                  }`}
                  placeholder={manualIsUpgrade ? 'Cite specific evidence...' : 'Rationale or notes...'}
                  aiSection="manual_status_rationale"
                  aiPayload={{ control_id: modal.cid, control_title: modal.title, current_status: sorted.find(sf => sf.control_id === modal.cid)?.status, target_status: manualStatus }}
                />
              </>
            )}

            {modal.type === 'clear_manual_status' && (
              <p className="text-sm text-gray-600 mb-4">Remove the manual status override? The LLM will determine this control's status on the next assessment run.</p>
            )}

            {!mcfg.noText && modal.type !== 'manual_status' && (
              <>
                <label className="text-xs font-semibold text-gray-600 block mb-1">{mcfg.label}</label>
                <ExpandingTextarea
                  value={modalText}
                  onChange={e => setModalText(e.target.value)}
                  rows={3}
                  className="w-full text-sm mb-3"
                  placeholder="Enter rationale..."
                  aiSection={({ na: 'applicability_rationale', applicable: 'applicability_rationale', inherited: 'applicability_rationale', satisfied: 'satisfied_rationale', risk: 'risk_rationale', notes: 'control_notes' })[modal.type]}
                  aiPayload={{ control_id: modal.cid, control_title: modal.title, current_status: sorted.find(sf => sf.control_id === modal.cid)?.status, finding_id: modal.type === 'notes' ? sorted.find(sf => sf.control_id === modal.cid)?.id : undefined }}
                />
              </>
            )}
            {modal.type === 'risk' && (
              <div className="mb-3">
                <label className="text-xs font-semibold text-gray-600 block mb-1">Expiry date (optional)</label>
                <input type="date" value={riskExpiry} onChange={e => setRiskExpiry(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                />
              </div>
            )}
            <div className="flex items-center justify-between mt-2">
              {/* AI Draft â€” shown for text-entry modals that have an applicable section */}
              {(() => {
                const aiSectionMap = {
                  na: 'applicability_rationale',
                  applicable: 'applicability_rationale',
                  inherited: 'applicability_rationale',
                  satisfied: 'satisfied_rationale',
                  risk: 'risk_rationale',
                  notes: 'control_notes',
                  manual_status: 'manual_status_rationale',
                }
                const aiSection = aiSectionMap[modal.type]
                if (!aiSection || modal.type === 'unsat' || modal.type === 'unrisk' || modal.type === 'clear_manual_status') return <span />
                const f = sorted.find(sf => sf.control_id === modal.cid)
                const payload = {
                  control_id: modal.cid,
                  control_title: modal.title,
                  current_status: f?.status,
                  target_status: modal.type === 'manual_status' ? manualStatus : undefined,
                  gaps: f?.gaps,
                  implementation_statement: f?.implementation_statement,
                  finding_id: modal.type === 'notes' ? f?.id : undefined,
                }
                return (
                  <AiGenerateButton
                    section={aiSection}
                    payload={payload}
                    onGenerated={(text) => {
                      if (modal.type === 'manual_status') setModalText(text)
                      else setModalText(text)
                    }}
                  />
                )
              })()}
              <div className="flex gap-2">
                <button onClick={closeModal} className="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">Cancel (Esc)</button>
                <button onClick={submitModal} className={`px-4 py-2 text-sm rounded-lg text-white font-medium ${mcfg.color} hover:opacity-90`}>
                  {mcfg.btn} (Ctrl+Enter)
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function DeltaView({ findings }) {
  const withPrev = findings.filter(f => f.prev_status !== null && f.prev_status !== undefined)

  const newlyNA = withPrev.filter(f => f.status === 'not_applicable' && f.prev_status !== 'not_applicable')
  const nowApplicable = withPrev.filter(f => f.status !== 'not_applicable' && f.prev_status === 'not_applicable')
  const statusChanged = withPrev.filter(f => f.status !== f.prev_status && f.status !== 'not_applicable' && f.prev_status !== 'not_applicable')

  const totalChanged = newlyNA.length + nowApplicable.length + statusChanged.length

  if (withPrev.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl px-5 py-6 text-center">
        <p className="text-sm text-gray-400">No previous run exists to compare against.</p>
      </div>
    )
  }

  if (totalChanged === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl px-5 py-6 text-center">
        <p className="text-sm text-gray-500 font-medium">No status changes vs previous run</p>
        <p className="text-xs text-gray-400 mt-1">All {withPrev.length} controls returned the same status as the previous assessment.</p>
      </div>
    )
  }

  const Section = ({ title, items, color }) => items.length === 0 ? null : (
    <div className="mb-5">
      <p className={`text-xs font-semibold mb-2 ${color}`}>{title} ({items.length})</p>
      <div className="space-y-1">
        {items.map(f => (
          <div key={f.control_id} className="flex items-center gap-3 px-3 py-2 bg-white border border-gray-100 rounded-lg">
            <span className="flex items-center gap-1 w-24 flex-shrink-0">
              <span className="font-mono text-xs text-blue-700 font-semibold">{f.control_id}</span>
              <ControlReferenceButton controlId={f.control_id} iconOnly />
            </span>
            <span className="text-sm text-gray-700 flex-1 truncate">{f.control_title}</span>
            <div className="flex items-center gap-2 flex-shrink-0">
              <div className="w-32 flex justify-end"><StatusBadge status={f.prev_status} /></div>
                <span className="text-gray-300 text-sm">-&gt;</span>
              <div className="w-32 flex justify-start"><StatusBadge status={f.status} /></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl px-5 py-4">
      <Section title="Newly Not Applicable" items={newlyNA} color="text-gray-500" />
      <Section title="Now Applicable (was N/A)" items={nowApplicable} color="text-blue-600" />
      <Section title="Status Changed" items={statusChanged} color="text-amber-600" />
    </div>
  )
}

function ManualReviewModal({ finding, projectId, assessmentId, onClose, onSaved }) {
  const [form, setForm] = useState({
    status: finding.status !== 'not_reviewed' ? finding.status : 'non_compliant',
    implementation_statement: finding.implementation_statement?.replace(/^Assessment error:.*$/, '') || '',
    gaps: (finding.gaps || []).join('\n'),
    remediation_plan: finding.remediation_plan || '',
    confidence_score: finding.confidence_score || 0.5,
    reviewer_note: '',
  })
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      await api.patch(
        `/projects/${projectId}/assessments/${assessmentId}/findings/${finding.id}/resolve`,
        { ...form, gaps: form.gaps.split('\n').map(s => s.trim()).filter(Boolean), confidence_score: parseFloat(form.confidence_score) }
      )
      onSaved()
      onClose()
    } catch (e) {
      alert('Save failed: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <p className="text-xs text-gray-400 font-mono">{finding.control_id} - Manual Review</p>
            <h2 className="font-bold text-gray-900">{finding.control_title}</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl font-bold">Ã—</button>
        </div>
        <div className="overflow-y-auto flex-1 px-6 py-4 space-y-4">
          {finding.raw_llm_response && (
            <div>
              <p className="text-xs font-semibold text-gray-400 mb-1">RAW LLM OUTPUT (unparseable)</p>
              <pre className="text-xs bg-gray-50 border rounded p-3 overflow-x-auto whitespace-pre-wrap text-gray-600 max-h-40">
                {finding.raw_llm_response}
              </pre>
            </div>
          )}
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">STATUS</label>
            <select value={form.status} onChange={e => setForm({ ...form, status: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm">
              <option value="compliant">Compliant</option>
              <option value="partially_compliant">Partially Compliant</option>
              <option value="non_compliant">Non-Compliant</option>
              <option value="not_applicable">Not Applicable</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">IMPLEMENTATION STATEMENT</label>
            <ExpandingTextarea rows={4} value={form.implementation_statement} onChange={e => setForm({ ...form, implementation_statement: e.target.value })}
              className="w-full text-sm" placeholder="Describe how the control is implemented..." />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">GAPS (one per line)</label>
            <ExpandingTextarea rows={3} value={form.gaps} onChange={e => setForm({ ...form, gaps: e.target.value })}
              className="w-full text-sm font-mono" placeholder="Gap 1&#10;Gap 2" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">REMEDIATION PLAN</label>
            <ExpandingTextarea rows={3} value={form.remediation_plan} onChange={e => setForm({ ...form, remediation_plan: e.target.value })}
              className="w-full text-sm" placeholder="Specific steps to achieve compliance..." />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">CONFIDENCE: {Math.round(form.confidence_score * 100)}%</label>
            <input type="range" min={0} max={1} step={0.05} value={form.confidence_score}
              onChange={e => setForm({ ...form, confidence_score: e.target.value })} className="w-full" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">REVIEWER NOTE (optional)</label>
            <input type="text" value={form.reviewer_note} onChange={e => setForm({ ...form, reviewer_note: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="Reason for manual override..." />
          </div>
        </div>
        <div className="flex gap-3 px-6 py-4 border-t">
          <button onClick={onClose} className="flex-1 border rounded-lg py-2 text-sm hover:bg-gray-50">Cancel</button>
          <button onClick={save} disabled={saving} className="flex-1 bg-blue-700 text-white rounded-lg py-2 text-sm hover:bg-blue-800 disabled:opacity-50">
            {saving ? 'Saving...' : 'Save Override'}
          </button>
        </div>
      </div>
    </div>
  )
}

// â”€â”€ Dissent Chat Panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Slide-over panel: AI reviewer collaborates with analyst on a dissented verdict

const DISSENT_STATUS_BADGE = {
  compliant:            'bg-green-100 text-green-700',
  partially_compliant:  'bg-amber-100 text-amber-700',
  non_compliant:        'bg-red-100 text-red-700',
  not_applicable:       'bg-gray-100 text-gray-500',
}

function DissentChatPanel({ finding, onClose }) {
  const [messages, setMessages] = useState([])   // displayed messages (hidden opener excluded)
  const [input, setInput]       = useState('')
  const [loading, setLoading]   = useState(false)
  const messagesEndRef = useRef(null)
  const inputRef       = useRef(null)

  // Auto-scroll on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // On mount: auto-send a hidden opener so the AI introduces the context
  useEffect(() => {
    const init = async () => {
      setLoading(true)
      try {
        const res = await api.post('/ai-assist/dissent-chat', {
          finding_id: finding.id,
          // Hidden opener â€” not displayed as a user bubble
          messages: [{ role: 'user', content: "Please briefly introduce your dissent on this verdict: which specific objectives you challenged and what evidence would change the outcome." }],
        })
        // Store opener exchange in full history for follow-up context,
        // but only display the AI response (first visible message)
        setMessages([
          { role: 'user', content: '__opener__', hidden: true },
          { role: 'assistant', content: res.data.text },
        ])
      } catch {
        setMessages([{ role: 'assistant', content: 'Failed to load dissent context. Please type a question to begin.' }])
      } finally {
        setLoading(false)
        inputRef.current?.focus()
      }
    }
    init()
  }, [finding.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || loading) return
    const userMsg = { role: 'user', content: text }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setInput('')
    setLoading(true)
    try {
      // Send full history (excluding hidden opener display-only flag, keeping content)
      const apiHistory = newMessages.map(m => ({ role: m.role, content: m.content }))
      const res = await api.post('/ai-assist/dissent-chat', {
        finding_id: finding.id,
        messages: apiHistory,
      })
      setMessages([...newMessages, { role: 'assistant', content: res.data.text }])
    } catch (e) {
      setMessages([...newMessages, { role: 'assistant', content: `Error: ${e.response?.data?.detail || e.message}` }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [input, loading, messages, finding.id])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const badge = DISSENT_STATUS_BADGE[finding.status] || 'bg-gray-100 text-gray-600'

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />

      {/* Slide-over panel */}
      <div className="fixed right-0 top-0 bottom-0 w-[500px] max-w-full bg-white shadow-2xl z-50 flex flex-col">

        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b bg-violet-50 flex-shrink-0">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <Scale size={13} className="text-violet-600 flex-shrink-0" />
              <span className="text-xs font-semibold text-violet-600 uppercase tracking-wide">AI Dissent Review</span>
            </div>
            <p className="font-mono text-sm font-bold text-gray-900">{finding.control_id}</p>
            <p className="text-xs text-gray-600 mt-0.5 truncate">{finding.control_title}</p>
            <span className={`inline-block mt-1.5 text-xs px-2 py-0.5 rounded font-medium ${badge}`}>
              {finding.status.replace(/_/g, ' ')}
            </span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 ml-4 mt-0.5 flex-shrink-0">
            <X size={18} />
          </button>
        </div>

        {/* Challenge note â€” always visible as context */}
        <div className="px-5 py-3 bg-amber-50 border-b border-amber-200 flex-shrink-0">
          <p className="text-xs font-semibold text-amber-700 mb-1 uppercase tracking-wide">AI Challenge Note</p>
          <p className="text-xs text-amber-800 leading-relaxed">{finding.llm_challenge_note}</p>
        </div>

        {/* Messages area */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0">
          {messages.filter(m => !m.hidden).map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[88%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-violet-600 text-white rounded-br-md'
                  : 'bg-gray-100 text-gray-800 rounded-bl-md'
              }`}>
                {msg.content}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="bg-gray-100 rounded-2xl rounded-bl-md px-4 py-3">
                <div className="flex gap-1.5 items-center">
                  {[0, 150, 300].map(delay => (
                    <span key={delay} className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                      style={{ animationDelay: `${delay}ms` }} />
                  ))}
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="px-4 py-3 border-t bg-gray-50 flex-shrink-0">
          <div className="flex gap-2 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about evidence requirements, remediation steps, SSP language..."
              rows={2}
              disabled={loading}
              className="flex-1 border border-gray-200 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-violet-300 disabled:opacity-50 bg-white"
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || loading}
              className="flex-shrink-0 bg-violet-600 text-white p-2.5 rounded-xl hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Send size={16} />
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-1.5">Enter to send | Shift+Enter for new line</p>
        </div>
      </div>
    </>
  )
}

// â”€â”€ Dissent View â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// List of all findings where the AI challenged the code verdict

function DissentView({ findings, onDiscuss }) {
  const dissentFindings = useMemo(
    () => findings.filter(f => f.llm_challenge_note).sort(sortByControlId),
    [findings]
  )

  if (dissentFindings.length === 0) {
    return (
      <div className="text-center py-16">
        <Scale size={36} className="mx-auto mb-3 text-gray-200" />
        <p className="font-medium text-gray-500">No AI dissents in this assessment</p>
        <p className="text-sm text-gray-400 mt-1">
          AI dissents appear when the review model disputes the automated control verdict.
        </p>
      </div>
    )
  }

  const cfgMap = {
    compliant:           { border: 'border-green-200', bg: 'bg-green-50',  badge: 'bg-green-100 text-green-700',  label: 'Compliant' },
    partially_compliant: { border: 'border-amber-200', bg: 'bg-amber-50',  badge: 'bg-amber-100 text-amber-700',  label: 'Partially Compliant' },
    non_compliant:       { border: 'border-red-200',   bg: 'bg-red-50',    badge: 'bg-red-100 text-red-700',      label: 'Non-Compliant' },
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 mb-1">
        <Scale size={18} className="text-violet-600 flex-shrink-0" />
        <div>
          <h2 className="text-sm font-bold text-gray-900">
            AI Dissents - {dissentFindings.length} finding{dissentFindings.length !== 1 ? 's' : ''}
          </h2>
          <p className="text-xs text-gray-500">
            The assessment AI registered dissents against these verdicts during secondary review.
            The code verdict stands - use Discuss to collaborate and decide whether to override.
          </p>
        </div>
      </div>

      {dissentFindings.map(f => {
        const cfg = cfgMap[f.status] || { border: 'border-gray-200', bg: 'bg-gray-50', badge: 'bg-gray-100 text-gray-700', label: f.status }
        return (
          <div key={f.id} className={`border rounded-xl p-4 ${cfg.border} ${cfg.bg}`}>
            {/* Control header */}
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="flex items-center gap-1.5">
                    <span className="font-mono text-sm font-bold text-gray-900">{f.control_id}</span>
                    <ControlReferenceButton controlId={f.control_id} iconOnly />
                    <button
                      type="button"
                      onClick={() => onDiscuss(f)}
                      className="text-violet-600 hover:text-violet-800"
                      title="Ask AI about this control"
                    >
                      <MessageSquare size={12} />
                    </button>
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${cfg.badge}`}>{cfg.label}</span>
                  {f.confidence_score != null && (
                    <span className="text-xs text-gray-500">{Math.round(f.confidence_score * 100)}% confidence</span>
                  )}
                  {f.nist_determination && (
                    <span className="text-xs text-gray-400 font-mono">
                      {f.nist_determination.abbreviation}
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-600 mt-0.5">{f.control_title}</p>
              </div>
              <button
                onClick={() => onDiscuss(f)}
                className="flex-shrink-0 flex items-center gap-1.5 bg-violet-600 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-violet-700 transition-colors font-medium"
              >
                <MessageSquare size={12} />
                Discuss
              </button>
            </div>

            {/* Challenge note */}
            <div className="mt-3 p-3 bg-white rounded-lg border border-amber-200">
              <p className="text-xs font-semibold text-amber-600 mb-1 uppercase tracking-wide">AI Challenge Note</p>
              <p className="text-xs text-gray-700 leading-relaxed">{f.llm_challenge_note}</p>
            </div>

            {/* Gaps summary */}
            {f.gaps && f.gaps.length > 0 && (
              <div className="mt-2.5">
                <p className="text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">Identified Gaps</p>
                <ul className="space-y-0.5">
                  {f.gaps.slice(0, 3).map((g, i) => (
                    <li key={i} className="flex gap-1.5 text-xs text-gray-600">
                      <span className="text-gray-400 flex-shrink-0 mt-px">*</span>
                      <span>{g}</span>
                    </li>
                  ))}
                  {f.gaps.length > 3 && (
                    <li className="text-xs text-gray-400 ml-3.5">+{f.gaps.length - 3} more gap{f.gaps.length - 3 !== 1 ? 's' : ''}</li>
                  )}
                </ul>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function AssessmentTabButton({ active, onClick, icon: Icon, label, count = null }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition-colors ${
        active
          ? 'border-blue-700 bg-blue-700 text-white shadow-sm'
          : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
      }`}
    >
      {Icon && <Icon size={15} />}
      <span>{label}</span>
      {count !== null && count !== undefined && (
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${active ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-600'}`}>
          {count}
        </span>
      )}
    </button>
  )
}

function PlainStatusPill({ status, controlsComplete = 0, controlsTotal = 0 }) {
  const total = Number(controlsTotal || 0)
  const complete = total > 0 ? Math.min(Number(controlsComplete || 0), total) : Number(controlsComplete || 0)
  const cfg = {
    pending: ['Queued', 'bg-slate-100 text-slate-700 border-slate-200'],
    running: ['Running', 'bg-blue-100 text-blue-700 border-blue-200'],
    paused: ['Paused', 'bg-amber-100 text-amber-700 border-amber-200'],
    complete: ['Complete', 'bg-emerald-100 text-emerald-700 border-emerald-200'],
    failed: ['Failed', 'bg-red-100 text-red-700 border-red-200'],
  }[status] || [titleCaseLabel(status || 'pending'), 'bg-slate-100 text-slate-700 border-slate-200']
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${cfg[1]}`}>
      <span>{cfg[0]}</span>
      {total > 0 && <span className="opacity-80">{complete}/{total}</span>}
    </span>
  )
}

function SelectedControlPanel({
  finding,
  override,
  projectId,
  assessmentId,
  onFindingUpdate,
  onUpsert,
  docMap,
  onManualReview,
  onDiscuss,
  onClose,
}) {
  const qc = useQueryClient()
  const [drawerView, setDrawerView] = useState('summary')
  const selectedControlId = finding?.control_id || ''

  useEffect(() => {
    setDrawerView('summary')
  }, [selectedControlId])
  const { data: closureGuidance, isLoading: guidanceLoading } = useQuery({
    queryKey: ['closure-guidance', projectId, assessmentId, selectedControlId],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/closure/controls/${encodeURIComponent(selectedControlId)}/guidance`).then(r => r.data),
    enabled: !!selectedControlId,
  })
  const { data: draftPackage, isLoading: draftPackageLoading } = useQuery({
    queryKey: ['control-draft-package', projectId, assessmentId, selectedControlId],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/closure/controls/${encodeURIComponent(selectedControlId)}/draft-package`).then(r => r.data),
    enabled: !!selectedControlId,
  })
  const generateDraftPackage = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/assessments/${assessmentId}/closure/controls/${encodeURIComponent(selectedControlId)}/draft-package`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['control-draft-package', projectId, assessmentId, selectedControlId] })
      qc.invalidateQueries({ queryKey: ['draft-package-report', assessmentId] })
    },
  })
  if (!finding) {
    return null
  }

  const displayStatus = effectiveStatus(finding.status, override)
  const evidenceCount = Array.isArray(finding.evidence_citations) ? finding.evidence_citations.length : 0
  const gapCount = Array.isArray(finding.gaps) ? finding.gaps.length : 0
  const normalizedGaps = Array.isArray(finding.gaps) ? finding.gaps.map((gap) => String(gap)) : []
  const decisionSummary = cleanFindingDetail(finding.implementation_statement)
    || cleanFindingDetail(finding.notes)
    || cleanFindingDetail(finding.llm_challenge_note)
    || 'The assessment recorded a determination for this control. Use the evidence section below to inspect the supporting record and decide whether follow-up is needed.'
  const objectiveContracts = Array.isArray(closureGuidance?.objective_contracts) ? closureGuidance.objective_contracts : []
  const recommendedArtifactTypes = Array.isArray(closureGuidance?.recommended_artifact_types) ? closureGuidance.recommended_artifact_types : []
  const collectionGuidanceItems = Array.isArray(closureGuidance?.collection_guidance) ? closureGuidance.collection_guidance : []
  const sharedRemediationPlan = closureGuidance?.remediation_plan ? String(closureGuidance.remediation_plan) : ''
  const findingControlIdNormalized = normalizeIdentifier(finding.control_id)
  const detectedCollectionGuidanceItems = collectionGuidanceItems.filter((item) => item?.detected)
  const fallbackCollectionGuidanceItems = collectionGuidanceItems.filter((item) => !item?.detected)
  const fallbackDomains = [...new Set(fallbackCollectionGuidanceItems.map((item) => String(item.domain || '').replace(/_/g, ' ')).filter(Boolean))]
  const fallbackCollect = [...new Set(fallbackCollectionGuidanceItems.flatMap((item) => item.collect || []).filter(Boolean))].slice(0, 4)
  const fallbackLookFor = [...new Set(fallbackCollectionGuidanceItems.flatMap((item) => item.look_for || []).filter(Boolean))].slice(0, 4)
  const draftState = draftPackage?.state || 'not_started'
  const nextApprovalLabel = draftPackage?.next_approval_step?.label || 'No review step pending'
  const generatedDraftArtifacts = Array.isArray(draftPackage?.generated_artifacts) ? draftPackage.generated_artifacts : []

  const contractForGap = (gapText, index) => {
    const directMatch = objectiveContracts.find((contract) => gapText.includes(contract.objective_id))
    return directMatch || objectiveContracts[index] || null
  }

  const drawerNavButton = (key, label, tone = 'default') => (
    <button
      type="button"
      onClick={() => setDrawerView(key)}
      className={`rounded-lg border px-3 py-2 text-xs font-medium transition ${
        drawerView === key
          ? tone === 'violet'
            ? 'border-violet-200 bg-violet-50 text-violet-700'
            : 'border-blue-200 bg-blue-50 text-blue-700'
          : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
      }`}
    >
      {label}
    </button>
  )

  return (
    <div className="fixed inset-0 z-40">
      <button
        type="button"
        aria-label="Close control review drawer"
        onClick={onClose}
        className="absolute inset-0 bg-slate-900/35 backdrop-blur-[1px]"
      />
      <aside className="absolute right-0 top-0 h-full w-[min(1120px,96vw)] border-l border-gray-200 bg-white shadow-2xl">
        <div className="flex h-full flex-col">
          <div className="sticky top-0 z-10 border-b border-gray-200 bg-white px-5 py-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-bold text-blue-700">{finding.control_id}</span>
                  <StatusBadge status={displayStatus} override={override} />
                  {finding.confidence_score != null && (
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                      {Math.round(finding.confidence_score * 100)}% confidence
                    </span>
                  )}
                </div>
                <h3 className="mt-2 text-xl font-semibold text-gray-900">{finding.control_title}</h3>
                <div className="mt-2 flex flex-wrap gap-2">
                  {needsDisplayReview(finding) && (
                    <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800">
                      Human review recommended
                    </span>
                  )}
                  {finding.llm_challenge_note && (
                    <span className="rounded-full bg-violet-100 px-2.5 py-1 text-xs font-medium text-violet-700">
                      AI dissent present
                    </span>
                  )}
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-500">
                  <span className="rounded-full bg-gray-100 px-2.5 py-1">
                    {fmt12hr(finding.tested_at) ? `Tested ${fmt12hr(finding.tested_at)}` : 'Not tested yet'}
                  </span>
                  <span className="rounded-full bg-gray-100 px-2.5 py-1">
                    {evidenceCount} evidence citation{evidenceCount === 1 ? '' : 's'}
                  </span>
                  {gapCount > 0 && (
                    <span className="rounded-full bg-red-50 px-2.5 py-1 text-red-700">
                      {gapCount} gap{gapCount === 1 ? '' : 's'}
                    </span>
                  )}
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-500 hover:bg-gray-50 hover:text-gray-700"
              >
                <X size={18} />
              </button>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {drawerNavButton('summary', 'Summary')}
              {drawerNavButton('evidence', 'Evidence')}
              {drawerNavButton('advanced', 'Advanced')}
              {finding.llm_challenge_note && (
                drawerNavButton('dissent', 'AI Dissent', 'violet')
              )}
              {(finding.status === 'not_reviewed' || needsDisplayReview(finding)) && (
                <button
                  type="button"
                  onClick={() => onManualReview(finding)}
                  className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800 hover:bg-amber-100"
                >
                  Open manual review
                </button>
              )}
            </div>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
            {drawerView === 'summary' && (
              <>
                <div className="rounded-2xl border border-gray-200 bg-white px-4 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Gap narrative</p>
                  <p className="mt-2 text-sm leading-7 text-gray-700">{decisionSummary}</p>
                </div>

                {!!sharedRemediationPlan && (
                  <div className="rounded-2xl border border-violet-200 bg-violet-50 px-4 py-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-violet-700">Recommended close actions</p>
                    <p className="mt-1 text-sm text-violet-900">
                      Use these steps to correct the current failure condition before gathering reassessment evidence.
                    </p>
                    <div className="mt-4 rounded-xl border border-violet-100 bg-white px-4 py-3">
                      <RemediationPlan text={sharedRemediationPlan} />
                    </div>
                  </div>
                )}

                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">AI draft artifact package</p>
                      <p className="mt-1 text-sm text-emerald-900">
                        Generate a labeled draft package for control-owner review. This does not become evidence of record until a human approves it and attaches supporting records.
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                        draftState === 'approved'
                          ? 'bg-emerald-200 text-emerald-900'
                          : draftState === 'owner_review'
                            ? 'bg-amber-100 text-amber-900'
                            : draftState === 'changes_requested'
                              ? 'bg-red-100 text-red-800'
                              : draftState === 'in_review'
                                ? 'bg-blue-100 text-blue-800'
                                : 'bg-white text-emerald-800'
                      }`}>
                        {titleCaseLabel(draftState.replace(/_/g, ' '))}
                      </span>
                      <button
                        type="button"
                        onClick={() => generateDraftPackage.mutate()}
                        disabled={generateDraftPackage.isPending}
                        className="rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm font-medium text-emerald-800 hover:bg-emerald-100 disabled:opacity-60"
                      >
                        {generateDraftPackage.isPending ? 'Generating…' : 'Generate AI draft artifact'}
                      </button>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
                    <div className="rounded-xl border border-emerald-100 bg-white px-4 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Safe delivery workflow</p>
                      <ul className="mt-2 space-y-2">
                        {(draftPackage?.owner_review_instructions || [
                          'Generate a draft that addresses the identified gaps.',
                          'Send the package to the control owner for accuracy review.',
                          'Do not treat the draft as evidence of record until the supporting records are attached and approved.',
                        ]).map((instruction, index) => (
                          <li key={`${finding.id}-draft-instruction-${index}`} className="flex gap-2 text-sm text-gray-700">
                            <span className="mt-1 h-1.5 w-1.5 rounded-full bg-emerald-500" />
                            <span>{instruction}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div className="rounded-xl border border-emerald-100 bg-white px-4 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Current review state</p>
                      {draftPackageLoading ? (
                        <p className="mt-2 text-sm text-gray-600">Loading current draft package status…</p>
                      ) : (
                        <>
                          <p className="mt-2 text-sm text-gray-800">
                            Next review step: <span className="font-semibold">{nextApprovalLabel}</span>
                          </p>
                          <p className="mt-1 text-sm text-gray-600">
                            {generatedDraftArtifacts.length} generated draft artifact{generatedDraftArtifacts.length === 1 ? '' : 's'} for this control.
                          </p>
                        </>
                      )}
                    </div>
                  </div>

                  {generatedDraftArtifacts.length > 0 && (
                    <div className="mt-4 rounded-xl border border-emerald-100 bg-white px-4 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Draft package contents</p>
                      <div className="mt-3 space-y-3">
                        {generatedDraftArtifacts.map((artifact) => (
                          <div key={`${finding.id}-draft-artifact-${artifact.document_id}`} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 px-3 py-3">
                            <div className="min-w-0">
                              <p className="text-sm font-semibold text-gray-900">{artifact.artifact_title}</p>
                              <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
                                <span className="rounded-full bg-gray-100 px-2 py-0.5">{titleCaseLabel(String(artifact.artifact_type || 'draft').replace(/_/g, ' '))}</span>
                                <span className="rounded-full bg-gray-100 px-2 py-0.5">{titleCaseLabel(String(artifact.approval_status || 'pending_review').replace(/_/g, ' '))}</span>
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={() => downloadByUrl(artifact.download_url, artifact.filename)}
                              className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                            >
                              Download
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {!!draftPackage?.coverage_map?.length && (
                    <div className="mt-4 rounded-xl border border-emerald-100 bg-white px-4 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Gap coverage map</p>
                      <div className="mt-3 space-y-4">
                        {draftPackage.coverage_map.map((item, index) => (
                          <div key={`${finding.id}-coverage-${index}`} className="rounded-lg border border-gray-200 px-3 py-3">
                            <p className="text-sm font-semibold text-gray-900">{item.objective_id} — {item.short_title}</p>
                            <p className="mt-2 text-sm text-gray-700">{item.gap}</p>
                            <div className="mt-3 grid gap-3 lg:grid-cols-3">
                              <div>
                                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Addressed by</p>
                                <ul className="mt-2 space-y-1.5">
                                  {(item.addressed_by || []).map((entry, entryIndex) => (
                                    <li key={entryIndex} className="flex gap-2 text-sm text-gray-700">
                                      <span className="mt-1 h-1.5 w-1.5 rounded-full bg-emerald-500" />
                                      <span>{entry}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                              <div>
                                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Passing evidence must show</p>
                                <ul className="mt-2 space-y-1.5">
                                  {(item.passing_evidence_expectations || []).map((entry, entryIndex) => (
                                    <li key={entryIndex} className="flex gap-2 text-sm text-gray-700">
                                      <span className="mt-1 h-1.5 w-1.5 rounded-full bg-violet-500" />
                                      <span>{entry}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                              <div>
                                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Owner must confirm</p>
                                <ul className="mt-2 space-y-1.5">
                                  {(item.owner_must_confirm || []).map((entry, entryIndex) => (
                                    <li key={entryIndex} className="flex gap-2 text-sm text-gray-700">
                                      <span className="mt-1 h-1.5 w-1.5 rounded-full bg-amber-500" />
                                      <span>{entry}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                <div className="rounded-2xl border border-gray-200 bg-white px-4 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Evidence, gaps, and how to close them</p>
                      <p className="mt-1 text-sm text-gray-600">
                        Review each discovered gap with the exact close guidance that supports a passing reassessment.
                      </p>
                    </div>
                    {recommendedArtifactTypes.length > 0 && (
                      <div className="flex flex-wrap gap-2 justify-end">
                        {recommendedArtifactTypes.map((type) => (
                          <span key={type} className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-xs font-medium text-violet-700">
                            {String(type).replace(/_/g, ' ')}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {guidanceLoading ? (
                    <p className="mt-4 text-sm text-violet-700">Loading remediation guidance…</p>
                  ) : gapCount > 0 ? (
                    <div className="mt-4 space-y-4">
                      {normalizedGaps.map((gapText, index) => {
                        const contract = contractForGap(gapText, index)
                        const displayedFacts = filterDisplayedRequiredFacts(contract?.required_facts || [])
                        const displayedEvidenceExamples = filterDisplayedEvidenceExamples(contract?.evidence_examples || [])
                        return (
                          <div key={`${finding.id}-gap-guide-${index}`} className="rounded-xl border border-violet-200 bg-violet-50/50 px-4 py-4 space-y-4">
                            <div className="rounded-xl border border-red-200 bg-white px-4 py-3">
                              <p className="text-xs font-semibold uppercase tracking-wide text-red-700">Discovered gap</p>
                              <div className="mt-2 flex gap-2 text-sm text-gray-700">
                                <span className="mt-1 h-1.5 w-1.5 rounded-full bg-red-400" />
                                <span>{gapText.replace(/\\n/g, '\n')}</span>
                              </div>
                            </div>

                            {contract && (
                              <div className="rounded-xl border border-violet-100 bg-white px-4 py-3 space-y-3">
                                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">What passing evidence must show</p>
                                <div className="rounded-lg border border-violet-100 bg-violet-50/60 px-3 py-3">
                                  <p className="text-sm font-semibold text-gray-900">
                                    {contract.objective_id} — {contract.short_title}
                                  </p>
                                  {normalizeIdentifier(contract.objective_id) !== findingControlIdNormalized && (
                                    <p className="mt-2 text-xs text-violet-800">
                                      NIST objective identifiers do not always match the exact control label shown above. These bullets are the specific assessment objective expectations tied to this finding.
                                    </p>
                                  )}
                                  <ul className="mt-2 space-y-2">
                                    {displayedFacts.map((fact, factIndex) => (
                                      <li key={factIndex} className="flex gap-2 text-sm text-gray-700">
                                        <span className="mt-1 h-1.5 w-1.5 rounded-full bg-violet-500" />
                                        <span>{fact}</span>
                                      </li>
                                    ))}
                                  </ul>
                                  {displayedEvidenceExamples.length > 0 && (
                                    <div className="mt-3 rounded-lg border border-white/80 bg-white px-3 py-3">
                                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Strong evidence examples</p>
                                      <ul className="space-y-2">
                                        {displayedEvidenceExamples.map((example, exampleIndex) => (
                                          <li key={exampleIndex} className="flex gap-2 text-sm text-gray-700">
                                            <span className="mt-1 h-1.5 w-1.5 rounded-full bg-violet-400" />
                                            <span>{example}</span>
                                          </li>
                                        ))}
                                      </ul>
                                    </div>
                                  )}
                                </div>
                              </div>
                            )}

                          </div>
                        )
                      })}

                      {normalizedGaps.length > 1 && !!sharedRemediationPlan && (
                        null
                      )}

                      {(detectedCollectionGuidanceItems.length > 0 || fallbackCollectionGuidanceItems.length > 0) && (
                        <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3">
                          <p className="text-xs font-semibold uppercase tracking-wide text-sky-700">Where to collect evidence</p>
                          <div className="mt-3 space-y-3">
                            {detectedCollectionGuidanceItems.map((item, idx) => (
                              <div key={`${finding.id}-detected-collection-${idx}`} className="rounded-lg border border-sky-100 bg-white px-3 py-3 text-sm text-gray-700">
                                <p className="font-semibold text-sky-900">{item.tool_name || item.domain}</p>
                                {item.where_to_go?.length > 0 && (
                                  <div className="mt-3">
                                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Go to</p>
                                    <ul className="mt-2 space-y-1.5">
                                      {item.where_to_go.map((entry, entryIndex) => (
                                        <li key={entryIndex} className="flex gap-2 text-sm text-gray-700">
                                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-sky-500" />
                                          <span>{entry}</span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                                {item.collect?.length > 0 && (
                                  <div className="mt-3">
                                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Collect</p>
                                    <ul className="mt-2 space-y-1.5">
                                      {item.collect.map((entry, entryIndex) => (
                                        <li key={entryIndex} className="flex gap-2 text-sm text-gray-700">
                                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-sky-500" />
                                          <span>{entry}</span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                                {item.look_for?.length > 0 && (
                                  <div className="mt-3">
                                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Look for</p>
                                    <ul className="mt-2 space-y-1.5">
                                      {item.look_for.map((entry, entryIndex) => (
                                        <li key={entryIndex} className="flex gap-2 text-sm text-gray-700">
                                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-sky-500" />
                                          <span>{entry}</span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </div>
                            ))}

                            {fallbackCollectionGuidanceItems.length > 0 && (
                              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-gray-700">
                                <p className="font-semibold text-amber-900">Tool-specific collection guidance is not available for this project yet</p>
                                <p className="mt-1 text-xs text-amber-800">
                                  No matching tools were detected for {fallbackDomains.join(' and ')} evidence, so this section can only suggest the kinds of records you need. Replace it with your actual platform and repository locations.
                                </p>
                                {fallbackCollect.length > 0 && (
                                  <div className="mt-3">
                                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Likely records to gather</p>
                                    <ul className="mt-2 space-y-1.5">
                                      {fallbackCollect.map((entry, entryIndex) => (
                                        <li key={entryIndex} className="flex gap-2 text-sm text-gray-700">
                                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-amber-500" />
                                          <span>{entry}</span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                                {fallbackLookFor.length > 0 && (
                                  <div className="mt-3">
                                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Fields those records should show</p>
                                    <ul className="mt-2 space-y-1.5">
                                      {fallbackLookFor.map((entry, entryIndex) => (
                                        <li key={entryIndex} className="flex gap-2 text-sm text-gray-700">
                                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-amber-500" />
                                          <span>{entry}</span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="mt-4 space-y-4">
                      {!!sharedRemediationPlan && (
                        <div className="rounded-xl border border-violet-100 bg-violet-50 px-4 py-3">
                          <p className="text-xs font-semibold uppercase tracking-wide text-violet-700">How to close this gap</p>
                          <div className="mt-3">
                            <RemediationPlan text={sharedRemediationPlan} />
                          </div>
                        </div>
                      )}
                      {!sharedRemediationPlan && objectiveContracts.length === 0 && (
                        <p className="text-sm text-gray-600">No explicit evidence gaps were captured for this control.</p>
                      )}
                    </div>
                  )}
                </div>

                <div className="rounded-2xl border border-gray-200 bg-white px-4 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Reviewer notes</p>
                  <NotesEditor
                    findingId={finding.id}
                    initialNotes={finding.notes}
                    projectId={projectId}
                    assessmentId={assessmentId}
                    onSaved={onFindingUpdate}
                  />
                </div>

                <div className="rounded-2xl border border-gray-200 bg-white px-4 py-4">
                  <AssessorActions finding={finding} override={override} onUpsert={onUpsert} />
                </div>
              </>
            )}

            {drawerView === 'evidence' && (
              <>
                <div className="rounded-2xl border border-gray-200 bg-white px-4 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Cited evidence</p>
                  <div className="mt-3">
                    <EvidenceCitations
                      citations={finding.evidence_citations}
                      docMap={docMap}
                      projectId={projectId}
                      assessmentId={assessmentId}
                      controlId={finding.control_id}
                      controlTitle={finding.control_title}
                    />
                  </div>
                </div>

                <div className="rounded-2xl border border-gray-200 bg-white px-4 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Evidence interpretation</p>
                  <div className="mt-3 space-y-3 text-sm text-gray-700">
                    {finding.implementation_statement ? (
                      <TextBlock text={finding.implementation_statement} />
                    ) : (
                      <p>No narrative interpretation is stored for this control.</p>
                    )}
                    {gapCount > 0 && (
                      <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-red-700 mb-2">Missing or weak evidence</p>
                        <ul className="space-y-2">
                          {finding.gaps.map((gap, index) => (
                            <li key={`${finding.id}-evidence-gap-${index}`} className="flex gap-2 text-sm text-red-900">
                              <span className="mt-1 h-1.5 w-1.5 rounded-full bg-red-500" />
                              <span>{String(gap).replace(/\\n/g, '\n')}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}

            {drawerView === 'dissent' && finding.llm_challenge_note && (
              <>
                <div className="rounded-2xl border border-violet-200 bg-violet-50 px-4 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-violet-700">AI dissent</p>
                  <p className="mt-2 text-sm leading-7 text-violet-900">{finding.llm_challenge_note}</p>
                </div>
                <div className="rounded-2xl border border-gray-200 bg-white px-4 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Discuss this challenge</p>
                  <p className="text-sm text-gray-600">
                    Review why the secondary model disagreed with the determination and what evidence would materially change the result.
                  </p>
                  <div className="mt-3">
                    <button
                      type="button"
                      onClick={onDiscuss}
                      className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm font-medium text-violet-700 hover:bg-violet-100"
                    >
                      Open AI dissent review
                    </button>
                  </div>
                </div>
              </>
            )}

            {drawerView === 'advanced' && (
              <ControlDetail
                f={finding}
                projectId={projectId}
                assessmentId={assessmentId}
                onFindingUpdate={onFindingUpdate}
                override={override}
                onUpsert={(body) => onUpsert(body)}
                docMap={docMap}
              />
            )}
          </div>
        </div>
      </aside>
    </div>
  )
}

function SelectedControlContextBar({ finding, onClear, helperText = 'Choose a control in Findings to inspect control-specific evidence and decision detail.' }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Selected control</p>
          {finding ? (
            <>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-bold text-blue-700">{finding.control_id}</span>
                <StatusBadge status={finding.status} />
              </div>
              <p className="mt-1 text-sm text-gray-800">{finding.control_title}</p>
              <p className="mt-1 text-xs text-gray-500">You are now in control-level review mode for this assessment.</p>
            </>
          ) : (
            <p className="mt-2 text-sm text-gray-600">{helperText}</p>
          )}
        </div>
        {finding && (
          <button
            type="button"
            onClick={onClear}
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            Clear selection
          </button>
        )}
      </div>
    </div>
  )
}

function ScopeNavButton({ active, label, onClick, count = null }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition ${
        active
          ? 'border-blue-200 bg-blue-50 text-blue-700'
          : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
      }`}
    >
      <span>{label}</span>
      {count !== null && (
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${active ? 'bg-white text-blue-700' : 'bg-gray-100 text-gray-500'}`}>
          {count}
        </span>
      )}
    </button>
  )
}

function AssessmentNavigationBar({
  activeTab,
  findingsView,
  advancedView,
  selectedFinding,
  visibleFindingsCount,
  evidenceCount,
  advancedCount,
  onOpenOverview,
  onOpenFindings,
  onOpenEvidence,
  onOpenOutputs,
  onOpenAdvanced,
  onClearSelection,
}) {
  const advancedLabel = ({
    delta: 'Changes',
    dissents: 'AI Dissent',
    workbench: 'Decision Mechanics',
    review: 'Keyboard Review',
    system: 'System Knowledge',
  })[advancedView] || 'Advanced'

  const showControlWorkspace = !!selectedFinding && activeTab === 'findings'

  if (!showControlWorkspace) {
    return (
      <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Assessment workspace</p>
            <p className="mt-1 text-sm text-gray-600">Move through the assessment. Select a control from Findings when you want control-level detail.</p>
          </div>
          <button
            type="button"
            onClick={onOpenFindings}
            className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100"
          >
            Open Findings
          </button>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <ScopeNavButton active={activeTab === 'overview'} label="Overview" onClick={onOpenOverview} />
          <ScopeNavButton active={activeTab === 'findings'} label={findingsView === 'flat' ? 'Findings / Flat' : 'Findings'} onClick={onOpenFindings} count={visibleFindingsCount} />
          <ScopeNavButton active={activeTab === 'evidence'} label="Evidence" onClick={onOpenEvidence} count={evidenceCount} />
          <ScopeNavButton active={activeTab === 'outputs'} label="Outputs" onClick={onOpenOutputs} />
          <ScopeNavButton active={activeTab === 'advanced'} label={activeTab === 'advanced' ? `Advanced / ${advancedLabel}` : 'Advanced'} onClick={onOpenAdvanced} count={advancedCount} />
        </div>
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(340px,0.8fr)]">
      <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Assessment workspace</p>
        <p className="mt-1 text-sm text-gray-600">
          Move around the full assessment without changing the selected control.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <ScopeNavButton active={activeTab === 'overview'} label="Overview" onClick={onOpenOverview} />
          <ScopeNavButton active={activeTab === 'findings'} label={findingsView === 'flat' ? 'Findings / Flat' : 'Findings'} onClick={onOpenFindings} count={visibleFindingsCount} />
          <ScopeNavButton active={activeTab === 'evidence'} label="Evidence" onClick={onOpenEvidence} count={evidenceCount} />
          <ScopeNavButton active={activeTab === 'outputs'} label="Outputs" onClick={onOpenOutputs} />
          <ScopeNavButton active={activeTab === 'advanced'} label={activeTab === 'advanced' ? `Advanced / ${advancedLabel}` : 'Advanced'} onClick={onOpenAdvanced} count={advancedCount} />
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Control review workspace</p>
        <>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-bold text-blue-700">{selectedFinding.control_id}</span>
              <StatusBadge status={selectedFinding.status} />
            </div>
            <p className="mt-1 text-sm text-gray-800">{selectedFinding.control_title}</p>
            <p className="mt-1 text-xs text-gray-500">
              You are reviewing one control inside this assessment. Use the assessment workspace on the left to change page context, or clear this selection to return to assessment-only review.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <ScopeNavButton active={activeTab === 'findings'} label="Findings" onClick={onOpenFindings} />
              <ScopeNavButton active={activeTab === 'evidence'} label="Evidence" onClick={onOpenEvidence} />
              <ScopeNavButton active={activeTab === 'advanced'} label="Advanced" onClick={onOpenAdvanced} />
              <button
                type="button"
                onClick={onClearSelection}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Clear selection
              </button>
            </div>
          </>
      </div>
    </div>
  )
}


function AssessmentFinalization({ projectId, assessmentId, assessment }) {
  const qc = useQueryClient()
  const base = `/projects/${projectId}/assessments/${assessmentId}/governance`
  const [activityDraft, setActivityDraft] = useState(null)
  const [dissentDraft, setDissentDraft] = useState(null)
  const [tailoringDraft, setTailoringDraft] = useState({
    control_id: '', decision_type: 'odp', parameter_id: '', value: '', rationale: '', evidence_refs: '',
  })
  const [approvalStatement, setApprovalStatement] = useState('')
  const [errorMessage, setErrorMessage] = useState('')

  const useGovernanceQuery = (name, path) => useQuery({
    queryKey: ['assessment-governance', name, assessmentId],
    queryFn: () => api.get(`${base}${path}`).then((response) => response.data),
    enabled: !!assessmentId,
  })
  const { data: plan } = useGovernanceQuery('plan', '/plan')
  const { data: readiness } = useGovernanceQuery('readiness', '/readiness')
  const { data: activities = [] } = useGovernanceQuery('activities', '/activities')
  const { data: tailoring = [] } = useGovernanceQuery('tailoring', '/tailoring')
  const { data: dissents = [] } = useGovernanceQuery('dissents', '/dissents')
  const { data: approvals = [] } = useGovernanceQuery('approvals', '/approvals')

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['assessment-governance'] })
    qc.invalidateQueries({ queryKey: ['assessment', assessmentId] })
  }
  const useGovernanceMutation = (mutationFn, onSuccess) => useMutation({
    mutationFn,
    onSuccess: (data) => {
      setErrorMessage('')
      refresh()
      onSuccess?.(data)
    },
    onError: (error) => setErrorMessage(
      typeof error.response?.data?.detail === 'string'
        ? error.response.data.detail
        : error.response?.data?.detail?.message || error.message
    ),
  })
  const completeActivity = useGovernanceMutation(
    ({ id, result, evidenceRefs }) => api.patch(`${base}/activities/${id}/complete`, {
      result,
      evidence_refs: evidenceRefs.split('\n').map((value) => value.trim()).filter(Boolean),
    }),
    () => setActivityDraft(null),
  )
  const createTailoring = useGovernanceMutation(
    () => api.post(`${base}/tailoring`, {
      control_id: tailoringDraft.control_id,
      decision_type: tailoringDraft.decision_type,
      parameter_id: tailoringDraft.parameter_id || null,
      value: tailoringDraft.value || null,
      rationale: tailoringDraft.rationale,
      evidence_refs: tailoringDraft.evidence_refs.split('\n').map((value) => value.trim()).filter(Boolean),
    }),
    () => setTailoringDraft({ control_id: '', decision_type: 'odp', parameter_id: '', value: '', rationale: '', evidence_refs: '' }),
  )
  const reviewTailoring = useGovernanceMutation(
    ({ id, status }) => api.patch(`${base}/tailoring/${id}/review`, { status }),
  )
  const resolveDissent = useGovernanceMutation(
    ({ controlId, status, note }) => api.patch(`${base}/dissents/${controlId}`, { resolution_status: status, note }),
    () => setDissentDraft(null),
  )
  const recordApproval = useGovernanceMutation(
    (approvalType) => api.post(`${base}/approvals`, { approval_type: approvalType, statement: approvalStatement }),
    () => setApprovalStatement(''),
  )
  const finalize = useGovernanceMutation(() => api.post(`${base}/finalize`))

  const incompleteActivities = activities.filter((row) => row.status !== 'completed' || !row.reviewed_by)
  const unresolvedDissents = dissents.filter((row) => !['resolved', 'dismissed'].includes(row.resolution_status))
  const approvedTypes = new Set(approvals.filter((row) => row.decision === 'approved').map((row) => row.approval_type))
  const blockerCount = (readiness?.blockers || []).reduce((sum, blocker) => sum + Number(blocker.count || 0), 0)

  return (
    <section className="rounded-2xl border border-slate-300 bg-white px-5 py-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Assessment finalization</p>
          <h3 className="mt-1 text-lg font-bold text-slate-950">
            {assessment?.finalization_status === 'finalized' ? 'Final assessment record' : 'Human review and approval gates'}
          </h3>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Automated findings remain draft until required assessment activities, control reviews, tailoring decisions, dissents, POA&amp;Ms, and independent approvals are complete.
          </p>
        </div>
        <div className={`rounded-xl border px-4 py-3 ${readiness?.ready ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'}`}>
          <p className={`text-xs font-semibold uppercase ${readiness?.ready ? 'text-emerald-700' : 'text-amber-700'}`}>
            {assessment?.finalization_status === 'finalized' ? 'Finalized' : readiness?.ready ? 'Ready to finalize' : 'Not ready'}
          </p>
          <p className="mt-1 text-2xl font-bold text-slate-900">{blockerCount}</p>
          <p className="text-xs text-slate-600">unresolved gate items</p>
        </div>
      </div>

      {errorMessage && (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{errorMessage}</div>
      )}

      <div className="mt-5 grid gap-4 xl:grid-cols-3">
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-4 xl:col-span-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Approved plan</p>
          <p className="mt-2 text-sm font-semibold text-blue-950">{plan?.title || 'Loading plan...'}</p>
          <p className="mt-2 text-sm text-blue-900">{plan?.scope?.statement}</p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            {(plan?.methods || []).map((method) => <span key={method} className="rounded-full bg-white px-2.5 py-1 font-semibold text-blue-700">{method}</span>)}
            {plan?.depth && <span className="rounded-full bg-white px-2.5 py-1 text-blue-700">{plan.depth} depth</span>}
            {plan?.coverage && <span className="rounded-full bg-white px-2.5 py-1 text-blue-700">{plan.coverage} coverage</span>}
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-4 xl:col-span-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-600">Open gates</p>
          {(readiness?.blockers || []).length ? (
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {readiness.blockers.map((blocker) => (
                <div key={blocker.code} className="rounded-lg border border-gray-200 bg-white px-3 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-semibold text-gray-900">{blocker.message}</p>
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-bold text-amber-800">{blocker.count}</span>
                  </div>
                  {blocker.items?.length > 0 && <p className="mt-2 text-xs text-gray-500">{blocker.items.slice(0, 8).join(', ')}{blocker.count > 8 ? ' ...' : ''}</p>}
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-emerald-700">All governance gates are satisfied.</p>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <details className="rounded-xl border border-gray-200 bg-white p-4" open={incompleteActivities.length > 0}>
          <summary className="cursor-pointer text-sm font-semibold text-gray-900">
            Assessment activities ({activities.length - incompleteActivities.length}/{activities.length} complete)
          </summary>
          <p className="mt-2 text-xs text-gray-500">ATO Bot records document examination. A qualified assessor must record each planned interview and technical test result with a source reference.</p>
          <div className="mt-3 space-y-2">
            {incompleteActivities.slice(0, 20).map((row) => (
              <div key={row.id} className="rounded-lg border border-gray-200 px-3 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div><span className="font-mono text-xs font-bold text-blue-700">{row.control_id}</span><span className="ml-2 text-xs font-semibold text-gray-600">{row.method}</span></div>
                  <button
                    type="button"
                    onClick={() => setActivityDraft({
                      id: row.id,
                      result: row.result || '',
                      evidenceRefs: (row.evidence_refs || []).map((value) => (
                        typeof value === 'string' ? value : JSON.stringify(value)
                      )).join('\n'),
                    })}
                    className="text-xs font-semibold text-blue-700"
                  >
                    {row.status === 'performed' ? 'Review result' : 'Record result'}
                  </button>
                </div>
                <p className="mt-1 text-xs text-gray-500">{row.description}</p>
                {activityDraft?.id === row.id && (
                  <div className="mt-3 space-y-2">
                    <textarea rows={3} value={activityDraft.result} onChange={(event) => setActivityDraft({ ...activityDraft, result: event.target.value })} placeholder="What was interviewed or tested, how it was performed, and the observed result" className="w-full rounded-lg border px-3 py-2 text-sm" />
                    <textarea rows={2} value={activityDraft.evidenceRefs} onChange={(event) => setActivityDraft({ ...activityDraft, evidenceRefs: event.target.value })} placeholder="One evidence, interview, ticket, test script, or result reference per line" className="w-full rounded-lg border px-3 py-2 text-sm" />
                    <button type="button" disabled={completeActivity.isPending || activityDraft.result.trim().length < 10 || !activityDraft.evidenceRefs.trim()} onClick={() => completeActivity.mutate(activityDraft)} className="rounded-lg bg-blue-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Save activity record</button>
                  </div>
                )}
              </div>
            ))}
            {incompleteActivities.length > 20 && <p className="text-xs text-gray-500">Showing 20 of {incompleteActivities.length} incomplete activities.</p>}
            {incompleteActivities.length === 0 && <p className="text-sm text-emerald-700">All planned activities have recorded results.</p>}
          </div>
        </details>

        <details className="rounded-xl border border-gray-200 bg-white p-4" open={unresolvedDissents.length > 0}>
          <summary className="cursor-pointer text-sm font-semibold text-gray-900">AI dissent resolution ({unresolvedDissents.length} open)</summary>
          <div className="mt-3 space-y-2">
            {unresolvedDissents.slice(0, 20).map((row) => (
              <div key={row.control_id} className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-3">
                <p className="font-mono text-xs font-bold text-violet-800">{row.control_id}</p>
                <p className="mt-1 text-xs text-violet-900">{row.dissent_note || 'The secondary review disagreed with the draft determination.'}</p>
                <button type="button" onClick={() => setDissentDraft({ controlId: row.control_id, status: 'resolved', note: '' })} className="mt-2 text-xs font-semibold text-violet-700">Resolve dissent</button>
                {dissentDraft?.controlId === row.control_id && (
                  <div className="mt-3 space-y-2">
                    <select value={dissentDraft.status} onChange={(event) => setDissentDraft({ ...dissentDraft, status: event.target.value })} className="rounded-lg border px-3 py-2 text-sm"><option value="resolved">Resolved through reviewer determination</option><option value="dismissed">Dismissed with rationale</option></select>
                    <textarea rows={3} value={dissentDraft.note} onChange={(event) => setDissentDraft({ ...dissentDraft, note: event.target.value })} placeholder="Document the evidence and judgment that resolved the disagreement" className="w-full rounded-lg border px-3 py-2 text-sm" />
                    <button type="button" disabled={resolveDissent.isPending || dissentDraft.note.trim().length < 10} onClick={() => resolveDissent.mutate(dissentDraft)} className="rounded-lg bg-violet-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Save resolution</button>
                  </div>
                )}
              </div>
            ))}
            {unresolvedDissents.length === 0 && <p className="text-sm text-emerald-700">All AI dissents have a human resolution.</p>}
          </div>
        </details>

        <details className="rounded-xl border border-gray-200 bg-white p-4">
          <summary className="cursor-pointer text-sm font-semibold text-gray-900">Tailoring and organization-defined parameters ({tailoring.length})</summary>
          <div className="mt-3 space-y-3">
            {tailoring.map((row) => (
              <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-gray-200 px-3 py-2 text-xs">
                <span><strong>{row.control_id}</strong> {row.decision_type}{row.parameter_id ? ` / ${row.parameter_id}` : ''}</span>
                <div className="flex items-center gap-2"><span className="font-semibold">{row.status}</span>{row.status === 'proposed' && <><button type="button" onClick={() => reviewTailoring.mutate({ id: row.id, status: 'approved' })} className="text-emerald-700">Approve</button><button type="button" onClick={() => reviewTailoring.mutate({ id: row.id, status: 'rejected' })} className="text-red-700">Reject</button></>}</div>
              </div>
            ))}
            <div className="grid gap-2 md:grid-cols-2">
              <input value={tailoringDraft.control_id} onChange={(event) => setTailoringDraft({ ...tailoringDraft, control_id: event.target.value })} placeholder="Control ID" className="rounded-lg border px-3 py-2 text-sm" />
              <select value={tailoringDraft.decision_type} onChange={(event) => setTailoringDraft({ ...tailoringDraft, decision_type: event.target.value })} className="rounded-lg border px-3 py-2 text-sm"><option value="odp">Organization-defined parameter</option><option value="inherited">Inherited</option><option value="compensating">Compensating control</option><option value="not_applicable">Not applicable</option></select>
              <input value={tailoringDraft.parameter_id} onChange={(event) => setTailoringDraft({ ...tailoringDraft, parameter_id: event.target.value })} placeholder="Parameter ID, when applicable" className="rounded-lg border px-3 py-2 text-sm" />
              <input value={tailoringDraft.value} onChange={(event) => setTailoringDraft({ ...tailoringDraft, value: event.target.value })} placeholder="Approved value or decision" className="rounded-lg border px-3 py-2 text-sm" />
            </div>
            <textarea rows={2} value={tailoringDraft.rationale} onChange={(event) => setTailoringDraft({ ...tailoringDraft, rationale: event.target.value })} placeholder="Rationale" className="w-full rounded-lg border px-3 py-2 text-sm" />
            <textarea rows={2} value={tailoringDraft.evidence_refs} onChange={(event) => setTailoringDraft({ ...tailoringDraft, evidence_refs: event.target.value })} placeholder="Evidence references, one per line" className="w-full rounded-lg border px-3 py-2 text-sm" />
            <button type="button" disabled={createTailoring.isPending || !tailoringDraft.control_id.trim() || tailoringDraft.rationale.trim().length < 10} onClick={() => createTailoring.mutate()} className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700 disabled:opacity-40">Add tailoring decision</button>
          </div>
        </details>

        <details className="rounded-xl border border-gray-200 bg-white p-4" open={readiness?.ready || approvals.length > 0}>
          <summary className="cursor-pointer text-sm font-semibold text-gray-900">Approval and finalization</summary>
          <div className="mt-3 space-y-3">
            <div className="flex flex-wrap gap-2 text-xs"><span className={`rounded-full px-2.5 py-1 ${approvedTypes.has('assessor') ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-600'}`}>Assessor approval</span><span className={`rounded-full px-2.5 py-1 ${approvedTypes.has('independent_reviewer') ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-600'}`}>Independent approval</span></div>
            <textarea rows={3} value={approvalStatement} onChange={(event) => setApprovalStatement(event.target.value)} placeholder="Approval statement describing the review performed and the determination accepted" className="w-full rounded-lg border px-3 py-2 text-sm" />
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={recordApproval.isPending || approvalStatement.trim().length < 20 || approvedTypes.has('assessor')} onClick={() => recordApproval.mutate('assessor')} className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700 disabled:opacity-40">Record assessor approval</button>
              <button type="button" disabled={recordApproval.isPending || approvalStatement.trim().length < 20 || !approvedTypes.has('assessor') || approvedTypes.has('independent_reviewer')} onClick={() => recordApproval.mutate('independent_reviewer')} className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-xs font-semibold text-violet-700 disabled:opacity-40">Record independent approval</button>
              <button type="button" disabled={finalize.isPending || !readiness?.ready || assessment?.finalization_status === 'finalized'} onClick={() => finalize.mutate()} className="rounded-lg bg-emerald-700 px-4 py-2 text-xs font-semibold text-white disabled:opacity-40">Finalize assessment</button>
            </div>
          </div>
        </details>
      </div>
    </section>
  )
}


export default function AssessmentView() {
  const { projectId, assessmentId } = useParams()
  const qc = useQueryClient()
  const pageTopRef = useRef(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = ['overview', 'findings', 'evidence', 'outputs', 'advanced'].includes(searchParams.get('tab'))
    ? searchParams.get('tab')
    : 'overview'
  const findingsView = ['family', 'flat'].includes(searchParams.get('findingsView'))
    ? searchParams.get('findingsView')
    : 'flat'
  const advancedView = ['delta', 'dissents', 'workbench', 'review', 'system'].includes(searchParams.get('advancedView'))
    ? searchParams.get('advancedView')
    : 'delta'
  const [statusFilter, setStatusFilter] = useState('')
  const [familyFilter, setFamilyFilter] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [reviewAttentionFilter, setReviewAttentionFilter] = useState(false)
  const [dissentOnlyFilter, setDissentOnlyFilter] = useState(false)
  const [changedOnlyFilter, setChangedOnlyFilter] = useState(false)
  const selectedControlId = searchParams.get('control') || null
  const [manualReviewFinding, setManualReviewFinding] = useState(null)
  const [retrying, setRetrying] = useState(false)
  const [editingNotes, setEditingNotes] = useState(false)
  const [notesText, setNotesText] = useState('')

  const resetFindingsFilters = useCallback(() => {
    setStatusFilter('')
    setFamilyFilter('')
    setSearchTerm('')
    setReviewAttentionFilter(false)
    setDissentOnlyFilter(false)
    setChangedOnlyFilter(false)
  }, [])

  const { data: assessment } = useQuery({
    queryKey: ['assessment', assessmentId],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}`).then(r => r.data),
    refetchInterval: (query) => query.state.data?.status === 'running' ? 3000 : false,
  })

  const { data: assessmentRollup } = useQuery({
    queryKey: ['assessment-rollup', assessmentId],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/rollup`).then(r => r.data),
    enabled: !!assessmentId && assessment?.status === 'complete',
  })

  const { data: findings = [], refetch: refetchFindings } = useQuery({
    queryKey: ['findings', assessmentId],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/findings`).then(r => r.data),
    refetchInterval: (query) => {
      if (assessment?.status === 'running') return 3000
      if (retrying) {
        const pending = (query.state.data || []).filter(f => f.status === 'not_reviewed').length
        if (pending === 0) {
          setRetrying(false)
          return false
        }
        return 3000
      }
      return false
    },
  })

  const { data: overrides = [] } = useQuery({
    queryKey: ['overrides', projectId],
    queryFn: () => api.get(`/projects/${projectId}/overrides`).then(r => r.data),
  })

  const { data: evidenceSources = [] } = useQuery({
    queryKey: ['assessment-evidence-sources', projectId, assessmentId],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/evidence-sources`).then(r => r.data),
    enabled: !!assessmentId,
  })

  const docMap = useMemo(
    () => Object.fromEntries(
      evidenceSources.flatMap(d => [
        [d.filename, d],
        [`id:${d.id}`, d],
      ])
    ),
    [evidenceSources]
  )

  const overrideMap = useMemo(
    () => Object.fromEntries(overrides.map(o => [o.control_id, o])),
    [overrides]
  )

  const upsertOverride = useMutation({
    mutationFn: ({ controlId, body }) => api.put(`/projects/${projectId}/overrides/${controlId}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['overrides', projectId] }),
  })

  const pauseAssessment = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/assessments/${assessmentId}/pause`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['assessment', assessmentId] }),
  })

  const resumeAssessment = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/assessments/${assessmentId}/resume`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assessment', assessmentId] })
      qc.invalidateQueries({ queryKey: ['findings', assessmentId] })
    },
  })

  const handleUpsert = (controlId, body) => upsertOverride.mutate({ controlId, body })

  const retryFailed = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/assessments/${assessmentId}/retry-failed`),
    onSuccess: (res) => {
      if (res.data.queued > 0) setRetrying(true)
      qc.invalidateQueries({ queryKey: ['findings', assessmentId] })
      qc.invalidateQueries({ queryKey: ['assessment', assessmentId] })
    },
  })

  const updateAssessmentNotes = async () => {
    try {
      await api.patch(`/projects/${projectId}/assessments/${assessmentId}`, { notes: notesText.trim() || null })
      qc.invalidateQueries({ queryKey: ['assessment', assessmentId] })
      setEditingNotes(false)
    } catch (e) {
      alert('Save failed: ' + (e.response?.data?.detail || e.message))
    }
  }

  const onFindingUpdate = () => {
    qc.invalidateQueries({ queryKey: ['findings', assessmentId] })
    qc.invalidateQueries({ queryKey: ['assessment-rollup', assessmentId] })
    qc.invalidateQueries({ queryKey: ['assessment', assessmentId] })
  }

  const openAssistantForFinding = (finding, options = {}) => {
    openCyberAssistant({
      mode: 'control',
      title: `${finding.control_id} Assistant`,
      projectId: Number(projectId),
      assessmentId: Number(assessmentId),
      attachments: [
        { type: 'finding', resource_id: String(finding.id) },
        {
          type: 'control',
          resource_id: finding.control_id,
          context_json: {
            assessment_id: Number(assessmentId),
            control_id: finding.control_id,
            control_title: finding.control_title,
            finding_status: finding.status,
            finding_gaps: finding.gaps || [],
            label: `${finding.control_id}: ${finding.control_title}`,
          },
        },
      ],
      ...options,
    })
  }

  const commitAssessmentNav = useCallback((updates) => {
    const next = new URLSearchParams(searchParams)
    const nextTab = updates.tab ?? activeTab
    const nextFindingsView = updates.findingsView ?? findingsView
    const nextAdvancedView = updates.advancedView ?? advancedView
    const nextControl = Object.prototype.hasOwnProperty.call(updates, 'control')
      ? updates.control
      : selectedControlId

    if (nextTab && nextTab !== 'overview') next.set('tab', nextTab)
    else next.delete('tab')

    if (nextFindingsView && nextFindingsView !== 'family') next.set('findingsView', nextFindingsView)
    else next.delete('findingsView')

    if (nextAdvancedView && nextAdvancedView !== 'delta') next.set('advancedView', nextAdvancedView)
    else next.delete('advancedView')

    if (nextControl) next.set('control', nextControl)
    else next.delete('control')

    setSearchParams(next)
  }, [searchParams, setSearchParams, activeTab, findingsView, advancedView, selectedControlId])

  const setActiveTab = useCallback((tab) => {
    commitAssessmentNav({ tab, control: tab === 'findings' ? selectedControlId : null })
  }, [commitAssessmentNav, selectedControlId])

  const setFindingsView = useCallback((view) => {
    commitAssessmentNav({ tab: 'findings', findingsView: view })
  }, [commitAssessmentNav])

  const setAdvancedView = useCallback((view) => {
    commitAssessmentNav({ tab: 'advanced', advancedView: view, control: null })
  }, [commitAssessmentNav])

  const setSelectedControlId = useCallback((controlId) => {
    commitAssessmentNav({ control: controlId })
  }, [commitAssessmentNav])

  const openAdvancedView = useCallback((view) => {
    commitAssessmentNav({ tab: 'advanced', advancedView: view, control: null })
  }, [commitAssessmentNav])

  const openFindingsView = useCallback((view = 'flat') => {
    commitAssessmentNav({ tab: 'findings', findingsView: view })
  }, [commitAssessmentNav])

  const openWorkspaceFindings = useCallback((view = 'flat') => {
    resetFindingsFilters()
    openFindingsView(view)
  }, [openFindingsView, resetFindingsFilters])

  useEffect(() => {
    if (!editingNotes) {
      setNotesText(assessment?.notes || '')
    }
  }, [assessment?.notes, editingNotes])

  useEffect(() => {
    const scrollToTop = () => {
      pageTopRef.current?.scrollIntoView({ block: 'start' })
      if (typeof window !== 'undefined') {
        window.scrollTo(0, 0)
      }
    }
    const frame = window.requestAnimationFrame(scrollToTop)
    return () => window.cancelAnimationFrame(frame)
  }, [activeTab, findingsView, advancedView])

  useEffect(() => {
    if (activeTab !== 'findings' && selectedControlId) {
      commitAssessmentNav({ control: null })
    }
  }, [activeTab, selectedControlId, commitAssessmentNav])

  const isRunning = assessment?.status === 'running'
  const isPaused = assessment?.status === 'paused'
  const duration = fmtDuration(assessment?.started_at, assessment?.completed_at)
  const displayedControlsTotal = Number(assessment?.controls_total || findings.length || 0)
  const displayedControlsComplete = displayedControlsTotal > 0
    ? Math.min(Number(assessment?.controls_complete || 0), displayedControlsTotal)
    : Number(assessment?.controls_complete || 0)
  const assessmentContent = assessment?.content_json || {}
  const systemKnowledge = assessmentContent.system_knowledge || {}

  const byFamily = useMemo(() => findings.reduce((acc, f) => {
    if (!acc[f.control_family]) acc[f.control_family] = []
    acc[f.control_family].push(f)
    return acc
  }, {}), [findings])
  const families = Object.keys(byFamily).sort()

  const counts = findings.reduce((acc, f) => {
    acc[f.status] = (acc[f.status] || 0) + 1
    return acc
  }, {})
  const rollupSummary = assessmentRollup?.summary || {}
  const pageCounts = rollupSummary.counts || counts
  const dissentCount = pageCounts.challenged || findings.filter(f => f.llm_challenge_note).length
  const reviewAttentionControls = (rollupSummary.review_attention?.controls || findings.filter(f => f.needs_manual_review))
    .map(control => findings.find(item => item.control_id === control.control_id) || control)
    .filter(item => needsDisplayReview(item))
  const reviewAttentionCount = reviewAttentionControls.length
  const changedFindings = findings.filter(f =>
    f.prev_status !== null && f.prev_status !== undefined && f.prev_status !== f.status
  )
  const dissentFindings = useMemo(() => findings.filter(f => f.llm_challenge_note), [findings])

  const visibleFindings = useMemo(() => findings.filter((finding) => {
    if (statusFilter && finding.status !== statusFilter) return false
    if (familyFilter && finding.control_family !== familyFilter) return false
    if (reviewAttentionFilter && !needsDisplayReview(finding)) return false
    if (dissentOnlyFilter && !finding.llm_challenge_note) return false
    if (changedOnlyFilter && !(finding.prev_status !== null && finding.prev_status !== undefined && finding.prev_status !== finding.status)) return false
    if (searchTerm) {
      const haystack = `${finding.control_id} ${finding.control_title} ${finding.control_family}`.toLowerCase()
      if (!haystack.includes(searchTerm.toLowerCase())) return false
    }
    return true
  }), [findings, statusFilter, familyFilter, reviewAttentionFilter, dissentOnlyFilter, changedOnlyFilter, searchTerm])

  const visibleByFamily = useMemo(() => visibleFindings.reduce((acc, f) => {
    if (!acc[f.control_family]) acc[f.control_family] = []
    acc[f.control_family].push(f)
    return acc
  }, {}), [visibleFindings])
  const visibleFamilies = Object.keys(visibleByFamily).sort()
  const sortedVisibleFindings = useMemo(() => [...visibleFindings].sort(sortByControlId), [visibleFindings])

  const selectedFinding = useMemo(() => {
    if (!selectedControlId) return null
    return findings.find(f => f.control_id === selectedControlId) || null
  }, [findings, selectedControlId])

  const fetchBlob = async (url, filename) => {
    try {
      const res = await api.get(url, { responseType: 'blob' })
      const href = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = href
      a.download = filename
      a.click()
      URL.revokeObjectURL(href)
    } catch (e) {
      alert('Download failed: ' + (e.response?.data?.detail || e.message))
    }
  }
  const downloadReport = (format) => {
    const ext = { excel: 'xlsx', word: 'docx', pptx: 'pptx', json: 'json' }[format] || format
    fetchBlob(`/projects/${projectId}/assessments/${assessmentId}/reports/${format}`, `assessment-${assessmentId}-report.${ext}`)
  }
  const downloadArtifact = (type) => {
    fetchBlob(`/projects/${projectId}/assessments/${assessmentId}/artifacts/${type}`, `assessment-${assessmentId}-${type}.docx`)
  }

  const openFindingsWith = ({ status = '', review = false, dissents = false, changed = false } = {}) => {
    setStatusFilter(status)
    setFamilyFilter('')
    setSearchTerm('')
    setReviewAttentionFilter(review)
    setDissentOnlyFilter(dissents)
    setChangedOnlyFilter(changed)
    openFindingsView('flat')
  }

  const statusSummary = {
    pending: {
      title: 'Queued',
      body: 'This assessment exists, but processing has not started yet. When work begins, the page will switch to running and show the current control being evaluated.',
    },
    running: {
      title: 'Running',
      body: assessment?.progress_detail || 'The system is evaluating controls and evidence now.',
    },
    paused: {
      title: 'Paused',
      body: 'Processing is paused. Resume to continue the assessment from the current point.',
    },
    complete: {
      title: 'Complete',
      body: 'The run is complete. Review what needs attention and decide what happens next.',
    },
    failed: {
      title: 'Failed',
      body: assessment?.progress_detail || 'The run stopped before completion. Review the current findings, then retry or restart as needed.',
    },
  }[assessment?.status || 'pending']

  return (
    <div ref={pageTopRef} className="w-full max-w-[2200px] p-4 sm:p-6 lg:p-8">
      <div className="space-y-5">
        <div className="space-y-3">
          <Link
            to={`/projects/${projectId}`}
            className="inline-flex items-center gap-1 text-xs font-medium text-gray-400 hover:text-gray-600"
          >
            &lt;- Back to Project
          </Link>

          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-3xl font-bold text-gray-900">
                  {assessment?.name || `Assessment #${assessment?.project_run_number ?? assessmentId}`}
                </h1>
                <div className="shrink-0">
                  <PlainStatusPill
                    status={assessment?.status}
                    controlsComplete={displayedControlsComplete}
                    controlsTotal={displayedControlsTotal}
                  />
                </div>
                {assessment?.status === 'complete' && assessmentRollup?.readiness && (
                  <div className="shrink-0">
                    <RollupBadge readiness={assessmentRollup.readiness} />
                  </div>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {isRunning && (
                <button
                  type="button"
                  onClick={() => pauseAssessment.mutate()}
                  disabled={pauseAssessment.isPending}
                  className="inline-flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-60"
                >
                  <Pause size={15} />
                  {pauseAssessment.isPending ? 'Pausing...' : 'Pause'}
                </button>
              )}
              {isPaused && (
                <button
                  type="button"
                  onClick={() => resumeAssessment.mutate()}
                  disabled={resumeAssessment.isPending}
                  className="inline-flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-60"
                >
                  <RotateCcw size={15} />
                  {resumeAssessment.isPending ? 'Resuming...' : 'Resume'}
                </button>
              )}
              <button
                type="button"
                onClick={() => openWorkspaceFindings(findingsView || 'family')}
                className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                <LayoutList size={15} />
                Open Findings
              </button>
              {!isRunning && !isPaused && (
                <>
                  <button
                    type="button"
                    onClick={() => setActiveTab('outputs')}
                    className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                  >
                    <Download size={15} />
                    Export
                  </button>
                  {(pageCounts.not_reviewed || 0) > 0 && (
                    <button
                      type="button"
                      onClick={() => retryFailed.mutate()}
                      disabled={retryFailed.isPending || retrying}
                      className="inline-flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-60"
                    >
                      <RefreshCw size={15} className={(retryFailed.isPending || retrying) ? 'animate-spin' : ''} />
                      {retrying ? 'Retrying...' : retryFailed.isPending ? 'Queuing retry...' : `Retry ${pageCounts.not_reviewed} failed`}
                    </button>
                  )}
                </>
              )}
            </div>
          </div>

          <p className="text-sm leading-7 text-gray-700">
            {assessment?.status === 'complete' && assessmentRollup?.residual_risk_summary ? (
              <>
                <span className="font-semibold text-gray-900">Assessment Summary:</span>{' '}
                {assessmentRollup.residual_risk_summary}
              </>
            ) : (
              statusSummary?.body
            )}
          </p>
        </div>

        {activeTab !== 'overview' && (
          <AssessmentNavigationBar
            activeTab={activeTab}
            findingsView={findingsView}
            advancedView={advancedView}
            selectedFinding={selectedFinding}
            visibleFindingsCount={findings.length}
            evidenceCount={evidenceSources.length}
            advancedCount={dissentCount + changedFindings.length}
            onOpenOverview={() => setActiveTab('overview')}
            onOpenFindings={() => openWorkspaceFindings(findingsView || 'family')}
            onOpenEvidence={() => setActiveTab('evidence')}
            onOpenOutputs={() => setActiveTab('outputs')}
            onOpenAdvanced={() => openAdvancedView(advancedView || 'delta')}
            onClearSelection={() => setSelectedControlId(null)}
          />
        )}

        {activeTab === 'overview' && (
          <div className="space-y-5">
            <AssessmentNavigationBar
              activeTab={activeTab}
              findingsView={findingsView}
              advancedView={advancedView}
              selectedFinding={selectedFinding}
              visibleFindingsCount={findings.length}
              evidenceCount={evidenceSources.length}
              advancedCount={dissentCount + changedFindings.length}
              onOpenOverview={() => setActiveTab('overview')}
              onOpenFindings={() => openWorkspaceFindings(findingsView || 'family')}
              onOpenEvidence={() => setActiveTab('evidence')}
              onOpenOutputs={() => setActiveTab('outputs')}
              onOpenAdvanced={() => openAdvancedView(advancedView || 'delta')}
              onClearSelection={() => setSelectedControlId(null)}
            />

            <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(360px,0.7fr)]">
              <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Needs attention</p>
                    <p className="mt-1 text-sm text-gray-600">Start with the blockers, then use the review signals to validate where a human look is warranted.</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => openFindingsWith({ status: 'compliant' })}
                      className="rounded-full border border-emerald-200 bg-emerald-50 px-6 py-2 text-left text-lg font-semibold text-emerald-700 hover:bg-emerald-100 min-w-[180px]"
                    >
                      {pageCounts.compliant || 0} passed
                    </button>
                    <details className="relative">
                      <summary className="list-none cursor-pointer rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100">
                        Run details
                      </summary>
                      <div className="absolute right-0 z-10 mt-2 w-[320px] rounded-xl border border-gray-200 bg-white p-4 shadow-lg">
                        <div className="space-y-3 text-sm text-gray-600">
                          <div>
                            <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Timing</p>
                            <p className="mt-1 text-sm text-gray-900">
                              {assessment?.started_at ? `Started ${fmt12hr(assessment.started_at)}` : 'Not started yet'}
                            </p>
                            <p className="mt-1 text-xs text-gray-500">
                              {duration || (assessment?.completed_at ? `Completed ${fmt12hr(assessment.completed_at)}` : 'No completed duration yet')}
                            </p>
                          </div>
                          <div>
                            <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Runtime</p>
                            <p className="mt-1 text-sm text-gray-900">{assessment?.llm_provider} / {assessment?.llm_model}</p>
                            <p className="mt-1 text-xs text-gray-500">{assessment?.context_strategy || 'Context strategy unavailable'}</p>
                          </div>
                        </div>
                      </div>
                    </details>
                  </div>
                </div>
                <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
                  <div className="space-y-3">
                    <button
                      type="button"
                      onClick={() => openFindingsWith({ status: 'non_compliant' })}
                      className="w-full rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-left hover:bg-red-100"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-red-700">Priority 1</p>
                          <p className="mt-1 text-base font-semibold text-red-950">Non-compliant controls</p>
                          <p className="mt-1 text-sm text-red-800">These are the clearest blockers to an authorization decision.</p>
                        </div>
                        <div className="text-right">
                          <p className="text-3xl font-bold leading-none text-red-800">{pageCounts.non_compliant || 0}</p>
                        </div>
                      </div>
                    </button>

                    <button
                      type="button"
                      onClick={() => openFindingsWith({ status: 'partially_compliant' })}
                      className="w-full rounded-xl border border-amber-200 bg-amber-50 px-4 py-4 text-left hover:bg-amber-100"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700">Priority 2</p>
                          <p className="mt-1 text-base font-semibold text-amber-950">Partial controls</p>
                          <p className="mt-1 text-sm text-amber-800">Evidence exists, but the record is not strong enough to close cleanly.</p>
                        </div>
                        <div className="text-right">
                          <p className="text-3xl font-bold leading-none text-amber-800">{pageCounts.partially_compliant || 0}</p>
                        </div>
                      </div>
                    </button>
                  </div>

                  <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-4">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Review signals</p>
                    <p className="mt-1 text-sm text-gray-600">Use these to decide where an assessor should challenge, validate, or explain the current determination.</p>
                    <div className="mt-4 space-y-3">
                      <button
                        type="button"
                        onClick={() => openFindingsWith({ review: true })}
                        className="flex w-full items-center justify-between rounded-xl border border-violet-200 bg-white px-4 py-3 text-left hover:bg-violet-50"
                      >
                        <div>
                          <p className="text-sm font-semibold text-violet-900">Controls needing review</p>
                          <p className="mt-1 text-xs text-violet-700">Evidence pattern needs human judgment.</p>
                        </div>
                        <span className="text-2xl font-bold text-violet-800">{reviewAttentionCount}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => openAdvancedView('dissents')}
                        className="flex w-full items-center justify-between rounded-xl border border-blue-200 bg-white px-4 py-3 text-left hover:bg-blue-50"
                      >
                        <div>
                          <p className="text-sm font-semibold text-blue-900">AI dissents</p>
                          <p className="mt-1 text-xs text-blue-700">Secondary review disagreed with the verdict.</p>
                        </div>
                        <span className="text-2xl font-bold text-blue-800">{dissentCount}</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div className="space-y-5">
                <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Next actions</p>
                  <div className="mt-4 space-y-2">
                    <button type="button" onClick={() => openWorkspaceFindings(findingsView || 'family')} className="flex w-full items-center justify-between rounded-xl border border-gray-200 px-4 py-3 text-left hover:bg-gray-50">
                      <div>
                        <p className="text-sm font-semibold text-gray-900">Continue findings review</p>
                        <p className="mt-1 text-xs text-gray-500">Inspect one control at a time with the new side panel.</p>
                      </div>
                      <ArrowUpRight size={15} className="text-gray-400" />
                    </button>
                    <button type="button" onClick={() => setActiveTab('evidence')} className="flex w-full items-center justify-between rounded-xl border border-gray-200 px-4 py-3 text-left hover:bg-gray-50">
                      <div>
                        <p className="text-sm font-semibold text-gray-900">Inspect evidence traceability</p>
                        <p className="mt-1 text-xs text-gray-500">See what was cited, what was missing, and how to explain the result.</p>
                      </div>
                      <ArrowUpRight size={15} className="text-gray-400" />
                    </button>
                    <button type="button" onClick={() => setActiveTab('outputs')} className="flex w-full items-center justify-between rounded-xl border border-gray-200 px-4 py-3 text-left hover:bg-gray-50">
                      <div>
                        <p className="text-sm font-semibold text-gray-900">Export reports and outputs</p>
                        <p className="mt-1 text-xs text-gray-500">Download reports or continue into remediation and closure tools.</p>
                      </div>
                      <ArrowUpRight size={15} className="text-gray-400" />
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {assessment?.status === 'complete' && (
              <AssessmentRollupCard
                projectId={projectId}
                assessmentId={assessmentId}
                assessmentStatus={assessment?.status}
                assessment={assessment}
                editingNotes={editingNotes}
                setEditingNotes={setEditingNotes}
                notesText={notesText}
                setNotesText={setNotesText}
                updateAssessmentNotes={updateAssessmentNotes}
                pageCounts={pageCounts}
                findings={findings}
                reviewAttentionCount={reviewAttentionCount}
                dissentCount={dissentCount}
                onOpenDissents={() => openAdvancedView('dissents')}
                onOpenNeedsReview={() => openFindingsWith({ review: true })}
              />
            )}

            {(pageCounts.not_reviewed || 0) > 0 && !isRunning && (
              <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-amber-900">
                      {retrying ? `Retrying controls - ${pageCounts.not_reviewed} still pending` : `${pageCounts.not_reviewed} controls still need a completed result`}
                    </p>
                    <p className="mt-1 text-xs text-amber-700">
                      Use retry to rerun the controls that did not finish cleanly. If they fail again, you can send them to manual review from the findings workflow.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => retryFailed.mutate()}
                    disabled={retryFailed.isPending || retrying}
                    className="inline-flex items-center gap-2 rounded-xl bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-60"
                  >
                    <RefreshCw size={14} className={(retryFailed.isPending || retrying) ? 'animate-spin' : ''} />
                    {retrying ? 'Retrying...' : 'Retry failed controls'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'findings' && (
          <div className="space-y-4">
            <div>
              <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Findings workflow</p>
                    <p className="mt-1 text-sm text-gray-600">Filter the findings list, choose a control, and review the reasoning without leaving the page.</p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setFindingsView('family')}
                      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium ${findingsView === 'family' ? 'border-blue-700 bg-blue-700 text-white' : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}
                    >
                      <LayoutList size={14} />
                      Family
                    </button>
                    <button
                      type="button"
                      onClick={() => setFindingsView('flat')}
                      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium ${findingsView === 'flat' ? 'border-blue-700 bg-blue-700 text-white' : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}
                    >
                      <Rows3 size={14} />
                      Flat
                    </button>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_repeat(3,minmax(0,0.8fr))]">
                  <input
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder="Search by control ID, title, or family"
                    className="rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-700 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
                  />
                  <select
                    value={familyFilter}
                    onChange={(e) => setFamilyFilter(e.target.value)}
                    className="rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-700 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
                  >
                    <option value="">All families</option>
                    {families.map(family => (
                      <option key={family} value={family}>{family} - {FAMILY_NAMES[family] || family}</option>
                    ))}
                  </select>
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className="rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-700 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
                  >
                    <option value="">All determinations</option>
                    {Object.entries(STATUS_CONFIG).map(([key, cfg]) => (
                      <option key={key} value={key}>{cfg.label}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => {
                      setSearchTerm('')
                      setFamilyFilter('')
                      setStatusFilter('')
                      setReviewAttentionFilter(false)
                      setDissentOnlyFilter(false)
                      setChangedOnlyFilter(false)
                    }}
                    className="rounded-xl border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                  >
                    Clear filters
                  </button>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  {Object.entries(STATUS_CONFIG).map(([key, cfg]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => {
                        setStatusFilter(statusFilter === key ? '' : key)
                        setReviewAttentionFilter(false)
                        setDissentOnlyFilter(false)
                        setChangedOnlyFilter(false)
                      }}
                      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium ${
                        statusFilter === key ? `${cfg.cardBorder} ${cfg.cardBg}` : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      <span className={`h-2 w-2 rounded-full ${cfg.dot}`} />
                      {cfg.label}
                      <span className="font-semibold text-gray-700">{pageCounts[key] || 0}</span>
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => {
                      setStatusFilter('')
                      setDissentOnlyFilter(false)
                      setChangedOnlyFilter(false)
                      setReviewAttentionFilter((current) => !current)
                    }}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium ${
                      reviewAttentionFilter ? 'border-amber-300 bg-amber-100 text-amber-900' : 'border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100'
                    }`}
                  >
                    <Wrench size={12} />
                    Needs review
                    <span className="font-semibold">{reviewAttentionCount}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setStatusFilter('')
                      setReviewAttentionFilter(false)
                      setChangedOnlyFilter(false)
                      setDissentOnlyFilter((current) => !current)
                    }}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium ${
                      dissentOnlyFilter ? 'border-violet-300 bg-violet-100 text-violet-900' : 'border-violet-200 bg-violet-50 text-violet-800 hover:bg-violet-100'
                    }`}
                  >
                    <Scale size={12} />
                    AI dissent
                    <span className="font-semibold">{dissentCount}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setStatusFilter('')
                      setReviewAttentionFilter(false)
                      setDissentOnlyFilter(false)
                      setChangedOnlyFilter((current) => !current)
                    }}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium ${
                      changedOnlyFilter ? 'border-blue-300 bg-blue-100 text-blue-900' : 'border-blue-200 bg-blue-50 text-blue-800 hover:bg-blue-100'
                    }`}
                  >
                    <RefreshCw size={12} />
                    Changed
                    <span className="font-semibold">{changedFindings.length}</span>
                  </button>
                </div>
              </div>

              <SelectedControlContextBar
                finding={selectedFinding}
                onClear={() => setSelectedControlId(null)}
                helperText="The findings list is assessment-wide. Select a control when you want to move from assessment review into control-specific detail."
              />

              {findingsView === 'family' ? (
                <div>
                  {visibleFamilies.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center text-sm text-gray-500">
                      {isRunning ? 'Assessment in progress. Completed controls will appear here as the run advances.' : 'No findings match the current filters.'}
                    </div>
                  ) : visibleFamilies.map(family => (
                    <FamilyRollup
                      key={family}
                      family={family}
                      findings={visibleByFamily[family]}
                      defaultOpen={visibleFamilies.length === 1}
                      onManualReview={setManualReviewFinding}
                      projectId={projectId}
                      assessmentId={assessmentId}
                      onFindingUpdate={onFindingUpdate}
                      overrideMap={overrideMap}
                      onUpsert={handleUpsert}
                      onExpand={refetchFindings}
                      docMap={docMap}
                      onAskAssistant={openAssistantForFinding}
                      onSelectControl={setSelectedControlId}
                      selectedControlId={selectedControlId}
                    />
                  ))}
                </div>
              ) : (
                <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 border-b border-gray-200">
                      <tr>
                        <th className="px-4 py-3 text-left font-medium text-gray-600 w-16">Family</th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600 w-28">Control</th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600">Title</th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600 w-32">Status</th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600 w-24">Confidence</th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600 w-24">Evidence</th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600 w-32">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedVisibleFindings.map(f => (
                        <tr
                          key={f.id}
                          onClick={() => setSelectedControlId(f.control_id)}
                          className={`border-b border-gray-100 cursor-pointer ${selectedControlId === f.control_id ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
                        >
                          <td className="px-4 py-3 font-mono text-xs text-gray-500">{f.control_family}</td>
                          <td className="px-4 py-3 font-mono text-xs font-semibold text-blue-700">
                            <span className="inline-flex items-center gap-1">
                              <span>{f.control_id}<OverrideIndicator override={overrideMap[f.control_id]} /></span>
                              <ControlReferenceButton controlId={f.control_id} iconOnly />
                            </span>
                          </td>
                          <td className="px-4 py-3 text-gray-800">
                            <div>{f.control_title}</div>
                            <OverrideBadges f={f} />
                          </td>
                          <td className="px-4 py-3"><StatusBadge status={f.status} override={overrideMap[f.control_id]} /></td>
                          <td className="px-4 py-3 text-xs text-gray-500">{f.confidence_score != null ? `${Math.round(f.confidence_score * 100)}%` : '-'}</td>
                          <td className="px-4 py-3 text-xs text-gray-500">{f.evidence_citations?.length || 0}</td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              {(f.status === 'not_reviewed' || needsDisplayReview(f)) && (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    setManualReviewFinding(f)
                                  }}
                                  className="text-amber-700 hover:text-amber-900"
                                  title="Manual review"
                                >
                                  <Wrench size={13} />
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  openAssistantForFinding(f)
                                }}
                                className="text-violet-600 hover:text-violet-800"
                                title="Ask AI about this control"
                              >
                                <MessageSquare size={13} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'evidence' && (
          <div className="space-y-4">
            {selectedFinding ? (
              <>
                <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Evidence review</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-bold text-blue-700">{selectedFinding.control_id}</span>
                        <StatusBadge status={selectedFinding.status} override={overrideMap[selectedFinding.control_id]} />
                        <span className="text-sm text-gray-700">{selectedFinding.control_title}</span>
                      </div>
                      <p className="mt-3 text-sm text-gray-600">
                        This view answers what evidence was used, what was missing, and what the system inferred from the source material.
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => openAdvancedView('workbench')}
                        className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                      >
                        Open advanced control detail
                      </button>
                      <button
                        type="button"
                        onClick={() => setSelectedControlId(null)}
                        className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                      >
                        Clear selection
                      </button>
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full bg-blue-50 px-2.5 py-1 font-medium text-blue-700">
                      {evidenceSources.length} total source records
                    </span>
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-700">
                      {selectedFinding.evidence_citations?.length || 0} selected control citations
                    </span>
                    <span className={`rounded-full px-2.5 py-1 font-medium ${selectedFinding.llm_challenge_note ? 'bg-violet-100 text-violet-700' : 'bg-gray-100 text-gray-600'}`}>
                      AI dissent on selected control: {selectedFinding.llm_challenge_note ? 'Yes' : 'No'}
                    </span>
                  </div>
                </div>

                <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Cited sources</p>
                  <div className="mt-3">
                    <EvidenceCitations
                      citations={selectedFinding.evidence_citations}
                      docMap={docMap}
                      projectId={projectId}
                      assessmentId={assessmentId}
                      controlId={selectedFinding.control_id}
                      controlTitle={selectedFinding.control_title}
                    />
                  </div>
                </div>

                <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Evidence interpretation</p>
                  <div className="mt-3 space-y-3 text-sm text-gray-700">
                    {selectedFinding.implementation_statement ? (
                      <TextBlock text={selectedFinding.implementation_statement} />
                    ) : (
                      <p>No narrative interpretation is stored for this control.</p>
                    )}
                    {selectedFinding.gaps?.length > 0 && (
                      <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-red-700 mb-2">Missing or weak evidence</p>
                        <ul className="space-y-2">
                          {selectedFinding.gaps.map((gap, index) => (
                            <li key={`${selectedFinding.id}-evidence-gap-${index}`} className="flex gap-2 text-sm text-red-900">
                              <span className="mt-1 h-1.5 w-1.5 rounded-full bg-red-500" />
                              <span>{String(gap).replace(/\\n/g, '\n')}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <>
                <SelectedControlContextBar
                  finding={selectedFinding}
                  onClear={() => setSelectedControlId(null)}
                  helperText="Evidence starts at the assessment level here. Select a control from Findings when you want to inspect control-specific citations and rationale."
                />

                <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Assessment-wide evidence summary</p>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-4">
                      <p className="text-sm font-semibold text-blue-900">Evidence sources</p>
                      <p className="mt-2 text-2xl font-bold text-blue-800">{evidenceSources.length}</p>
                      <p className="mt-1 text-xs text-blue-700">Indexed source records available to support assessment decisions.</p>
                    </div>
                    <div className="rounded-xl border border-violet-200 bg-violet-50 px-4 py-4">
                      <p className="text-sm font-semibold text-violet-900">Controls with review needs</p>
                      <p className="mt-2 text-2xl font-bold text-violet-800">{reviewAttentionCount}</p>
                      <p className="mt-1 text-xs text-violet-700">Controls where the evidence trail needs a human look.</p>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {activeTab === 'outputs' && (
          <div className="space-y-5">
            <AssessmentFinalization
              projectId={projectId}
              assessmentId={assessmentId}
              assessment={assessment}
            />
            <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Exports and downstream work</p>
              <p className="mt-2 text-sm text-gray-600">
                Use this area for report export, generated plan artifacts, and remediation or closure workflows that follow the assessment.
              </p>
              <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {['excel', 'word', 'pptx', 'json'].map(fmt => (
                  <button
                    key={fmt}
                    type="button"
                    onClick={() => downloadReport(fmt)}
                    disabled={assessment?.finalization_status !== 'finalized'}
                    className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-4 text-left hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    <p className="text-sm font-semibold text-gray-900">{fmt.toUpperCase()} report</p>
                    <p className="mt-1 text-xs text-gray-500">{assessment?.finalization_status === 'finalized' ? 'Download the finalized assessment report.' : 'Locked until human review and finalization are complete.'}</p>
                  </button>
                ))}
                <button type="button" onClick={() => downloadArtifact('contingency-plan')} className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-4 text-left hover:bg-blue-100">
                  <p className="text-sm font-semibold text-blue-900">Contingency plan</p>
                  <p className="mt-1 text-xs text-blue-700">Download the generated contingency plan artifact.</p>
                </button>
                <button type="button" onClick={() => downloadArtifact('incident-response-plan')} className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-4 text-left hover:bg-blue-100">
                  <p className="text-sm font-semibold text-blue-900">Incident response plan</p>
                  <p className="mt-1 text-xs text-blue-700">Download the generated incident response plan artifact.</p>
                </button>
                <button type="button" disabled={assessment?.finalization_status !== 'finalized'} onClick={() => downloadArtifact('sar')} className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-4 text-left hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-45">
                  <p className="text-sm font-semibold text-blue-900">Security assessment report</p>
                  <p className="mt-1 text-xs text-blue-700">{assessment?.finalization_status === 'finalized' ? 'Download the finalized SAR document.' : 'Locked until human review and finalization are complete.'}</p>
                </button>
              </div>
            </div>

            {assessment?.status === 'complete' ? (
              <RemediationView
                projectId={projectId}
                assessmentId={assessmentId}
                findings={findings}
              />
            ) : (
              <div className="rounded-2xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center text-sm text-gray-500">
                Remediation and closure tools become most useful after the assessment is complete.
              </div>
            )}
          </div>
        )}

        {activeTab === 'advanced' && (
          <div className="space-y-4">
            <SelectedControlContextBar
              finding={selectedFinding}
              onClear={() => setSelectedControlId(null)}
              helperText="Advanced tools can stay assessment-wide, but control workbench detail only appears after you intentionally select a control from Findings."
            />

            <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => setAdvancedView('delta')} className={`rounded-lg border px-3 py-2 text-sm font-medium ${advancedView === 'delta' ? 'border-blue-700 bg-blue-700 text-white' : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}>Change Since Prior Run</button>
                <button type="button" onClick={() => setAdvancedView('dissents')} className={`rounded-lg border px-3 py-2 text-sm font-medium ${advancedView === 'dissents' ? 'border-violet-700 bg-violet-700 text-white' : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}>AI Dissent</button>
                <button type="button" onClick={() => setAdvancedView('workbench')} className={`rounded-lg border px-3 py-2 text-sm font-medium ${advancedView === 'workbench' ? 'border-blue-700 bg-blue-700 text-white' : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}>Decision Mechanics</button>
                <button type="button" onClick={() => setAdvancedView('review')} className={`rounded-lg border px-3 py-2 text-sm font-medium ${advancedView === 'review' ? 'border-blue-700 bg-blue-700 text-white' : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}>Keyboard Review</button>
                <button type="button" onClick={() => setAdvancedView('system')} className={`rounded-lg border px-3 py-2 text-sm font-medium ${advancedView === 'system' ? 'border-sky-700 bg-sky-700 text-white' : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}>System Knowledge</button>
              </div>
            </div>

            {advancedView === 'delta' && (
              <div>
                <h2 className="mb-3 text-base font-semibold text-gray-700">Changes vs Previous Run</h2>
                <DeltaView findings={findings} />
              </div>
            )}

            {advancedView === 'dissents' && (
              <DissentView
                findings={findings}
                onDiscuss={(finding) => openAssistantForFinding(finding, {
                  initialPrompt: 'Please explain your challenge to this verdict, which objectives you questioned, and what evidence would change the outcome.',
                  hiddenInitialMessage: true,
                })}
              />
            )}

            {advancedView === 'review' && (
              <KeyboardReview
                findings={findings}
                overrideMap={overrideMap}
                onUpsert={handleUpsert}
                projectId={projectId}
                assessmentId={assessmentId}
                onFindingUpdate={onFindingUpdate}
                docMap={docMap}
              />
            )}

            {advancedView === 'workbench' && (
              selectedFinding ? (
                <div className="space-y-3">
                  <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Advanced control detail</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-bold text-blue-700">{selectedFinding.control_id}</span>
                      <StatusBadge status={selectedFinding.status} override={overrideMap[selectedFinding.control_id]} />
                      <span className="text-sm text-gray-700">{selectedFinding.control_title}</span>
                    </div>
                  </div>
                  <ControlDetail
                    f={selectedFinding}
                    projectId={projectId}
                    assessmentId={assessmentId}
                    onFindingUpdate={onFindingUpdate}
                    override={overrideMap[selectedFinding.control_id]}
                    onUpsert={(body) => handleUpsert(selectedFinding.control_id, body)}
                    docMap={docMap}
                  />
                </div>
              ) : (
                <div className="rounded-2xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center text-sm text-gray-500">
                  Select a control in Findings to open the advanced decision mechanics workbench.
                </div>
              )
            )}

            {advancedView === 'system' && (
              <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Derived system knowledge</p>
                {(systemKnowledge.tool_count || systemKnowledge.assertion_count) ? (
                  <div className="mt-4 grid gap-4 xl:grid-cols-2">
                    <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-4">
                      <p className="text-sm font-semibold text-sky-900">Observed tools</p>
                      <p className="mt-2 text-sm text-sky-800">
                        {(systemKnowledge.tools || []).map((t) => t.tool_name).slice(0, 10).join(', ') || 'No tools detected yet.'}
                      </p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
                      <p className="text-sm font-semibold text-slate-900">Knowledge coverage</p>
                      <ul className="mt-2 space-y-1 text-sm text-slate-700">
                        <li>Tools detected: {systemKnowledge.tool_count || 0}</li>
                        <li>Assertions captured: {systemKnowledge.assertion_count || 0}</li>
                        <li>Evidence sources: {evidenceSources.length}</li>
                      </ul>
                    </div>
                  </div>
                ) : (
                  <p className="mt-3 text-sm text-gray-500">No derived system knowledge has been recorded for this assessment yet.</p>
                )}
              </div>
            )}
          </div>
        )}

        {manualReviewFinding && (
          <ManualReviewModal
            finding={manualReviewFinding}
            projectId={projectId}
            assessmentId={assessmentId}
            onClose={() => setManualReviewFinding(null)}
            onSaved={() => {
              qc.invalidateQueries({ queryKey: ['findings', assessmentId] })
              qc.invalidateQueries({ queryKey: ['assessment', assessmentId] })
              qc.invalidateQueries({ queryKey: ['assessment-rollup', assessmentId] })
            }}
          />
        )}

        {activeTab === 'findings' && selectedFinding && (
          <SelectedControlPanel
            finding={selectedFinding}
            override={overrideMap[selectedFinding.control_id]}
            projectId={projectId}
            assessmentId={assessmentId}
            onFindingUpdate={onFindingUpdate}
            onUpsert={(body) => handleUpsert(selectedFinding.control_id, body)}
            docMap={docMap}
            onManualReview={setManualReviewFinding}
            onDiscuss={() => openAssistantForFinding(selectedFinding, {
              initialPrompt: 'Please explain the current determination, the cited evidence, and what would materially change the result.',
              hiddenInitialMessage: true,
            })}
            onClose={() => setSelectedControlId(null)}
          />
        )}
      </div>
    </div>
  )
}
