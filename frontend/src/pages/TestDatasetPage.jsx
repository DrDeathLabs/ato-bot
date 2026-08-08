/**
 * TestDatasetPage — Standalone tool for generating a complete fictitious
 * ATO evidence package for testing the assessment engine end-to-end.
 */
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Play, RefreshCw, Trash2, Clock, CheckCircle2,
  XCircle, AlertTriangle, File, ChevronDown, ChevronRight,
  Database, Loader2, BookOpen, ClipboardList, FlaskConical, FileCode,
  GraduationCap, History, BarChart2
} from 'lucide-react'
import api from '../api/client'

// ── Type badge config ─────────────────────────────────────────────────────────
const TYPE_CONFIG = {
  policy: {
    label: 'Policy',
    bg: 'bg-blue-100',
    text: 'text-blue-700',
    icon: BookOpen,
  },
  procedure: {
    label: 'Procedure',
    bg: 'bg-green-100',
    text: 'text-green-700',
    icon: ClipboardList,
  },
  technical_artifact: {
    label: 'Technical Artifact',
    bg: 'bg-orange-100',
    text: 'text-orange-700',
    icon: FileCode,
  },
  ssp_narrative: {
    label: 'SSP Narrative',
    bg: 'bg-purple-100',
    text: 'text-purple-700',
    icon: File,
  },
  training_record: {
    label: 'Training Record',
    bg: 'bg-pink-100',
    text: 'text-pink-700',
    icon: GraduationCap,
  },
}

const OUTCOME_OPTIONS = [
  { value: 'compliant', label: 'Compliant' },
  { value: 'partially_compliant', label: 'Partial' },
  { value: 'non_compliant', label: 'Non-Compliant' },
]

function createEmptyFamilyOverride() {
  return {
    family: '',
    satisfied_pct: '',
    partial_pct: '',
    failed_pct: '',
  }
}

function createEmptyControlOverride() {
  return {
    control_id: '',
    status: 'compliant',
  }
}

function toNumberOrUndefined(value) {
  if (value === '' || value === null || value === undefined) return undefined
  const num = Number(value)
  return Number.isFinite(num) ? num : undefined
}

function buildFamilyOverrides(rows) {
  const overrides = {}
  for (const row of rows) {
    const family = String(row.family || '').trim().toUpperCase()
    if (!family) continue
    overrides[family] = {
      ...(toNumberOrUndefined(row.satisfied_pct) !== undefined ? { satisfied_pct: toNumberOrUndefined(row.satisfied_pct) } : {}),
      ...(toNumberOrUndefined(row.partial_pct) !== undefined ? { partial_pct: toNumberOrUndefined(row.partial_pct) } : {}),
      ...(toNumberOrUndefined(row.failed_pct) !== undefined ? { failed_pct: toNumberOrUndefined(row.failed_pct) } : {}),
    }
  }
  return overrides
}

function buildControlOverrides(rows) {
  const overrides = {}
  for (const row of rows) {
    const controlId = String(row.control_id || '').trim().toUpperCase()
    const status = String(row.status || '').trim()
    if (!controlId || !status) continue
    overrides[controlId] = status
  }
  return overrides
}

function TypeBadge({ type }) {
  const cfg = TYPE_CONFIG[type] || {
    label: type || 'Document',
    bg: 'bg-gray-100',
    text: 'text-gray-600',
    icon: File,
  }
  const Icon = cfg.icon
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${cfg.bg} ${cfg.text}`}>
      <Icon size={11} />
      {cfg.label}
    </span>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const configs = {
    pending: { color: 'bg-yellow-100 text-yellow-700', icon: <Clock size={12} />, label: 'Pending' },
    running: { color: 'bg-blue-100 text-blue-700', icon: <Loader2 size={12} className="animate-spin" />, label: 'Running' },
    completed: { color: 'bg-green-100 text-green-700', icon: <CheckCircle2 size={12} />, label: 'Completed' },
    failed: { color: 'bg-red-100 text-red-700', icon: <XCircle size={12} />, label: 'Failed' },
    cancelled: { color: 'bg-gray-100 text-gray-500', icon: <XCircle size={12} />, label: 'Cancelled' },
  }
  const cfg = configs[status] || configs.pending
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full ${cfg.color}`}>
      {cfg.icon}
      {cfg.label}
    </span>
  )
}

function formatSeconds(value) {
  const secs = Number(value)
  if (!Number.isFinite(secs) || secs < 0) return 'n/a'
  if (secs < 60) return `${secs.toFixed(1)}s`
  return `${(secs / 60).toFixed(1)}m`
}

function countObjectKeys(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return 0
  return Object.keys(value).length
}

// ── Artifact accordion row ────────────────────────────────────────────────────
function ArtifactRow({ artifact }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center gap-3 px-4 py-3 bg-white hover:bg-gray-50 transition-colors text-left"
        onClick={() => setOpen(v => !v)}
      >
        {open ? <ChevronDown size={15} className="text-gray-400 flex-shrink-0" /> : <ChevronRight size={15} className="text-gray-400 flex-shrink-0" />}
        <span className="font-mono text-xs text-gray-500 flex-shrink-0 w-20">{artifact.control_id || artifact.bundle_id || artifact.family}</span>
        <span className="text-sm text-gray-800 flex-1 truncate">{artifact.title}</span>
        <TypeBadge type={artifact.document_type} />
        {artifact.indexed ? (
          <span className="text-xs text-green-600 ml-2 flex-shrink-0">indexed</span>
        ) : (
          <span className="text-xs text-gray-400 ml-2 flex-shrink-0">pending index</span>
        )}
      </button>
      {open && (
        <div className="bg-gray-50 px-4 pb-3 pt-2 border-t border-gray-100 text-sm text-gray-600 space-y-1">
          {artifact.filename && <p><span className="font-medium text-gray-700">Filename:</span> {artifact.filename}</p>}
          {artifact.family && <p><span className="font-medium text-gray-700">Family:</span> {artifact.family}</p>}
          {artifact.controls_addressed?.length > 0 && <p><span className="font-medium text-gray-700">Controls:</span> {artifact.controls_addressed.join(', ')}</p>}
          {artifact.doc_id && <p><span className="font-medium text-gray-700">Document ID:</span> {artifact.doc_id}</p>}
        </div>
      )}
    </div>
  )
}

// ── Family group ──────────────────────────────────────────────────────────────
function FamilyGroup({ family, artifacts }) {
  const [open, setOpen] = useState(true)
  const typeCount = artifacts.reduce((acc, a) => {
    acc[a.document_type] = (acc[a.document_type] || 0) + 1
    return acc
  }, {})

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center gap-3 px-5 py-3.5 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
        onClick={() => setOpen(v => !v)}
      >
        {open ? <ChevronDown size={16} className="text-gray-500 flex-shrink-0" /> : <ChevronRight size={16} className="text-gray-500 flex-shrink-0" />}
        <span className="font-semibold text-gray-800 flex-1">{family}</span>
        <span className="text-xs text-gray-500 mr-2">{artifacts.length} document{artifacts.length !== 1 ? 's' : ''}</span>
        <div className="flex gap-1.5">
          {Object.entries(typeCount).map(([type, count]) => {
            const cfg = TYPE_CONFIG[type] || { bg: 'bg-gray-100', text: 'text-gray-500', label: type }
            return (
              <span key={type} className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg.bg} ${cfg.text}`}>
                {count} {cfg.label}
              </span>
            )
          })}
        </div>
      </button>
      {open && (
        <div className="divide-y divide-gray-100">
          {artifacts.map((art, i) => (
            <ArtifactRow key={i} artifact={art} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Results panel ─────────────────────────────────────────────────────────────
function ResultsPanel({ job }) {
  const artifacts = job.artifacts || []
  const summary = job.summary || {}
  const blueprint = job.blueprint || {}
  const validation = job.validation || {}
  const artifactValidation = job.artifact_validation || {}
  const systemKnowledge = job.system_knowledge || {}
  const timing = job.timing || {}
  const expected = job.expected_outcomes?.summary || {}
  const controlOverrides = job.expected_outcomes?.control_overrides || {}
  const invalidControlOverrides = job.expected_outcomes?.invalid_control_overrides || {}
  const benchmark = job.benchmark
  const calibration = job.calibration
  const evidenceRoleCounts = blueprint.summary?.evidence_role_counts || {}
  const recipeName = blueprint.summary?.recipe_name || validation.recipe_name || 'standard'

  if (artifacts.length === 0) {
    return (
      <div className="text-center py-10 text-gray-400 text-sm">
        No artifacts generated yet.
      </div>
    )
  }

  // Group by family
  const byFamily = {}
  for (const art of artifacts) {
    const fam = art.family || art.control_id?.slice(0, art.control_id.indexOf('-')) || 'Other'
    if (!byFamily[fam]) byFamily[fam] = []
    byFamily[fam].push(art)
  }
  const families = Object.keys(byFamily).sort()

  return (
    <div className="space-y-4">
      {job.config && Object.keys(job.config).length > 0 && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4 text-sm text-indigo-900">
          <p className="font-semibold mb-1">Run Configuration</p>
          <p>
            Style: <span className="font-medium">{job.config.package_style || 'standard'}</span>
            {' '}· Evidence mix: <span className="font-medium">{job.config.evidence_mix || 'balanced'}</span>
            {' '}· Expected profile: <span className="font-medium">{job.config.target_profile || 'passing_ato'}</span>
          </p>
        </div>
      )}

      {/* Summary row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Total Documents', value: summary.total_docs ?? artifacts.length, color: 'text-violet-700' },
          { label: 'Policies', value: summary.policy ?? artifacts.filter(a => a.document_type === 'policy').length, color: 'text-blue-600' },
          { label: 'Procedures', value: summary.procedure ?? artifacts.filter(a => a.document_type === 'procedure').length, color: 'text-green-600' },
          { label: 'Technical', value: summary.technical_artifact ?? artifacts.filter(a => a.document_type === 'technical_artifact').length, color: 'text-orange-600' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-white border border-gray-200 rounded-xl p-4 text-center">
            <p className={`text-2xl font-bold ${color}`}>{value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Blueprint</p>
          <p className="text-sm text-gray-800">{blueprint.summary?.bundle_count || 0} planned package components</p>
          <p className="text-xs text-gray-500 mt-1">Recipe: {recipeName === 'first_pass_technical' ? 'first-pass technical' : recipeName}</p>
          <p className="text-xs text-gray-500 mt-1">Implemented controls: {blueprint.summary?.controls_in_implemented_bundles || 0}</p>
          <p className="text-xs text-gray-500 mt-1">Gap register controls: {blueprint.summary?.controls_in_gap_register || 0}</p>
          <p className="text-xs text-gray-500 mt-1">Technical bundles: {blueprint.summary?.technical_bundle_count || 0}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Expected Outcomes</p>
          <p className="text-xs text-gray-600">Compliant: {expected.compliant || 0}</p>
          <p className="text-xs text-gray-600 mt-1">Partial: {expected.partially_compliant || 0}</p>
          <p className="text-xs text-gray-600 mt-1">Non-Compliant: {expected.non_compliant || 0}</p>
          <p className="text-xs text-gray-500 mt-2">
            Family overrides: {expected.family_override_count || 0}
            {' '}· Control overrides: {expected.control_override_count || 0}
          </p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Validation</p>
          <p className="text-sm text-gray-800">{validation.bundle_count || 0} bundles across {validation.families_covered?.length || 0} families</p>
          <p className="text-xs text-gray-500 mt-1">Status: {validation.status || 'pending'}</p>
          <p className="text-xs text-gray-500 mt-1">
            Roles: impl {evidenceRoleCounts.implementation || 0}
            {' '}· val {evidenceRoleCounts.validation || 0}
            {' '}· arch {evidenceRoleCounts.architecture || 0}
            {' '}· gov {evidenceRoleCounts.governance || 0}
          </p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Artifact Readiness</p>
          <p className="text-sm text-gray-800">{artifactValidation.retrieval_viable || 0} of {artifactValidation.document_count || 0} docs ready</p>
          <p className="text-xs text-gray-500 mt-1">Viability: {artifactValidation.package_viability?.viability_score ?? 0}%</p>
          <p className="text-xs text-gray-500 mt-1">Weak docs: {artifactValidation.weak_documents_count || 0}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Timing</p>
          <p className="text-sm text-gray-800">Total: {formatSeconds(timing.total_secs)}</p>
          <p className="text-xs text-gray-500 mt-1">Generate: {formatSeconds(timing.generation_secs)}</p>
          <p className="text-xs text-gray-500 mt-1">Validate + knowledge: {formatSeconds((timing.artifact_validation_secs || 0) + (timing.system_knowledge_secs || 0))}</p>
        </div>
      </div>

      {benchmark && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm text-emerald-900">
          <p className="font-semibold mb-1">Benchmark Comparison</p>
          <p>
            Latest complete assessment #{benchmark.assessment_id} matched
            {' '}<span className="font-semibold">{benchmark.match_pct}%</span> of the expected control outcomes.
          </p>
          <p className="text-xs text-emerald-700 mt-1">
            {benchmark.mismatch_count || 0} mismatches detected against the intended package profile.
          </p>
        </div>
      )}

      {calibration?.summary && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-sm text-blue-900">
          <p className="font-semibold mb-1">Persistent Calibration Run</p>
          <p>
            Latest calibration matched <span className="font-semibold">{calibration.summary.match_pct || 0}%</span>
            {' '}of expected outcomes across {calibration.summary.total_controls || 0} controls.
          </p>
          <p className="text-xs text-blue-700 mt-1">
            False strict: {calibration.summary.drift_counts?.false_strict || 0}
            {' '}· False pass: {calibration.summary.drift_counts?.false_pass || 0}
            {' '}· Partial drift: {(calibration.summary.drift_counts?.too_strict_partial || 0) + (calibration.summary.drift_counts?.too_lenient_partial || 0)}
          </p>
        </div>
      )}

      {(systemKnowledge.tool_count || systemKnowledge.assertion_count) ? (
        <div className="bg-sky-50 border border-sky-200 rounded-xl p-4 text-sm text-sky-900">
          <p className="font-semibold mb-1">Derived System Knowledge</p>
          <p>
            {systemKnowledge.assertion_count || 0} assertions across
            {' '}{Object.keys(systemKnowledge.category_counts || {}).length} categories.
          </p>
          <p className="text-xs text-sky-700 mt-1">
            Tools detected: {(systemKnowledge.tools || []).map((t) => t.tool_name).slice(0, 6).join(', ') || 'None yet'}
          </p>
        </div>
      ) : null}

      {(countObjectKeys(controlOverrides) > 0 || countObjectKeys(invalidControlOverrides) > 0) && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-900">
          <p className="font-semibold mb-1">Control-Level Truth Overrides</p>
          <p>
            Applied {countObjectKeys(controlOverrides)} explicit control overrides on top of the global profile.
          </p>
          {countObjectKeys(controlOverrides) > 0 && (
            <p className="text-xs text-amber-800 mt-1">
              Examples: {Object.entries(controlOverrides).slice(0, 6).map(([cid, status]) => `${cid} -> ${status}`).join(', ')}
            </p>
          )}
          {countObjectKeys(invalidControlOverrides) > 0 && (
            <p className="text-xs text-red-700 mt-2">
              Ignored {countObjectKeys(invalidControlOverrides)} invalid overrides: {Object.entries(invalidControlOverrides).slice(0, 6).map(([cid, reason]) => `${cid} (${reason})`).join(', ')}
            </p>
          )}
        </div>
      )}

      {/* Family accordions */}
      <div className="space-y-3">
        {families.map(fam => (
          <FamilyGroup key={fam} family={fam} artifacts={byFamily[fam]} />
        ))}
      </div>
    </div>
  )
}

// ── History row ───────────────────────────────────────────────────────────────
function HistoryRow({ job, onDelete }) {
  const [delConfirm, setDelConfirm] = useState(false)
  const isActive = job.status === 'running' || job.status === 'pending'
  const artifactCount = (job.generated_doc_ids || []).length

  return (
    <div className="flex items-center gap-4 px-4 py-3 bg-white border border-gray-200 rounded-lg">
      <StatusBadge status={job.status} />
      <span className="text-xs text-gray-500 flex-1">
        {new Date(job.created_at).toLocaleString()}
      </span>
      <span className="text-sm text-gray-700">{artifactCount} document{artifactCount !== 1 ? 's' : ''}</span>
      {!isActive && (
        delConfirm ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-red-600">Delete job + docs?</span>
            <button
              onClick={() => { onDelete(job.id); setDelConfirm(false) }}
              className="text-xs text-white bg-red-500 px-2 py-1 rounded hover:bg-red-600"
            >Yes</button>
            <button
              onClick={() => setDelConfirm(false)}
              className="text-xs text-gray-500 border border-gray-300 px-2 py-1 rounded hover:bg-gray-50"
            >No</button>
          </div>
        ) : (
          <button
            onClick={() => setDelConfirm(true)}
            className="text-gray-400 hover:text-red-500 transition-colors"
            title="Delete job"
          >
            <Trash2 size={15} />
          </button>
        )
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function TestDatasetPage() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [showHistory, setShowHistory] = useState(false)
  const [confirmGenerate, setConfirmGenerate] = useState(false)
  const [packageStyle, setPackageStyle] = useState('standard')
  const [evidenceMix, setEvidenceMix] = useState('balanced')
  const [targetProfile, setTargetProfile] = useState('passing_ato')
  const [customSatisfiedPct, setCustomSatisfiedPct] = useState(75)
  const [customPartialPct, setCustomPartialPct] = useState(15)
  const [customFailedPct, setCustomFailedPct] = useState(10)
  const [familyOverrideRows, setFamilyOverrideRows] = useState([])
  const [controlOverrideRows, setControlOverrideRows] = useState([])

  // Project info
  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get(`/projects/${projectId}`).then(r => r.data),
  })

  const baselineName = useMemo(() => {
    const value = String(project?.impact_baseline || '').trim().toLowerCase()
    return value === 'low' || value === 'moderate' || value === 'high' ? value : 'moderate'
  }, [project?.impact_baseline])

  const { data: familyData } = useQuery({
    queryKey: ['control-families'],
    queryFn: () => api.get('/control-catalog/families').then((response) => response.data),
    staleTime: 10 * 60 * 1000,
  })

  const { data: controlOptions = [] } = useQuery({
    queryKey: ['test-dataset-control-options', baselineName],
    enabled: !!project,
    queryFn: async () => {
      const items = []
      let offset = 0
      let total = 0
      do {
        const response = await api.get('/control-catalog/controls', {
          params: {
            baseline: baselineName,
            include_enhancements: true,
            limit: 250,
            offset,
          },
        })
        const payload = response.data || {}
        total = payload.total || 0
        const pageItems = payload.items || []
        items.push(...pageItems)
        offset += pageItems.length
        if (pageItems.length === 0) break
      } while (offset < total)
      return items
    },
    staleTime: 10 * 60 * 1000,
  })

  // Documents (context source)
  const { data: documents = [] } = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => api.get(`/projects/${projectId}/documents`).then(r => r.data),
  })

  // Latest job — poll while running
  const { data: latestJob, isLoading: jobLoading } = useQuery({
    queryKey: ['test-dataset-job', projectId],
    queryFn: () => api.get(`/projects/${projectId}/test-dataset`).then(r => r.data),
    refetchInterval: (data) => {
      if (!data) return false
      return data?.status === 'running' || data?.status === 'pending' ? 2000 : false
    },
  })

  // History
  const { data: history = [] } = useQuery({
    queryKey: ['test-dataset-history', projectId],
    queryFn: () => api.get(`/projects/${projectId}/test-dataset/history`).then(r => r.data),
    enabled: showHistory,
  })

  // Generate
  const generateMutation = useMutation({
    mutationFn: () => {
      const familyOverrides = buildFamilyOverrides(familyOverrideRows)
      const controlOverrides = buildControlOverrides(controlOverrideRows)
      return api.post(`/projects/${projectId}/test-dataset/generate`, {
        package_style: packageStyle,
        evidence_mix: evidenceMix,
        target_profile: targetProfile,
        ...(targetProfile === 'custom'
          ? {
              expected_satisfied_pct: Number(customSatisfiedPct),
              expected_partial_pct: Number(customPartialPct),
              expected_failed_pct: Number(customFailedPct),
            }
          : {}),
        ...(Object.keys(familyOverrides).length > 0 ? { family_overrides: familyOverrides } : {}),
        ...(Object.keys(controlOverrides).length > 0 ? { control_overrides: controlOverrides } : {}),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['test-dataset-job', projectId] })
      qc.invalidateQueries({ queryKey: ['test-dataset-history', projectId] })
      setConfirmGenerate(false)
    },
  })

  const calibrateMutation = useMutation({
    mutationFn: (jobId) => api.post(`/projects/${projectId}/test-dataset/${jobId}/calibrate`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['test-dataset-job', projectId] })
      qc.invalidateQueries({ queryKey: ['test-dataset-history', projectId] })
    },
  })

  // Cancel
  const cancelMutation = useMutation({
    mutationFn: (jobId) => api.post(`/projects/${projectId}/test-dataset/${jobId}/cancel`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['test-dataset-job', projectId] }),
  })

  // Delete job
  const deleteMutation = useMutation({
    mutationFn: (jobId) => api.delete(`/projects/${projectId}/test-dataset/${jobId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['test-dataset-job', projectId] })
      qc.invalidateQueries({ queryKey: ['test-dataset-history', projectId] })
    },
  })

  const isRunning = latestJob?.status === 'running' || latestJob?.status === 'pending'
  const parsedDocs = documents.filter(d => d.parse_status === 'completed' || d.parse_status === 'indexed')
  const hasExistingRun = latestJob && latestJob.status === 'completed'
  const customTotal = Number(customSatisfiedPct || 0) + Number(customPartialPct || 0) + Number(customFailedPct || 0)
  const customTotalValid = customTotal === 100
  const familyOverridesValid = familyOverrideRows.every((row) => {
    if (!row.family && row.satisfied_pct === '' && row.partial_pct === '' && row.failed_pct === '') return true
    return !!row.family
      && toNumberOrUndefined(row.satisfied_pct) !== undefined
      && toNumberOrUndefined(row.partial_pct) !== undefined
      && toNumberOrUndefined(row.failed_pct) !== undefined
  })
  const controlOverridesValid = controlOverrideRows.every((row) => {
    if (!row.control_id && !row.status) return true
    return !!row.control_id && !!row.status
  })
  const controlOverridesCount = Object.keys(buildControlOverrides(controlOverrideRows)).length
  const familyOverridesCount = Object.keys(buildFamilyOverrides(familyOverrideRows)).length

  return (
    <div className="max-w-5xl mx-auto py-8 px-4 space-y-6">
      {/* ── Header ── */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate(`/projects/${projectId}`)}
          className="text-gray-400 hover:text-gray-600 transition-colors"
        >
          <ArrowLeft size={20} />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <FlaskConical size={22} className="text-violet-600" />
            <h1 className="text-xl font-bold text-gray-900">Test Dataset Generator</h1>
          </div>
          {project && (
            <p className="text-sm text-gray-500 mt-0.5">
              {project.name} — {project.impact_baseline?.toUpperCase() || 'MODERATE'} baseline
            </p>
          )}
        </div>
        <button
          onClick={() => setShowHistory(v => !v)}
          className="flex items-center gap-1.5 text-sm text-gray-500 border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <History size={14} />
          History
        </button>
      </div>

      {/* ── What this does ── */}
      <div className="bg-violet-50 border border-violet-200 rounded-xl p-4 text-sm text-violet-800 space-y-1">
        <p className="font-semibold">What this generates</p>
        <p>
          A complete, fictitious ATO evidence package — one document per control in the project's
          {' '}{project?.impact_baseline?.toUpperCase() || 'MODERATE'} baseline. Documents are written
          as realistic present-tense artifacts (policies, procedures, technical artifacts, SSP narratives)
          using the project's actual system context extracted from uploaded documents.
        </p>
        <p>
          New runs generate a consolidated package of shared SSP, policy, procedure, technical, and
          operational artifacts instead of hundreds of control-specific files.
        </p>
        <p className="text-violet-600 font-medium">
          Running a new generation replaces all previously generated test documents.
        </p>
        <p className="text-violet-700">
          New runs now target a consolidated package and store an expected assessment profile so you can compare the next complete assessment against the intended result.
        </p>
      </div>

      {/* ── Context source ── */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
        <div className="flex items-center gap-2">
          <Database size={16} className="text-gray-500" />
          <h2 className="font-semibold text-gray-800 text-sm">Context Source Documents</h2>
          <span className="text-xs text-gray-400 ml-1">({parsedDocs.length} parsed)</span>
        </div>
        {documents.length === 0 ? (
          <p className="text-sm text-gray-500">
            No documents uploaded. The generator will use a generic Keystone Federal persona as context.
            Upload real documents for system-specific output.
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-48 overflow-y-auto pr-1">
            {documents.map(doc => (
              <div key={doc.id} className="flex items-center gap-2 text-xs text-gray-600 bg-gray-50 rounded-lg px-3 py-2">
                <File size={12} className="text-gray-400 flex-shrink-0" />
                <span className="truncate flex-1">{doc.filename}</span>
                <span className={`flex-shrink-0 font-medium ${
                  doc.parse_status === 'completed' || doc.parse_status === 'indexed'
                    ? 'text-green-600' : 'text-yellow-600'
                }`}>
                  {doc.parse_status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Generate button / status ── */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="font-semibold text-gray-800">Generate Test Dataset</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Generates one compliance document per control across the full {project?.impact_baseline?.toUpperCase() || 'MODERATE'} baseline.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {isRunning && latestJob && (
              <button
                onClick={() => cancelMutation.mutate(latestJob.id)}
                disabled={cancelMutation.isPending}
                className="flex items-center gap-1.5 text-sm border border-red-200 text-red-500 px-3 py-2 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
              >
                <XCircle size={15} />
                Cancel
              </button>
            )}
            {!confirmGenerate ? (
              <button
                onClick={() => setConfirmGenerate(true)}
                disabled={isRunning || generateMutation.isPending || (targetProfile === 'custom' && !customTotalValid) || !familyOverridesValid || !controlOverridesValid}
                className="flex items-center gap-2 bg-violet-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-violet-700 disabled:opacity-40 transition-colors"
              >
                {isRunning ? (
                  <><Loader2 size={15} className="animate-spin" /> Running…</>
                ) : hasExistingRun ? (
                  <><RefreshCw size={15} /> Regenerate</>
                ) : (
                  <><Play size={15} /> Generate</>
                )}
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-xs text-orange-600">
                  {hasExistingRun ? 'This will replace existing test documents.' : 'Start generation?'}
                </span>
                <button
                  onClick={() => generateMutation.mutate()}
                  disabled={generateMutation.isPending || (targetProfile === 'custom' && !customTotalValid) || !familyOverridesValid || !controlOverridesValid}
                  className="text-xs bg-violet-600 text-white px-3 py-1.5 rounded-lg hover:bg-violet-700 disabled:opacity-50"
                >
                  {generateMutation.isPending ? 'Starting…' : 'Confirm'}
                </button>
                <button
                  onClick={() => setConfirmGenerate(false)}
                  className="text-xs border border-gray-300 text-gray-500 px-3 py-1.5 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="text-sm text-gray-700">
            <span className="block text-xs font-semibold text-gray-500 mb-1">Package Style</span>
            <select value={packageStyle} onChange={e => setPackageStyle(e.target.value)} className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white">
              <option value="lean">Lean</option>
              <option value="standard">Standard</option>
              <option value="robust">Robust</option>
            </select>
          </label>
          <label className="text-sm text-gray-700">
            <span className="block text-xs font-semibold text-gray-500 mb-1">Evidence Mix</span>
            <select value={evidenceMix} onChange={e => setEvidenceMix(e.target.value)} className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white">
              <option value="balanced">Balanced</option>
              <option value="policy_heavy">Policy Heavy</option>
              <option value="implementation_heavy">Implementation Heavy</option>
              <option value="test_heavy">Test Heavy</option>
            </select>
          </label>
          <label className="text-sm text-gray-700">
            <span className="block text-xs font-semibold text-gray-500 mb-1">Expected Outcome</span>
            <select value={targetProfile} onChange={e => setTargetProfile(e.target.value)} className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white">
              <option value="passing_ato">Passing ATO</option>
              <option value="mostly_compliant">Mostly Compliant</option>
              <option value="mixed_realistic">Mixed Realistic</option>
              <option value="stress_test">Stress Test</option>
              <option value="custom">Custom Percentages</option>
            </select>
          </label>
        </div>

        {targetProfile === 'custom' && (
          <div className="border border-violet-200 bg-violet-50 rounded-xl p-4 space-y-3">
            <div>
              <p className="text-sm font-semibold text-violet-900">Custom Expected Outcome Mix</p>
              <p className="text-xs text-violet-700 mt-1">
                These values become the intended truth set for the synthetic package and should add up to 100%.
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <label className="text-sm text-gray-700">
                <span className="block text-xs font-semibold text-gray-500 mb-1">Compliant %</span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={customSatisfiedPct}
                  onChange={e => setCustomSatisfiedPct(e.target.value)}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white"
                />
              </label>
              <label className="text-sm text-gray-700">
                <span className="block text-xs font-semibold text-gray-500 mb-1">Partial %</span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={customPartialPct}
                  onChange={e => setCustomPartialPct(e.target.value)}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white"
                />
              </label>
              <label className="text-sm text-gray-700">
                <span className="block text-xs font-semibold text-gray-500 mb-1">Non-Compliant %</span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={customFailedPct}
                  onChange={e => setCustomFailedPct(e.target.value)}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 bg-white"
                />
              </label>
            </div>
            <p className={`text-xs font-medium ${customTotalValid ? 'text-green-700' : 'text-red-600'}`}>
              Total: {customTotal}% {customTotalValid ? '- ready to generate' : '- percentages must add up to 100'}
            </p>
          </div>
        )}

        <div className="border border-sky-200 bg-sky-50 rounded-xl p-4 space-y-3">
          <div>
            <p className="text-sm font-semibold text-sky-900">Advanced Family Shaping</p>
            <p className="text-xs text-sky-700 mt-1">
              Optional per-family overrides make the synthetic truth set more realistic. Add rows only if you want a family to be stricter or weaker than the global profile.
            </p>
          </div>
          <div className="space-y-2">
            {familyOverrideRows.length === 0 && (
              <div className="rounded-lg border border-dashed border-sky-300 bg-white px-3 py-4 text-sm text-sky-700">
                No family overrides. The selected global profile will be used for every family.
              </div>
            )}
            {familyOverrideRows.map((row, index) => (
              <div key={`family-override-${index}`} className="grid grid-cols-1 md:grid-cols-12 gap-2 rounded-lg border border-sky-200 bg-white p-3">
                <label className="md:col-span-3 text-sm text-gray-700">
                  <span className="block text-xs font-semibold text-gray-500 mb-1">Family</span>
                  <select
                    value={row.family}
                    onChange={(event) => {
                      const next = [...familyOverrideRows]
                      next[index] = { ...row, family: event.target.value }
                      setFamilyOverrideRows(next)
                    }}
                    className="w-full rounded-lg border border-sky-200 px-3 py-2 bg-white"
                  >
                    <option value="">Select family</option>
                    {(familyData?.families || []).map((item) => (
                      <option key={item.id} value={item.id}>{item.id} - {item.title}</option>
                    ))}
                  </select>
                </label>
                <label className="md:col-span-2 text-sm text-gray-700">
                  <span className="block text-xs font-semibold text-gray-500 mb-1">Compliant %</span>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={row.satisfied_pct}
                    onChange={(event) => {
                      const next = [...familyOverrideRows]
                      next[index] = { ...row, satisfied_pct: event.target.value }
                      setFamilyOverrideRows(next)
                    }}
                    className="w-full rounded-lg border border-sky-200 px-3 py-2 bg-white"
                  />
                </label>
                <label className="md:col-span-2 text-sm text-gray-700">
                  <span className="block text-xs font-semibold text-gray-500 mb-1">Partial %</span>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={row.partial_pct}
                    onChange={(event) => {
                      const next = [...familyOverrideRows]
                      next[index] = { ...row, partial_pct: event.target.value }
                      setFamilyOverrideRows(next)
                    }}
                    className="w-full rounded-lg border border-sky-200 px-3 py-2 bg-white"
                  />
                </label>
                <label className="md:col-span-2 text-sm text-gray-700">
                  <span className="block text-xs font-semibold text-gray-500 mb-1">Non-Compliant %</span>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={row.failed_pct}
                    onChange={(event) => {
                      const next = [...familyOverrideRows]
                      next[index] = { ...row, failed_pct: event.target.value }
                      setFamilyOverrideRows(next)
                    }}
                    className="w-full rounded-lg border border-sky-200 px-3 py-2 bg-white"
                  />
                </label>
                <div className="md:col-span-3 flex items-end justify-end">
                  <button
                    type="button"
                    onClick={() => setFamilyOverrideRows(familyOverrideRows.filter((_, rowIndex) => rowIndex !== index))}
                    className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-600 hover:bg-red-50"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setFamilyOverrideRows([...familyOverrideRows, createEmptyFamilyOverride()])}
            className="inline-flex items-center gap-2 rounded-lg border border-sky-300 bg-white px-3 py-2 text-sm font-medium text-sky-700 hover:bg-sky-100"
          >
            + Add family override
          </button>
          <p className={`text-xs font-medium ${familyOverridesValid ? 'text-sky-700' : 'text-red-600'}`}>
            {familyOverridesValid
              ? `${familyOverridesCount} family override${familyOverridesCount === 1 ? '' : 's'} ready. Families not listed here use the selected global profile.`
              : 'Every family override row needs a family and all three percentage values.'}
          </p>
        </div>

        <div className="border border-amber-200 bg-amber-50 rounded-xl p-4 space-y-3">
          <div>
            <p className="text-sm font-semibold text-amber-900">Control-Level Truth Overrides</p>
            <p className="text-xs text-amber-700 mt-1">
              Optional explicit overrides let you pin exact controls to exact intended outcomes. These win over both the global profile and family shaping.
            </p>
          </div>
          <div className="space-y-2">
            {controlOverrideRows.length === 0 && (
              <div className="rounded-lg border border-dashed border-amber-300 bg-white px-3 py-4 text-sm text-amber-700">
                No control overrides. The generator will use the selected profile and any family shaping above.
              </div>
            )}
            {controlOverrideRows.map((row, index) => (
              <div key={`control-override-${index}`} className="grid grid-cols-1 md:grid-cols-12 gap-2 rounded-lg border border-amber-200 bg-white p-3">
                <label className="md:col-span-7 text-sm text-gray-700">
                  <span className="block text-xs font-semibold text-gray-500 mb-1">Control</span>
                  <select
                    value={row.control_id}
                    onChange={(event) => {
                      const next = [...controlOverrideRows]
                      next[index] = { ...row, control_id: event.target.value }
                      setControlOverrideRows(next)
                    }}
                    className="w-full rounded-lg border border-amber-200 px-3 py-2 bg-white"
                  >
                    <option value="">Select control</option>
                    {controlOptions.map((item) => (
                      <option key={item.id} value={item.id}>{item.id} - {item.title}</option>
                    ))}
                  </select>
                </label>
                <label className="md:col-span-3 text-sm text-gray-700">
                  <span className="block text-xs font-semibold text-gray-500 mb-1">Outcome</span>
                  <select
                    value={row.status}
                    onChange={(event) => {
                      const next = [...controlOverrideRows]
                      next[index] = { ...row, status: event.target.value }
                      setControlOverrideRows(next)
                    }}
                    className="w-full rounded-lg border border-amber-200 px-3 py-2 bg-white"
                  >
                    {OUTCOME_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
                <div className="md:col-span-2 flex items-end justify-end">
                  <button
                    type="button"
                    onClick={() => setControlOverrideRows(controlOverrideRows.filter((_, rowIndex) => rowIndex !== index))}
                    className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-600 hover:bg-red-50"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setControlOverrideRows([...controlOverrideRows, createEmptyControlOverride()])}
            className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-medium text-amber-700 hover:bg-amber-100"
          >
            + Add control override
          </button>
          <p className={`text-xs font-medium ${controlOverridesValid ? 'text-amber-700' : 'text-red-600'}`}>
            {controlOverridesValid
              ? `${controlOverridesCount} explicit control override${controlOverridesCount === 1 ? '' : 's'} ready. Accepted values: compliant, partial, non_compliant, pass, fail.`
              : 'Every control override row needs both a control and an outcome.'}
          </p>
        </div>

        {/* Progress / status */}
        {latestJob && (
          <div className="border-t border-gray-100 pt-4 space-y-2">
            <div className="flex items-center gap-3">
              <StatusBadge status={latestJob.status} />
              {latestJob.progress_detail && (
                <span className="text-sm text-gray-600">{latestJob.progress_detail}</span>
              )}
            </div>
            {latestJob.error_message && (
              <div className="flex items-start gap-2 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
                <AlertTriangle size={15} className="flex-shrink-0 mt-0.5" />
                {latestJob.error_message}
              </div>
            )}
          </div>
        )}

        {generateMutation.isError && (
          <div className="flex items-start gap-2 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
            <AlertTriangle size={15} className="flex-shrink-0 mt-0.5" />
            {generateMutation.error?.response?.data?.detail || 'Generation failed. Check backend logs.'}
          </div>
        )}
      </div>

      {/* ── Results ── */}
      {latestJob && (latestJob.artifacts?.length > 0 || latestJob.status === 'completed') && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold text-gray-800 flex items-center gap-2">
              <CheckCircle2 size={16} className="text-green-500" />
              Generated Artifacts
              {latestJob.generated_doc_ids?.length > 0 && (
                <span className="text-xs text-gray-400 font-normal">
                  — {latestJob.generated_doc_ids.length} document{latestJob.generated_doc_ids.length !== 1 ? 's' : ''}
                </span>
              )}
            </h2>
            {latestJob.status === 'completed' && (
              <button
                onClick={() => calibrateMutation.mutate(latestJob.id)}
                disabled={calibrateMutation.isPending}
                className="inline-flex items-center gap-2 border border-blue-300 text-blue-700 px-3 py-1.5 rounded-lg text-sm font-medium hover:bg-blue-50 disabled:opacity-50"
              >
                <BarChart2 size={14} className={calibrateMutation.isPending ? 'animate-pulse' : ''} />
                {calibrateMutation.isPending ? 'Running Calibration...' : 'Run Calibration'}
              </button>
            )}
          </div>
          <ResultsPanel job={latestJob} />
        </div>
      )}

      {/* ── History panel ── */}
      {showHistory && (
        <div className="space-y-3">
          <h2 className="font-semibold text-gray-800 flex items-center gap-2">
            <History size={16} className="text-gray-500" />
            Job History
          </h2>
          {history.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-4">No previous jobs found.</p>
          ) : (
            <div className="space-y-2">
              {history.map(job => (
                <HistoryRow
                  key={job.id}
                  job={job}
                  onDelete={(jobId) => deleteMutation.mutate(jobId)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
