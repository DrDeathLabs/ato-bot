/**
 * Control Closure Workflow
 *
 * Interactive AI-assisted wizard for closing partial and non-compliant NIST 800-53 Rev 5 controls.
 * Steps: Select Control → AI Interview → Artifact Generation → Approval Routing → Complete
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

// ── Icons (inline SVG to avoid dependency) ────────────────────────────────────
const Icon = ({ name, size = 16, className = '' }) => {
  const icons = {
    close:     <><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></>,
    check:     <><polyline points="20 6 9 12 4 9"/><polyline points="4 9 2 22 20 6"/></>,
    checkCirc: <><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></>,
    arrowR:    <><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></>,
    arrowL:    <><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></>,
    doc:       <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></>,
    loader:    <><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></>,
    alert:     <><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></>,
    shield:    <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></>,
    user:      <><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></>,
    thumbsUp:  <><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></>,
    trash:     <><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></>,
    plus:      <><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></>,
    refresh:   <><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></>,
    x:         <><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></>,
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className={className}>
      {icons[name]}
    </svg>
  )
}

// ── Status helpers ─────────────────────────────────────────────────────────────
const STATUS_COLORS = {
  non_compliant:        { bg: 'bg-red-100',    text: 'text-red-700',    border: 'border-red-200',   label: 'Non-Compliant' },
  partially_compliant:  { bg: 'bg-amber-100',  text: 'text-amber-700',  border: 'border-amber-200', label: 'Partially Compliant' },
  compliant:            { bg: 'bg-emerald-100', text: 'text-emerald-700',border: 'border-emerald-200',label: 'Compliant' },
}

const ARTIFACT_TYPE_LABELS = {
  policy_procedure:  { label: 'Policy & Procedure', color: 'bg-blue-100 text-blue-700' },
  completed_form:    { label: 'Completed Form',      color: 'bg-purple-100 text-purple-700' },
  ssp_narrative:     { label: 'SSP Narrative',       color: 'bg-indigo-100 text-indigo-700' },
  procedure:         { label: 'Procedure',           color: 'bg-teal-100 text-teal-700' },
  evidence_template: { label: 'Evidence Record',     color: 'bg-orange-100 text-orange-700' },
  agreement_template:{ label: 'Agreement',           color: 'bg-pink-100 text-pink-700' },
}

const APPROVAL_STEP_ICONS = ['✍️', '🔍', '🛡️', '✅']

// ── Main Component ────────────────────────────────────────────────────────────
export default function ClosureWorkflow({ projectId, assessmentId, findings }) {
  const qc = useQueryClient()
  const [selectedSession, setSelectedSession] = useState(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [startingControl, setStartingControl] = useState(null)
  const [actionError, setActionError] = useState('')

  const openControls = findings.filter(f =>
    f.status === 'non_compliant' || f.status === 'partially_compliant'
  ).sort((a, b) => {
    const order = { non_compliant: 0, partially_compliant: 1 }
    return (order[a.status] ?? 2) - (order[b.status] ?? 2)
  })

  const { data: sessions = [], refetch: refetchSessions, error: sessionsError } = useQuery({
    queryKey: ['closure-sessions', assessmentId],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/closure/sessions`).then(r => r.data),
  })

  const sessionByControl = Object.fromEntries(sessions.map(s => [s.control_id, s]))

  const startSession = useMutation({
    mutationFn: (controlId) => api.post(
      `/projects/${projectId}/assessments/${assessmentId}/closure/sessions`,
      { control_id: controlId }
    ).then(r => r.data),
    onSuccess: (session) => {
      setActionError('')
      qc.invalidateQueries({ queryKey: ['closure-sessions', assessmentId] })
      setSelectedSession(session)
      setWizardOpen(true)
      setStartingControl(null)
    },
    onError: (e) => {
      setStartingControl(null)
      setActionError(e.response?.data?.detail || 'Unable to start closure workflow')
    },
  })

  const handleOpenSession = (session) => {
    setActionError('')
    setSelectedSession(session)
    setWizardOpen(true)
  }

  const handleStartClosure = (controlId) => {
    setActionError('')
    setStartingControl(controlId)
    startSession.mutate(controlId)
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <div className="flex items-center gap-3 mb-1">
          <Icon name="shield" size={18} className="text-violet-600" />
          <h2 className="text-base font-bold text-gray-900">Control Closure Workflow</h2>
          <span className="text-xs bg-violet-100 text-violet-700 border border-violet-200 px-2.5 py-0.5 rounded-full font-medium">
            NIST RMF — Execute
          </span>
        </div>
        <p className="text-sm text-gray-500 ml-7">
          AI-assisted, evidence-based closure for each open finding. Complete the interview, generate targeted artifacts,
          and route them through a documented approval chain aligned with NIST 800-53 Rev 5 and the RMF.
        </p>
      </div>

      {/* Control list */}
      {openControls.length === 0 ? (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-8 text-center">
          <div className="text-3xl mb-2">✅</div>
          <p className="text-emerald-800 font-semibold">All controls are compliant</p>
          <p className="text-emerald-600 text-sm mt-1">No closure actions are required.</p>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-5 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
              Open Controls — {openControls.length} requiring closure
            </p>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-red-500 inline-block"/>
                Non-Compliant
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-amber-500 inline-block"/>
                Partial
              </span>
            </div>
          </div>
          <div className="divide-y divide-gray-100">
            {openControls.map(f => {
              const sc = STATUS_COLORS[f.status] || STATUS_COLORS.partially_compliant
              const existingSession = sessionByControl[f.control_id]
              const isStarting = startingControl === f.control_id

              return (
                <div key={f.control_id} className="flex items-center justify-between px-5 py-3 hover:bg-gray-50 transition-colors">
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded border flex-shrink-0 ${sc.bg} ${sc.text} ${sc.border}`}>
                      {f.control_id}
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{f.control_title}</p>
                      <p className="text-xs text-gray-400">
                        {(f.gaps || []).length} gap{(f.gaps || []).length !== 1 ? 's' : ''} identified
                        {f.confidence_score != null && ` · ${Math.round(f.confidence_score * 100)}% confidence`}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 ml-4 flex-shrink-0">
                    {existingSession ? (
                      <SessionStatusBadge session={existingSession} onOpen={() => handleOpenSession(existingSession)} />
                    ) : (
                      <button
                        onClick={() => handleStartClosure(f.control_id)}
                        disabled={isStarting}
                        className="flex items-center gap-1.5 text-xs bg-violet-600 hover:bg-violet-700 text-white px-3 py-1.5 rounded-lg font-medium disabled:opacity-50 transition-colors"
                      >
                        {isStarting ? <Icon name="loader" size={12} className="animate-spin" /> : <Icon name="plus" size={12} />}
                        {isStarting ? 'Starting…' : 'Start Closure'}
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {(actionError || sessionsError) && (
        <div className="flex items-center gap-2 text-red-700 text-sm bg-red-50 border border-red-200 rounded-xl px-4 py-3">
          <Icon name="alert" size={14} />
          {actionError || sessionsError?.response?.data?.detail || sessionsError?.message || 'Closure workflow is unavailable right now'}
        </div>
      )}

      {/* Active sessions summary */}
      {sessions.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-5 py-3 bg-gray-50 border-b border-gray-200">
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
              Closure Sessions — {sessions.length} total
            </p>
          </div>
          <div className="divide-y divide-gray-100">
            {sessions.map(s => (
              <div key={s.id} className="flex items-center justify-between px-5 py-3 hover:bg-gray-50">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-bold text-gray-600 bg-gray-100 px-2 py-0.5 rounded">{s.control_id}</span>
                  <div>
                    <p className="text-sm font-medium text-gray-800">{s.control_title}</p>
                    <p className="text-xs text-gray-400">
                      {s.generated_artifact_ids?.length || 0} artifact{(s.generated_artifact_ids?.length || 0) !== 1 ? 's' : ''} generated
                      · {s.approvals?.length || 0} approval{(s.approvals?.length || 0) !== 1 ? 's' : ''}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <SessionStatusBadge session={s} onOpen={() => handleOpenSession(s)} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Wizard Modal */}
      {wizardOpen && selectedSession && (
        <ClosureWizard
          session={selectedSession}
          projectId={projectId}
          assessmentId={assessmentId}
          findings={findings}
          onClose={() => { setWizardOpen(false); setSelectedSession(null); refetchSessions() }}
          onSessionUpdate={(s) => setSelectedSession(s)}
        />
      )}
    </div>
  )
}

// ── Session Status Badge ───────────────────────────────────────────────────────
function SessionStatusBadge({ session, onOpen }) {
  const configs = {
    active:           { label: 'Interview', color: 'bg-blue-100 text-blue-700 border-blue-200',     btn: 'Continue' },
    artifact_pending: { label: 'Ready to Generate', color: 'bg-amber-100 text-amber-700 border-amber-200', btn: 'Generate' },
    in_approval:      { label: 'In Approval',  color: 'bg-violet-100 text-violet-700 border-violet-200', btn: 'Review' },
    closed:           { label: 'Closed',       color: 'bg-emerald-100 text-emerald-700 border-emerald-200', btn: 'View' },
  }
  const cfg = configs[session.session_status] || configs.active
  return (
    <div className="flex items-center gap-2">
      <span className={`text-xs px-2 py-0.5 rounded border font-medium ${cfg.color}`}>{cfg.label}</span>
      <button onClick={onOpen}
        className="text-xs text-violet-600 hover:text-violet-800 font-medium hover:underline">
        {cfg.btn} →
      </button>
    </div>
  )
}

// ── Closure Wizard Modal ──────────────────────────────────────────────────────
function ClosureWizard({ session: initialSession, projectId, assessmentId, findings, onClose, onSessionUpdate }) {
  const qc = useQueryClient()
  const [session, setSession] = useState(initialSession)
  const [activeStep, setActiveStep] = useState(() => {
    if (initialSession.session_status === 'in_approval' || initialSession.session_status === 'closed') return 3
    if (initialSession.session_status === 'artifact_pending') return 2
    return 0
  })

  const finding = findings.find(f => f.control_id === session.control_id)
  const steps = ['Gap Review', 'AI Interview', 'Artifact Generation', 'Approval Routing', 'Complete']

  const updateSession = (s) => {
    setSession(s)
    onSessionUpdate(s)
    if (s.session_status === 'active' && activeStep < 1) setActiveStep(1)
    if (s.session_status === 'artifact_pending' && activeStep < 2) setActiveStep(2)
    if (s.session_status === 'in_approval' && activeStep < 3) setActiveStep(3)
    if (s.session_status === 'closed') setActiveStep(4)
  }

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-start justify-center p-4 overflow-y-auto">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl my-8">
        {/* Modal header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-gray-50 rounded-t-2xl">
          <div>
            <div className="flex items-center gap-3">
              <Icon name="shield" size={18} className="text-violet-600" />
              <h2 className="text-base font-bold text-gray-900">
                Control Closure — {session.control_id}
              </h2>
              <span className="text-xs text-gray-500 font-normal truncate max-w-xs">{session.control_title}</span>
            </div>
            <p className="text-xs text-gray-400 ml-7 mt-0.5">
              NIST 800-53 Rev 5 · RMF Execute · Evidence-Based Closure
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1 rounded">
            <Icon name="x" size={18} />
          </button>
        </div>

        {/* Step indicator */}
        <div className="px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            {steps.map((label, idx) => {
              const isActive = idx === activeStep
              const isDone = idx < activeStep
              return (
                <div key={idx} className="flex items-center gap-2">
                  <button
                    onClick={() => isDone && setActiveStep(idx)}
                    className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium transition-colors ${
                      isActive ? 'bg-violet-600 text-white' :
                      isDone   ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200 cursor-pointer' :
                                 'bg-gray-100 text-gray-400 cursor-default'
                    }`}>
                    {isDone ? <Icon name="checkCirc" size={11} /> : <span>{idx + 1}</span>}
                    {label}
                  </button>
                  {idx < steps.length - 1 && <span className="text-gray-300 text-xs">›</span>}
                </div>
              )
            })}
          </div>
        </div>

        {/* Step content */}
        <div className="p-6">
          {activeStep === 0 && (
            <GapReviewStep
              finding={finding}
              session={session}
              projectId={projectId}
              assessmentId={assessmentId}
              onNext={() => setActiveStep(1)}
            />
          )}
          {activeStep === 1 && (
            <InterviewStep
              session={session}
              projectId={projectId}
              assessmentId={assessmentId}
              onSessionUpdate={updateSession}
              onNext={() => setActiveStep(2)}
            />
          )}
          {activeStep === 2 && (
            <ArtifactGenerationStep
              session={session}
              projectId={projectId}
              assessmentId={assessmentId}
              onSessionUpdate={updateSession}
              onNext={() => setActiveStep(3)}
            />
          )}
          {activeStep === 3 && (
            <ApprovalStep
              session={session}
              projectId={projectId}
              assessmentId={assessmentId}
              onSessionUpdate={updateSession}
              onNext={() => setActiveStep(4)}
            />
          )}
          {activeStep === 4 && (
            <CompletionStep
              session={session}
              projectId={projectId}
              assessmentId={assessmentId}
              onSessionUpdate={updateSession}
              onClose={onClose}
            />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Step 0: Gap Review ────────────────────────────────────────────────────────
function GapReviewStep({ finding, session, projectId, assessmentId, onNext }) {
  const { data: guidance } = useQuery({
    queryKey: ['closure-guidance', assessmentId, session.control_id],
    queryFn: () => api.get(`/projects/${projectId}/assessments/${assessmentId}/closure/controls/${session.control_id}/guidance`).then(r => r.data),
    enabled: Boolean(projectId && assessmentId && session?.control_id),
  })
  if (!finding) return <p className="text-gray-500 text-sm">Finding data not available.</p>

  const sc = STATUS_COLORS[finding.status] || STATUS_COLORS.partially_compliant
  const gaps = Array.isArray(finding.gaps) ? finding.gaps : (finding.gaps ? [finding.gaps] : [])

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
          <Icon name="alert" size={14} className="text-amber-500" />
          Current Compliance Finding
        </h3>
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-3">
            <span className={`text-xs font-bold px-2.5 py-1 rounded-lg border ${sc.bg} ${sc.text} ${sc.border}`}>
              {sc.label}
            </span>
            {finding.confidence_score != null && (
              <span className="text-xs text-gray-500">
                {Math.round(finding.confidence_score * 100)}% assessor confidence
              </span>
            )}
          </div>
          {finding.implementation_statement && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Implementation Statement</p>
              <p className="text-sm text-gray-700 bg-white border border-gray-200 rounded p-3 leading-relaxed">
                {finding.implementation_statement}
              </p>
            </div>
          )}
        </div>
      </div>

      {gaps.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
            <span className="w-4 h-4 bg-red-100 text-red-600 rounded flex items-center justify-center text-xs font-bold">{gaps.length}</span>
            Identified Gaps
          </h3>
          <ul className="space-y-1.5">
            {gaps.map((g, i) => (
              <li key={i} className="flex items-start gap-2.5 text-sm text-gray-700 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                <span className="text-red-400 mt-0.5 flex-shrink-0">✗</span>
                <span>{typeof g === 'string' ? g : JSON.stringify(g)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {finding.remediation_plan && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Recommended Remediation</h3>
          <div className="bg-blue-50 border border-blue-100 rounded-xl p-3 text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
            {finding.remediation_plan}
          </div>
        </div>
      )}

      {guidance && (
        <div className="bg-violet-50 border border-violet-200 rounded-xl p-4 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-violet-900">What Passing Evidence Must Show</h3>
              <p className="text-xs text-violet-700 mt-1">
                This is the deterministic closure contract the engine uses to judge whether the control is truly closed.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 justify-end">
              {(guidance.recommended_artifact_types || []).map(type => (
                <span key={type} className="text-xs px-2 py-1 rounded-full bg-white border border-violet-200 text-violet-700 font-medium">
                  {type.replace(/_/g, ' ')}
                </span>
              ))}
            </div>
          </div>

          <div className="space-y-3">
            {(guidance.objective_contracts || []).map(contract => (
              <div key={contract.objective_id} className="bg-white border border-violet-100 rounded-lg p-3 space-y-3">
                <div>
                  <p className="text-sm font-semibold text-gray-900">{contract.objective_id} — {contract.short_title}</p>
                  {contract.description && (
                    <p className="text-xs text-gray-500 mt-1">{contract.description}</p>
                  )}
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">Required Facts</p>
                    <ul className="space-y-1.5">
                      {(contract.required_facts || []).map((fact, idx) => (
                        <li key={idx} className="text-sm text-gray-700 flex items-start gap-2">
                          <span className="text-violet-500 mt-0.5">•</span>
                          <span>{fact}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">Concrete Example</p>
                    <div className="text-sm text-gray-700 bg-violet-50 border border-violet-100 rounded-lg p-3 leading-relaxed">
                      {contract.example_response}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex justify-end pt-2">
        <button onClick={onNext}
          className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white text-sm px-4 py-2 rounded-lg font-medium transition-colors">
          Start AI Interview
          <Icon name="arrowR" size={14} />
        </button>
      </div>
    </div>
  )
}

// ── Step 1: AI Interview ──────────────────────────────────────────────────────
function InterviewStep({ session, projectId, assessmentId, onSessionUpdate, onNext }) {
  const [answers, setAnswers] = useState({})
  const [error, setError] = useState('')

  // Get the most recent AI question step
  const steps = session.steps || []
  const latestAIStep = [...steps].reverse().find(s => s.role === 'ai' && s.step_type === 'question')
  const latestPlan = [...steps].reverse().find(s => s.role === 'ai' && s.step_type === 'plan')

  const submitAnswers = useMutation({
    mutationFn: (answers) => api.post(
      `/projects/${projectId}/assessments/${assessmentId}/closure/sessions/${session.id}/respond`,
      { answers }
    ).then(r => r.data),
    onSuccess: (updated) => {
      setAnswers({})
      setError('')
      onSessionUpdate(updated)
      if (updated.session_status === 'artifact_pending') onNext()
    },
    onError: (e) => setError(e.response?.data?.detail || 'Submission failed'),
  })

  const handleSubmit = () => {
    if (!latestAIStep) return
    const questions = latestAIStep.content?.questions || []
    const unanswered = questions.filter(q => q.required !== false && !answers[q.id])
    if (unanswered.length) {
      setError(`Please answer: ${unanswered.map(q => q.id).join(', ')}`)
      return
    }
    setError('')
    submitAnswers.mutate(answers)
  }

  if (latestPlan) {
    // Already have a plan — show summary
    return (
      <div className="space-y-4">
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <Icon name="checkCirc" size={16} className="text-emerald-600" />
            <p className="text-sm font-semibold text-emerald-800">Interview Complete</p>
          </div>
          <p className="text-sm text-gray-700">{latestPlan.content?.implementation_summary}</p>
        </div>
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Planned Artifacts</p>
          <div className="space-y-2">
            {(latestPlan.content?.recommended_artifacts || []).map((a, i) => {
              const tc = ARTIFACT_TYPE_LABELS[a.artifact_type] || ARTIFACT_TYPE_LABELS.policy_procedure
              return (
                <div key={i} className="flex items-start gap-3 bg-white border border-gray-200 rounded-lg px-3 py-2.5">
                  <Icon name="doc" size={14} className="text-gray-400 mt-0.5 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800">{a.title}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{a.purpose}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded font-medium flex-shrink-0 ${tc.color}`}>{tc.label}</span>
                </div>
              )
            })}
          </div>
        </div>
        <div className="flex justify-end pt-2">
          <button onClick={onNext}
            className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white text-sm px-4 py-2 rounded-lg font-medium">
            Generate Artifacts
            <Icon name="arrowR" size={14} />
          </button>
        </div>
      </div>
    )
  }

  if (!latestAIStep) return <p className="text-gray-500 text-sm">Loading interview questions…</p>

  const { intro, questions = [] } = latestAIStep.content || {}

  return (
    <div className="space-y-5">
      {/* AI intro */}
      <div className="bg-violet-50 border border-violet-200 rounded-xl p-4">
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 bg-violet-600 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0">AI</div>
          <p className="text-sm text-gray-700 leading-relaxed">{intro}</p>
        </div>
      </div>

      {/* Prior exchanges */}
      {steps.filter(s => s.role === 'user').length > 0 && (
        <details className="text-xs text-gray-500 cursor-pointer">
          <summary className="font-medium">View prior exchanges ({steps.filter(s => s.role === 'user').length} responses)</summary>
          <div className="mt-2 space-y-2 pl-2 border-l-2 border-gray-200">
            {steps.filter(s => s.role === 'user').map((s, i) => (
              <div key={i} className="text-gray-600">
                {Object.entries(s.content || {}).map(([k, v]) => (
                  <p key={k}><span className="font-medium">{k}:</span> {String(v)}</p>
                ))}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Questions */}
      <div className="space-y-4">
        {questions.map(q => (
          <QuestionField key={q.id} question={q} value={answers[q.id]} onChange={v => setAnswers(prev => ({ ...prev, [q.id]: v }))} />
        ))}
      </div>

      {error && (
        <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          <Icon name="alert" size={14} />
          {error}
        </div>
      )}

      <div className="flex justify-end pt-2">
        <button onClick={handleSubmit}
          disabled={submitAnswers.isPending}
          className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white text-sm px-4 py-2 rounded-lg font-medium disabled:opacity-50 transition-colors">
          {submitAnswers.isPending
            ? <><Icon name="loader" size={14} className="animate-spin" /> Analyzing…</>
            : <>Submit Answers <Icon name="arrowR" size={14} /></>}
        </button>
      </div>
    </div>
  )
}

// ── Question Field ─────────────────────────────────────────────────────────────
function QuestionField({ question, value, onChange }) {
  const { id, text, type, options = [], placeholder, nist_context } = question

  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-gray-800">
        {text}
        {question.required !== false && <span className="text-red-400 ml-1">*</span>}
      </label>
      {nist_context && (
        <p className="text-xs text-gray-400 italic">{nist_context}</p>
      )}

      {type === 'boolean' && (
        <div className="flex gap-3">
          {['Yes', 'No'].map(opt => (
            <button key={opt} onClick={() => onChange(opt)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                value === opt
                  ? 'bg-violet-600 text-white border-violet-600'
                  : 'bg-white text-gray-700 border-gray-300 hover:border-violet-400'
              }`}>
              {opt}
            </button>
          ))}
        </div>
      )}

      {type === 'dropdown' && (
        <select
          value={value || ''}
          onChange={e => onChange(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-300 focus:border-violet-400 bg-white">
          <option value="">Select an option…</option>
          {options.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      )}

      {type === 'multiselect' && (
        <div className="space-y-1.5">
          {options.map(o => {
            const selected = Array.isArray(value) ? value.includes(o) : false
            return (
              <label key={o} className="flex items-center gap-2.5 cursor-pointer">
                <input type="checkbox" checked={selected}
                  onChange={e => {
                    const cur = Array.isArray(value) ? value : []
                    onChange(e.target.checked ? [...cur, o] : cur.filter(x => x !== o))
                  }}
                  className="w-4 h-4 rounded border-gray-300 text-violet-600 focus:ring-violet-400" />
                <span className="text-sm text-gray-700">{o}</span>
              </label>
            )
          })}
        </div>
      )}

      {type === 'text' && (
        <textarea
          value={value || ''}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''}
          rows={3}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-300 focus:border-violet-400 resize-none" />
      )}
    </div>
  )
}

// ── Step 2: Artifact Generation ───────────────────────────────────────────────
function ArtifactGenerationStep({ session, projectId, assessmentId, onSessionUpdate, onNext }) {
  const [preparerName, setPreparerName] = useState('')
  const [error, setError] = useState('')

  const planned = session.recommended_artifacts || []
  const alreadyGenerated = (session.generated_artifact_ids || []).length > 0

  const generate = useMutation({
    mutationFn: () => api.post(
      `/projects/${projectId}/assessments/${assessmentId}/closure/sessions/${session.id}/generate-artifacts`,
      { preparer_name: preparerName || 'System User' }
    ).then(r => r.data),
    onSuccess: (updated) => {
      setError('')
      onSessionUpdate(updated)
      if ((updated.generated_artifact_ids || []).length > 0) onNext()
    },
    onError: (e) => setError(e.response?.data?.detail || 'Generation failed'),
  })

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Artifacts to Generate</h3>
        <div className="space-y-2">
          {planned.map((a, i) => {
            const tc = ARTIFACT_TYPE_LABELS[a.artifact_type] || ARTIFACT_TYPE_LABELS.policy_procedure
            return (
              <div key={i} className="flex items-start gap-3 bg-white border border-gray-200 rounded-xl px-4 py-3">
                <Icon name="doc" size={16} className="text-violet-500 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <p className="text-sm font-semibold text-gray-800">{a.title}</p>
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${tc.color}`}>{tc.label}</span>
                  </div>
                  <p className="text-xs text-gray-500">{a.purpose}</p>
                  <p className="text-xs text-gray-400 mt-1">Controls: {(a.controls_addressed || []).join(', ')}</p>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {!alreadyGenerated && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">
            Preparer Name
            <span className="text-gray-400 font-normal ml-1">(your name — appears on approval cover sheet)</span>
          </label>
          <input
            type="text"
            value={preparerName}
            onChange={e => setPreparerName(e.target.value)}
            placeholder="e.g. Jane Smith, ISSO"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 focus:border-violet-400" />
        </div>
      )}

      <div className="bg-blue-50 border border-blue-100 rounded-xl p-4">
        <div className="flex items-start gap-2">
          <Icon name="alert" size={14} className="text-blue-600 mt-0.5 flex-shrink-0" />
          <div className="text-xs text-blue-800 space-y-1">
            <p className="font-semibold">What happens next</p>
            <ul className="space-y-1 text-blue-700">
              <li>• Each artifact is generated as a Word document incorporating your interview responses</li>
              <li>• Documents are saved to the project library and indexed for future assessments</li>
              <li>• An approval chain is created for each artifact (Preparer → Reviewer → ISSO → System Owner)</li>
              <li>• The approval record documents that artifacts were reviewed — not just generated</li>
            </ul>
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          <Icon name="alert" size={14} />
          {error}
        </div>
      )}

      {alreadyGenerated ? (
        <div className="flex justify-between pt-2">
          <div className="flex items-center gap-2 text-emerald-600 text-sm">
            <Icon name="checkCirc" size={16} />
            {session.generated_artifact_ids.length} artifact{session.generated_artifact_ids.length !== 1 ? 's' : ''} generated
          </div>
          <button onClick={onNext}
            className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white text-sm px-4 py-2 rounded-lg font-medium">
            Review Approvals
            <Icon name="arrowR" size={14} />
          </button>
        </div>
      ) : (
        <div className="flex justify-end pt-2">
          <button onClick={() => generate.mutate()}
            disabled={generate.isPending}
            className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white text-sm px-4 py-2 rounded-lg font-medium disabled:opacity-50 transition-colors">
            {generate.isPending
              ? <><Icon name="loader" size={14} className="animate-spin" /> Generating {planned.length} artifact{planned.length !== 1 ? 's' : ''}…</>
              : <><Icon name="doc" size={14} /> Generate Artifacts</>}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Step 3: Approval Routing ──────────────────────────────────────────────────
function ApprovalStep({ session, projectId, assessmentId, onSessionUpdate, onNext }) {
  const [approvals, setApprovals] = useState(session.approvals || [])
  const [error, setError] = useState('')

  // Refresh approvals from server
  const { data: freshApprovals, refetch } = useQuery({
    queryKey: ['closure-approvals', session.id],
    queryFn: () => api.get(
      `/projects/${projectId}/assessments/${assessmentId}/closure/sessions/${session.id}/approvals`
    ).then(r => r.data),
    initialData: session.approvals || [],
  })

  const allApproved = (freshApprovals || []).every(a => a.overall_status === 'approved')
  const anyRejected = (freshApprovals || []).some(a => a.overall_status === 'rejected')

  const advance = useMutation({
    mutationFn: ({ approvalId, body }) => api.post(
      `/projects/${projectId}/assessments/${assessmentId}/closure/sessions/${session.id}/approvals/${approvalId}/advance`,
      body
    ).then(r => r.data),
    onSuccess: () => { refetch(); setError('') },
    onError: (e) => setError(e.response?.data?.detail || 'Action failed'),
  })

  return (
    <div className="space-y-5">
      <div className="bg-violet-50 border border-violet-100 rounded-xl p-4">
        <div className="flex items-start gap-2.5">
          <Icon name="shield" size={15} className="text-violet-600 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-violet-800">
            <p className="font-semibold mb-1">NIST RMF Approval Requirement</p>
            <p className="text-violet-700 text-xs leading-relaxed">
              Per NIST SP 800-37 Rev 2 (RMF Execute, Task E-2), implementation evidence must be reviewed and approved by
              appropriate personnel before a control is considered closed. Each artifact requires sign-off from a
              Technical Reviewer, ISSO, and System Owner.
            </p>
          </div>
        </div>
      </div>

      {(freshApprovals || []).map((approval) => (
        <ApprovalCard
          key={approval.id}
          approval={approval}
          onAction={(body) => advance.mutate({ approvalId: approval.id, body })}
          isPending={advance.isPending}
        />
      ))}

      {error && (
        <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          <Icon name="alert" size={14} /> {error}
        </div>
      )}

      <div className="flex justify-between items-center pt-2">
        <div className="text-xs text-gray-500">
          {allApproved ? '✅ All artifacts approved' :
           anyRejected ? '❌ One or more artifacts rejected — revise and re-generate' :
           `${(freshApprovals || []).filter(a => a.overall_status === 'approved').length}/${(freshApprovals || []).length} approved`}
        </div>
        <div className="flex gap-2">
          <button onClick={onNext}
            className="flex items-center gap-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm px-4 py-2 rounded-lg font-medium">
            Skip to Completion
          </button>
          {allApproved && (
            <button onClick={onNext}
              className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white text-sm px-4 py-2 rounded-lg font-medium">
              Complete Closure <Icon name="arrowR" size={14} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Approval Card ─────────────────────────────────────────────────────────────
function ApprovalCard({ approval, onAction, isPending }) {
  const [form, setForm] = useState({ name: '', title: '', org: '', comments: '' })
  const [expanded, setExpanded] = useState(approval.overall_status !== 'approved')

  const chain = approval.approval_chain || []
  const currentStep = approval.current_step
  const pendingStepData = chain[currentStep]

  const tc = ARTIFACT_TYPE_LABELS[approval.artifact_type] || ARTIFACT_TYPE_LABELS.policy_procedure

  const STATUS_BADGE = {
    approved:       'bg-emerald-100 text-emerald-700 border-emerald-200',
    rejected:       'bg-red-100 text-red-700 border-red-200',
    pending:        'bg-gray-100 text-gray-500 border-gray-200',
    in_review:      'bg-amber-100 text-amber-700 border-amber-200',
    pending_review: 'bg-amber-100 text-amber-700 border-amber-200',
  }

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left">
        <div className="flex items-center gap-3">
          <Icon name="doc" size={14} className="text-gray-500" />
          <div>
            <p className="text-sm font-semibold text-gray-800">{approval.artifact_title}</p>
            <p className="text-xs text-gray-400">{approval.control_id}</p>
          </div>
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${tc.color}`}>{tc.label}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2.5 py-0.5 rounded border font-medium ${STATUS_BADGE[approval.overall_status] || STATUS_BADGE.pending}`}>
            {approval.overall_status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
          </span>
          <span className="text-gray-400">{expanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {expanded && (
        <div className="p-4 space-y-4">
          {/* Approval chain steps */}
          <div className="space-y-2">
            {chain.map((step, idx) => (
              <div key={idx} className={`flex items-start gap-3 rounded-lg p-3 border ${
                idx === currentStep && approval.overall_status !== 'approved' && approval.overall_status !== 'rejected'
                  ? 'bg-violet-50 border-violet-200'
                  : step.status === 'approved'
                  ? 'bg-emerald-50 border-emerald-100'
                  : step.status === 'rejected'
                  ? 'bg-red-50 border-red-100'
                  : 'bg-gray-50 border-gray-100'
              }`}>
                <span className="text-base flex-shrink-0 mt-0.5">{APPROVAL_STEP_ICONS[idx] || '📋'}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold text-gray-700">{step.label}</p>
                    <span className={`text-xs px-2 py-0.5 rounded border ${STATUS_BADGE[step.status] || STATUS_BADGE.pending}`}>
                      {step.status.replace(/_/g, ' ')}
                    </span>
                  </div>
                  {step.name && <p className="text-xs text-gray-600 mt-0.5">{step.name}{step.title ? ` · ${step.title}` : ''}{step.organization ? ` · ${step.organization}` : ''}</p>}
                  {step.comments && <p className="text-xs text-gray-500 italic mt-0.5">"{step.comments}"</p>}
                  {step.completed_at && <p className="text-xs text-gray-400 mt-0.5">{new Date(step.completed_at).toLocaleString()}</p>}
                </div>
              </div>
            ))}
          </div>

          {/* Action form for current pending step */}
          {pendingStepData && approval.overall_status !== 'approved' && approval.overall_status !== 'rejected' && (
            <div className="border-t border-gray-200 pt-4 space-y-3">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
                Action Required — {pendingStepData.label}
              </p>
              <div className="grid grid-cols-3 gap-3">
                <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  placeholder="Full name *" required
                  className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 col-span-1" />
                <input value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                  placeholder="Title / Role"
                  className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300" />
                <input value={form.org} onChange={e => setForm(f => ({ ...f, org: e.target.value }))}
                  placeholder="Organization"
                  className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300" />
              </div>
              <textarea value={form.comments} onChange={e => setForm(f => ({ ...f, comments: e.target.value }))}
                placeholder="Comments (optional)"
                rows={2}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none" />
              <div className="flex gap-2">
                <button
                  onClick={() => onAction({ approver_name: form.name, approver_title: form.title, approver_org: form.org, action: 'approve', comments: form.comments })}
                  disabled={isPending || !form.name.trim()}
                  className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-sm px-4 py-1.5 rounded-lg font-medium disabled:opacity-50 transition-colors">
                  <Icon name="thumbsUp" size={13} /> Approve
                </button>
                <button
                  onClick={() => onAction({ approver_name: form.name, approver_title: form.title, approver_org: form.org, action: 'reject', comments: form.comments })}
                  disabled={isPending || !form.name.trim()}
                  className="flex items-center gap-1.5 bg-red-100 hover:bg-red-200 text-red-700 text-sm px-4 py-1.5 rounded-lg font-medium disabled:opacity-50 transition-colors">
                  <Icon name="x" size={13} /> Reject
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Step 4: Completion ────────────────────────────────────────────────────────
function CompletionStep({ session, projectId, assessmentId, onSessionUpdate, onClose }) {
  const [notes, setNotes] = useState(session.closure_notes || '')
  const [saved, setSaved] = useState(session.session_status === 'closed')

  const complete = useMutation({
    mutationFn: () => api.post(
      `/projects/${projectId}/assessments/${assessmentId}/closure/sessions/${session.id}/complete`,
      { closure_notes: notes }
    ).then(r => r.data),
    onSuccess: (updated) => {
      setSaved(true)
      onSessionUpdate(updated)
    },
  })

  return (
    <div className="space-y-5">
      {saved ? (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5 text-center">
          <div className="text-4xl mb-2">✅</div>
          <p className="text-emerald-800 font-bold text-base">Closure Workflow Complete</p>
          <p className="text-emerald-600 text-sm mt-1">
            {session.generated_artifact_ids?.length || 0} artifact{(session.generated_artifact_ids?.length || 0) !== 1 ? 's' : ''} generated and routed for approval.
            {' '}Re-run the assessment to validate compliance after documents are indexed.
          </p>
        </div>
      ) : (
        <div className="bg-violet-50 border border-violet-200 rounded-xl p-4">
          <p className="text-sm font-semibold text-violet-800 mb-1">Closure Summary</p>
          <ul className="text-sm text-violet-700 space-y-1">
            <li>✓ Control: {session.control_id} — {session.control_title}</li>
            <li>✓ {session.generated_artifact_ids?.length || 0} artifact{(session.generated_artifact_ids?.length || 0) !== 1 ? 's' : ''} generated and saved to the project library</li>
            <li>✓ Approval chain initiated — artifacts will be indexed after approval</li>
            <li>✓ Implementation summary documented in closure record</li>
          </ul>
        </div>
      )}

      {session.implementation_summary && (
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Implementation Summary (from interview)</p>
          <p className="text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-xl p-3 leading-relaxed">
            {session.implementation_summary}
          </p>
        </div>
      )}

      {!saved && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">
            Closure Notes <span className="text-gray-400 font-normal">(optional — added to the closure record)</span>
          </label>
          <textarea value={notes} onChange={e => setNotes(e.target.value)}
            placeholder="Any additional notes about this closure…"
            rows={3}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none" />
        </div>
      )}

      <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-xs text-blue-800 space-y-1">
        <p className="font-semibold">Next Steps (NIST RMF)</p>
        <ul className="text-blue-700 space-y-1">
          <li>1. Ensure all approvals in the chain are completed</li>
          <li>2. Wait for documents to finish indexing (status: Indexed)</li>
          <li>3. Re-run the assessment and explicitly enable carry-forward if unchanged compliant controls should be reused</li>
          <li>4. If still partial, review the artifact content and refine</li>
          <li>5. Update the system POAM if this control was a POA&amp;M item</li>
        </ul>
      </div>

      <div className="flex justify-between pt-2">
        <button onClick={onClose}
          className="text-sm text-gray-500 hover:text-gray-700 px-4 py-2 rounded-lg border border-gray-200 hover:border-gray-300 transition-colors">
          Close
        </button>
        {!saved && (
          <button onClick={() => complete.mutate()}
            disabled={complete.isPending}
            className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white text-sm px-5 py-2 rounded-lg font-medium disabled:opacity-50 transition-colors">
            {complete.isPending
              ? <><Icon name="loader" size={14} className="animate-spin" /> Saving…</>
              : <><Icon name="checkCirc" size={14} /> Mark Complete</>}
          </button>
        )}
        {saved && (
          <button onClick={onClose}
            className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm px-5 py-2 rounded-lg font-medium">
            Done
          </button>
        )}
      </div>
    </div>
  )
}
