import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  BarChart2,
  CheckCircle2,
  FlaskConical,
  Play,
  Plus,
  RefreshCw,
  Target,
  Trash2,
  XCircle,
} from 'lucide-react'
import api from '../api/client'

function parseOptionalJson(label, value) {
  if (!value || !value.trim()) return null
  try {
    return JSON.parse(value)
  } catch {
    throw new Error(`${label} must be valid JSON.`)
  }
}

function SummaryCard({ label, value, hint }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      {hint ? <p className="text-xs text-gray-500 mt-1">{hint}</p> : null}
    </div>
  )
}

function formatSeconds(value) {
  const secs = Number(value)
  if (!Number.isFinite(secs) || secs < 0) return 'n/a'
  if (secs < 60) return `${secs.toFixed(1)}s`
  return `${(secs / 60).toFixed(1)}m`
}

function statusTone(matchStatus) {
  if (matchStatus === 'matched') return 'bg-green-50 border-green-200 text-green-800'
  if (matchStatus?.includes('false') || matchStatus?.includes('strict')) return 'bg-red-50 border-red-200 text-red-800'
  if (matchStatus?.includes('lenient') || matchStatus === 'mismatch') return 'bg-amber-50 border-amber-200 text-amber-800'
  return 'bg-gray-50 border-gray-200 text-gray-700'
}

function CaseRow({ suiteId, calibrationCase, onDelete }) {
  return (
    <div className="flex items-start gap-3 px-3 py-3 border border-gray-200 rounded-lg bg-white">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-gray-900">{calibrationCase.control_id}</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
            expected {calibrationCase.expected_status?.replace(/_/g, ' ')}
          </span>
          {calibrationCase.expected_objectives && Object.keys(calibrationCase.expected_objectives).length > 0 ? (
            <span className="text-xs px-2 py-0.5 rounded-full bg-violet-100 text-violet-700 font-medium">
              {Object.keys(calibrationCase.expected_objectives).length} objective checks
            </span>
          ) : null}
          {Array.isArray(calibrationCase.expected_citations) && calibrationCase.expected_citations.length > 0 ? (
            <span className="text-xs px-2 py-0.5 rounded-full bg-sky-100 text-sky-700 font-medium">
              {calibrationCase.expected_citations.length} citation checks
            </span>
          ) : null}
        </div>
        {calibrationCase.notes ? (
          <p className="text-sm text-gray-600 mt-1">{calibrationCase.notes}</p>
        ) : (
          <p className="text-sm text-gray-400 mt-1 italic">No notes yet.</p>
        )}
        {calibrationCase.expected_objectives && Object.keys(calibrationCase.expected_objectives).length > 0 ? (
          <pre className="mt-2 text-xs text-gray-500 bg-gray-50 border border-gray-100 rounded p-2 overflow-x-auto">
            {JSON.stringify(calibrationCase.expected_objectives, null, 2)}
          </pre>
        ) : null}
        {Array.isArray(calibrationCase.expected_citations) && calibrationCase.expected_citations.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {calibrationCase.expected_citations.slice(0, 5).map((item, idx) => (
              <span key={idx} className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                {item}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <button
        onClick={() => onDelete({ suiteId, caseId: calibrationCase.id })}
        className="text-red-500 hover:text-red-700 transition-colors"
        title="Delete case"
      >
        <Trash2 size={14} />
      </button>
    </div>
  )
}

function RunSummary({ run }) {
  if (!run?.summary) return null
  const summary = run.summary
  const drift = summary.drift_counts || {}
  const performance = summary.performance || {}
  const assessmentPerf = performance.assessment || {}
  const packageTiming = performance.package_timing || {}
  return (
    <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-sm text-blue-900">
      <p className="font-semibold mb-1">Latest Calibration Run</p>
      <p>
        Matched <span className="font-semibold">{summary.match_pct || 0}%</span> of curated expectations across{' '}
        {summary.total_controls || 0} controls.
      </p>
      <p className="text-xs text-blue-700 mt-1">
        False strict: {drift.false_strict || 0}
        {' '}· False pass: {drift.false_pass || 0}
        {' '}· Partial drift: {(drift.too_strict_partial || 0) + (drift.too_lenient_partial || 0)}
      </p>
      {(assessmentPerf.duration_secs != null || packageTiming.total_secs != null) ? (
        <p className="text-xs text-blue-700 mt-1">
          Assessment runtime: {formatSeconds(assessmentPerf.duration_secs)}
          {packageTiming.total_secs != null ? ` | Package runtime: ${formatSeconds(packageTiming.total_secs)}` : ''}
          {performance.package_viability_score != null ? ` | Package viability: ${performance.package_viability_score}%` : ''}
        </p>
      ) : null}
    </div>
  )
}

export default function CalibrationPage() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [suiteForm, setSuiteForm] = useState({ name: '', description: '' })
  const [caseForms, setCaseForms] = useState({})
  const [assessmentSelection, setAssessmentSelection] = useState({})
  const [selectedSuiteId, setSelectedSuiteId] = useState(null)
  const [selectedRunId, setSelectedRunId] = useState(null)
  const [caseError, setCaseError] = useState('')

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get(`/projects/${projectId}`).then((r) => r.data),
  })

  const { data: suites = [], isLoading } = useQuery({
    queryKey: ['calibration-suites', projectId],
    queryFn: () => api.get(`/projects/${projectId}/calibration/suites`).then((r) => r.data),
  })

  const { data: assessments = [] } = useQuery({
    queryKey: ['assessments', projectId],
    queryFn: () => api.get(`/projects/${projectId}/assessments`).then((r) => r.data),
  })

  const completedAssessments = useMemo(
    () => assessments.filter((assessment) => assessment.status === 'complete'),
    [assessments]
  )

  useEffect(() => {
    if (!suites.length) {
      setSelectedSuiteId(null)
      setSelectedRunId(null)
      return
    }
    if (!selectedSuiteId || !suites.some((suite) => suite.id === selectedSuiteId)) {
      const firstSuite = suites[0]
      setSelectedSuiteId(firstSuite.id)
      setSelectedRunId(firstSuite.latest_run?.id || null)
    }
  }, [suites, selectedSuiteId])

  const selectedSuite = suites.find((suite) => suite.id === selectedSuiteId) || null

  const { data: runDetail, isFetching: runLoading } = useQuery({
    queryKey: ['calibration-run', projectId, selectedRunId],
    queryFn: () => api.get(`/projects/${projectId}/calibration/runs/${selectedRunId}`).then((r) => r.data),
    enabled: !!selectedRunId,
  })

  const createSuiteMutation = useMutation({
    mutationFn: (payload) => api.post(`/projects/${projectId}/calibration/suites`, payload),
    onSuccess: () => {
      setSuiteForm({ name: '', description: '' })
      qc.invalidateQueries({ queryKey: ['calibration-suites', projectId] })
    },
  })

  const createCaseMutation = useMutation({
    mutationFn: ({ suiteId, payload }) => api.post(`/projects/${projectId}/calibration/suites/${suiteId}/cases`, payload),
    onSuccess: (_data, variables) => {
      setCaseForms((prev) => ({
        ...prev,
        [variables.suiteId]: {
          control_id: '',
          expected_status: 'compliant',
          notes: '',
          expected_objectives: '',
          expected_citations: '',
        },
      }))
      setCaseError('')
      qc.invalidateQueries({ queryKey: ['calibration-suites', projectId] })
    },
  })

  const deleteCaseMutation = useMutation({
    mutationFn: ({ suiteId, caseId }) => api.delete(`/projects/${projectId}/calibration/suites/${suiteId}/cases/${caseId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['calibration-suites', projectId] }),
  })

  const runSuiteMutation = useMutation({
    mutationFn: ({ suiteId, assessmentId }) =>
      api.post(`/projects/${projectId}/calibration/suites/${suiteId}/run`, {
        assessment_id: assessmentId ? Number(assessmentId) : null,
      }),
    onSuccess: (response, variables) => {
      const runId = response?.data?.id
      qc.invalidateQueries({ queryKey: ['calibration-suites', projectId] })
      if (variables?.suiteId) setSelectedSuiteId(variables.suiteId)
      if (runId) setSelectedRunId(runId)
    },
  })

  const suiteSummary = useMemo(() => {
    const caseCount = suites.reduce((sum, suite) => sum + (suite.case_count || 0), 0)
    const latestRuns = suites.map((suite) => suite.latest_run).filter(Boolean)
    const latestRun = latestRuns.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))[0]
    return {
      suites: suites.length,
      cases: caseCount,
      latestRun,
    }
  }, [suites])

  const submitCase = (suiteId) => {
    const form = caseForms[suiteId] || {}
    try {
      const payload = {
        control_id: (form.control_id || '').trim(),
        expected_status: form.expected_status || 'compliant',
        notes: form.notes || '',
        expected_objectives: parseOptionalJson('Expected objectives', form.expected_objectives || ''),
        expected_citations: parseOptionalJson('Expected citations', form.expected_citations || ''),
      }
      setCaseError('')
      createCaseMutation.mutate({ suiteId, payload })
    } catch (error) {
      setCaseError(error.message || 'Case expectations are invalid.')
    }
  }

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
            <h1 className="text-2xl font-bold text-gray-900">Calibration</h1>
            <p className="text-sm text-gray-500 mt-1">
              Curate expected control outcomes for {project?.name || 'this project'} and measure assessor drift against real completed assessments.
            </p>
          </div>
        </div>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ['calibration-suites', projectId] })}
          className="inline-flex items-center gap-2 border border-gray-300 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50"
        >
          <RefreshCw size={16} />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <SummaryCard label="Suites" value={suiteSummary.suites} hint="Curated expectation sets" />
        <SummaryCard label="Cases" value={suiteSummary.cases} hint="Expected control outcomes" />
        <SummaryCard label="Completed Assessments" value={completedAssessments.length} hint="Available to compare against" />
        <SummaryCard
          label="Latest Match"
          value={`${Math.round(suiteSummary.latestRun?.summary?.match_pct || 0)}%`}
          hint={suiteSummary.latestRun ? `Run #${suiteSummary.latestRun.id}` : 'No suite run yet'}
        />
      </div>

      <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4 text-sm text-indigo-900">
        <p className="font-semibold mb-1">What this is for</p>
        <p>
          Use suites to define controls that should definitely pass, definitely fail, or land in partial. Then run the suite against a completed assessment to see where the engine is too strict, too lenient, or drifting on borderline cases.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[360px,minmax(0,1fr)] gap-6">
        <div className="space-y-4">
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
            <div className="flex items-center gap-2">
              <Plus size={16} className="text-violet-600" />
              <h2 className="font-semibold text-gray-900">Create Suite</h2>
            </div>
            <input
              value={suiteForm.name}
              onChange={(e) => setSuiteForm((prev) => ({ ...prev, name: e.target.value }))}
              placeholder="Example: Adequate Controls"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
            />
            <textarea
              value={suiteForm.description}
              onChange={(e) => setSuiteForm((prev) => ({ ...prev, description: e.target.value }))}
              placeholder="What this suite is validating..."
              rows={3}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
            />
            <button
              onClick={() => createSuiteMutation.mutate(suiteForm)}
              disabled={!suiteForm.name.trim() || createSuiteMutation.isPending}
              className="inline-flex items-center gap-2 bg-violet-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-violet-700 disabled:opacity-50"
            >
              <Plus size={15} />
              {createSuiteMutation.isPending ? 'Creating...' : 'Create Suite'}
            </button>
          </div>

          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <Target size={16} className="text-blue-600" />
              <h2 className="font-semibold text-gray-900">Calibration Suites</h2>
            </div>
            {isLoading ? (
              <p className="text-sm text-gray-500">Loading suites...</p>
            ) : suites.length === 0 ? (
              <p className="text-sm text-gray-500">No suites yet.</p>
            ) : (
              <div className="space-y-3">
                {suites.map((suite) => {
                  const active = suite.id === selectedSuiteId
                  return (
                    <button
                      key={suite.id}
                      onClick={() => {
                        setSelectedSuiteId(suite.id)
                        setSelectedRunId(suite.latest_run?.id || null)
                      }}
                      className={`w-full text-left border rounded-xl p-4 transition-colors ${
                        active ? 'border-violet-300 bg-violet-50' : 'border-gray-200 bg-white hover:bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className="font-semibold text-gray-900 truncate">{suite.name}</p>
                          <p className="text-xs text-gray-500 mt-1">{suite.case_count || 0} curated cases</p>
                        </div>
                        {suite.latest_run?.summary?.match_pct != null ? (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
                            {suite.latest_run.summary.match_pct}% match
                          </span>
                        ) : null}
                      </div>
                      {suite.description ? (
                        <p className="text-sm text-gray-600 mt-2 line-clamp-2">{suite.description}</p>
                      ) : null}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4">
          {!selectedSuite ? (
            <div className="bg-white border border-gray-200 rounded-xl p-8 text-sm text-gray-500">
              Select a suite to add curated cases and run calibration.
            </div>
          ) : (
            <>
              <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <h2 className="font-semibold text-gray-900">{selectedSuite.name}</h2>
                    {selectedSuite.description ? (
                      <p className="text-sm text-gray-500 mt-1">{selectedSuite.description}</p>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      value={assessmentSelection[selectedSuite.id] || ''}
                      onChange={(e) => setAssessmentSelection((prev) => ({ ...prev, [selectedSuite.id]: e.target.value }))}
                      className="rounded-lg border border-gray-200 px-3 py-2 text-sm bg-white"
                    >
                      <option value="">Latest completed assessment</option>
                      {completedAssessments.map((assessment) => (
                        <option key={assessment.id} value={assessment.id}>
                          Assessment #{assessment.project_run_number || assessment.id}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => runSuiteMutation.mutate({
                        suiteId: selectedSuite.id,
                        assessmentId: assessmentSelection[selectedSuite.id],
                      })}
                      disabled={runSuiteMutation.isPending || completedAssessments.length === 0}
                      className="inline-flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
                    >
                      <Play size={15} />
                      {runSuiteMutation.isPending ? 'Running...' : 'Run Suite'}
                    </button>
                  </div>
                </div>

                <RunSummary run={selectedSuite.latest_run} />

                <div className="border-t border-gray-100 pt-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <Plus size={14} className="text-violet-600" />
                    <p className="text-sm font-semibold text-gray-900">Add Case</p>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-[140px,180px,minmax(0,1fr),auto] gap-3">
                    <input
                      value={caseForms[selectedSuite.id]?.control_id || ''}
                      onChange={(e) => setCaseForms((prev) => ({
                        ...prev,
                        [selectedSuite.id]: {
                          control_id: e.target.value,
                          expected_status: prev[selectedSuite.id]?.expected_status || 'compliant',
                          notes: prev[selectedSuite.id]?.notes || '',
                          expected_objectives: prev[selectedSuite.id]?.expected_objectives || '',
                          expected_citations: prev[selectedSuite.id]?.expected_citations || '',
                        },
                      }))}
                      placeholder="AC-2"
                      className="rounded-lg border border-gray-200 px-3 py-2 text-sm"
                    />
                    <select
                      value={caseForms[selectedSuite.id]?.expected_status || 'compliant'}
                      onChange={(e) => setCaseForms((prev) => ({
                        ...prev,
                        [selectedSuite.id]: {
                          control_id: prev[selectedSuite.id]?.control_id || '',
                          expected_status: e.target.value,
                          notes: prev[selectedSuite.id]?.notes || '',
                          expected_objectives: prev[selectedSuite.id]?.expected_objectives || '',
                          expected_citations: prev[selectedSuite.id]?.expected_citations || '',
                        },
                      }))}
                      className="rounded-lg border border-gray-200 px-3 py-2 text-sm bg-white"
                    >
                      <option value="compliant">Compliant</option>
                      <option value="partially_compliant">Partially Compliant</option>
                      <option value="non_compliant">Non-Compliant</option>
                    </select>
                    <input
                      value={caseForms[selectedSuite.id]?.notes || ''}
                      onChange={(e) => setCaseForms((prev) => ({
                        ...prev,
                        [selectedSuite.id]: {
                          control_id: prev[selectedSuite.id]?.control_id || '',
                          expected_status: prev[selectedSuite.id]?.expected_status || 'compliant',
                          notes: e.target.value,
                          expected_objectives: prev[selectedSuite.id]?.expected_objectives || '',
                          expected_citations: prev[selectedSuite.id]?.expected_citations || '',
                        },
                      }))}
                      placeholder="Why this control should land here..."
                      className="rounded-lg border border-gray-200 px-3 py-2 text-sm"
                    />
                    <button
                      onClick={() => submitCase(selectedSuite.id)}
                      disabled={!(caseForms[selectedSuite.id]?.control_id || '').trim() || createCaseMutation.isPending}
                      className="inline-flex items-center justify-center gap-2 bg-violet-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-violet-700 disabled:opacity-50"
                    >
                      <Plus size={14} />
                      Add
                    </button>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <textarea
                      value={caseForms[selectedSuite.id]?.expected_objectives || ''}
                      onChange={(e) => setCaseForms((prev) => ({
                        ...prev,
                        [selectedSuite.id]: {
                          control_id: prev[selectedSuite.id]?.control_id || '',
                          expected_status: prev[selectedSuite.id]?.expected_status || 'compliant',
                          notes: prev[selectedSuite.id]?.notes || '',
                          expected_objectives: e.target.value,
                          expected_citations: prev[selectedSuite.id]?.expected_citations || '',
                        },
                      }))}
                      placeholder='Optional JSON, e.g. {"AC-2a.[01]":"compliant"}'
                      rows={4}
                      className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono"
                    />
                    <textarea
                      value={caseForms[selectedSuite.id]?.expected_citations || ''}
                      onChange={(e) => setCaseForms((prev) => ({
                        ...prev,
                        [selectedSuite.id]: {
                          control_id: prev[selectedSuite.id]?.control_id || '',
                          expected_status: prev[selectedSuite.id]?.expected_status || 'compliant',
                          notes: prev[selectedSuite.id]?.notes || '',
                          expected_objectives: prev[selectedSuite.id]?.expected_objectives || '',
                          expected_citations: e.target.value,
                        },
                      }))}
                      placeholder={'Optional JSON array, e.g. ["Access Control Policy","CrowdStrike"]'}
                      rows={4}
                      className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono"
                    />
                  </div>
                  {caseError ? (
                    <p className="text-xs text-red-600">{caseError}</p>
                  ) : (
                    <p className="text-xs text-gray-500">
                      Add optional objective and citation expectations when you want to measure why the assessor drifted, not just whether the top-line control status matched.
                    </p>
                  )}
                </div>
              </div>

              <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
                <div className="flex items-center gap-2">
                  <FlaskConical size={16} className="text-gray-600" />
                  <h2 className="font-semibold text-gray-900">Curated Cases</h2>
                </div>
                {selectedSuite.cases?.length ? (
                  <div className="space-y-3">
                    {selectedSuite.cases.map((calibrationCase) => (
                      <CaseRow
                        key={calibrationCase.id}
                        suiteId={selectedSuite.id}
                        calibrationCase={calibrationCase}
                        onDelete={(payload) => deleteCaseMutation.mutate(payload)}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">No curated cases yet.</p>
                )}
              </div>

              <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <BarChart2 size={16} className="text-blue-600" />
                    <h2 className="font-semibold text-gray-900">Mismatch Review</h2>
                  </div>
                  {runLoading ? <span className="text-xs text-gray-400">Loading run...</span> : null}
                </div>
                {!selectedRunId ? (
                  <p className="text-sm text-gray-500">Run this suite to inspect drift and false strictness.</p>
                ) : !runDetail?.results?.length ? (
                  <p className="text-sm text-gray-500">No run results found.</p>
                ) : (
                  <div className="space-y-3">
                    {runDetail.summary?.performance ? (
                      <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs text-gray-700">
                        <p className="font-semibold text-gray-900 mb-1">Performance Snapshot</p>
                        <p>
                          Assessment runtime: {formatSeconds(runDetail.summary.performance.assessment?.duration_secs)}
                          {runDetail.summary.performance.package_timing?.total_secs != null
                            ? ` | Source package runtime: ${formatSeconds(runDetail.summary.performance.package_timing.total_secs)}`
                            : ''}
                        </p>
                        <p className="mt-1">
                          Package viability: {runDetail.summary.performance.package_viability_score ?? 'n/a'}
                          {runDetail.summary.performance.weak_documents_count != null
                            ? ` | Weak docs: ${runDetail.summary.performance.weak_documents_count}`
                            : ''}
                        </p>
                      </div>
                    ) : null}
                    {runDetail.results.map((result, index) => (
                      <div
                        key={`${result.control_id}-${index}`}
                        className={`border rounded-lg p-3 ${statusTone(result.match_status)}`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="font-semibold">{result.control_id}</p>
                            <p className="text-xs mt-1">
                              Expected {result.expected_status?.replace(/_/g, ' ')} · Actual {result.actual_status?.replace(/_/g, ' ')}
                            </p>
                          </div>
                          <span className="text-xs px-2 py-0.5 rounded-full bg-white/80 border border-current font-medium">
                            {result.match_status?.replace(/_/g, ' ')}
                          </span>
                        </div>
                        {result.delta?.notes ? (
                          <p className="text-sm mt-2">{result.delta.notes}</p>
                        ) : null}
                        {result.delta?.objective_mismatches?.length ? (
                          <div className="mt-3">
                            <p className="text-xs font-semibold uppercase tracking-wide opacity-75">Objective drift</p>
                            <div className="mt-1 space-y-1">
                              {result.delta.objective_mismatches.slice(0, 5).map((item, idx) => (
                                <p key={idx} className="text-xs">
                                  {item.objective_id}: expected {item.expected_status?.replace(/_/g, ' ')} · actual {item.actual_status?.replace(/_/g, ' ')}
                                </p>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        {result.delta?.missing_citations?.length ? (
                          <div className="mt-3">
                            <p className="text-xs font-semibold uppercase tracking-wide opacity-75">Missing citation expectations</p>
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              {result.delta.missing_citations.slice(0, 5).map((item, idx) => (
                                <span key={idx} className="text-xs px-2 py-0.5 rounded-full bg-white/80 border border-current">
                                  {item}
                                </span>
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
