import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  CheckCircle2,
  Copy,
  Trash2,
  RefreshCw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react'
import api from '../api/client'

function NumberInput({ value, onChange, min = 0, max = 2, step = 0.05, disabled = false }) {
  return (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
      className="w-24 rounded-lg border border-gray-200 px-2 py-1.5 text-sm"
    />
  )
}

function Toggle({ checked, onChange, disabled = false }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold transition-colors ${
        checked ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'
      } ${disabled ? 'opacity-60 cursor-not-allowed' : ''}`}
    >
      {checked ? 'Yes' : 'No'}
    </button>
  )
}

function SummaryCard({ label, value, hint }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-bold text-gray-900">{value}</p>
      {hint ? <p className="mt-1 text-xs text-gray-500">{hint}</p> : null}
    </div>
  )
}

const THRESHOLD_FIELDS = [
  ['compliant_threshold', 'Compliant threshold'],
  ['partial_threshold', 'Partial threshold'],
  ['minimum_evidence_quality_for_compliant', 'Minimum evidence quality'],
  ['max_contradiction_for_compliant', 'Max contradiction for compliant'],
  ['manual_review_contradiction_threshold', 'Manual review contradiction'],
  ['manual_review_weak_evidence_threshold', 'Manual review weak evidence'],
]

export default function AssessmentPolicyPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [selectedPolicyId, setSelectedPolicyId] = useState(null)
  const [draftState, setDraftState] = useState(null)
  const [saveMessage, setSaveMessage] = useState('')

  const { data: policies = [], isLoading: policiesLoading } = useQuery({
    queryKey: ['assessment-policies'],
    queryFn: () => api.get('/assessment-policy').then((r) => r.data),
  })

  const { data: activePolicy } = useQuery({
    queryKey: ['assessment-policy-active'],
    queryFn: () => api.get('/assessment-policy/active').then((r) => r.data),
  })

  useEffect(() => {
    if (!selectedPolicyId && policies.length) {
      const preferred = policies.find((policy) => policy.status === 'active') || policies.find((policy) => policy.status === 'draft') || policies[0]
      setSelectedPolicyId(preferred.id)
    }
  }, [policies, selectedPolicyId])

  const { data: selectedPolicy, isLoading: selectedLoading } = useQuery({
    queryKey: ['assessment-policy', selectedPolicyId],
    queryFn: () => api.get(`/assessment-policy/${selectedPolicyId}`).then((r) => r.data),
    enabled: !!selectedPolicyId,
  })

  const { data: preview } = useQuery({
    queryKey: ['assessment-policy-preview', selectedPolicyId],
    queryFn: () => api.get(`/assessment-policy/${selectedPolicyId}/preview`).then((r) => r.data),
    enabled: !!selectedPolicyId,
  })

  useEffect(() => {
    if (selectedPolicy) {
      setDraftState(JSON.parse(JSON.stringify(selectedPolicy)))
      setSaveMessage('')
    }
  }, [selectedPolicy])

  const createDraftMutation = useMutation({
    mutationFn: (policyId) => api.post(`/assessment-policy/${policyId}/clone`).then((r) => r.data),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['assessment-policies'] })
      qc.invalidateQueries({ queryKey: ['assessment-policy-active'] })
      setSelectedPolicyId(data.id)
    },
  })

  const activateMutation = useMutation({
    mutationFn: (policyId) => api.post(`/assessment-policy/${policyId}/activate`).then((r) => r.data),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['assessment-policies'] })
      qc.invalidateQueries({ queryKey: ['assessment-policy-active'] })
      qc.invalidateQueries({ queryKey: ['assessment-policy', data.id] })
      qc.invalidateQueries({ queryKey: ['assessment-policy-preview', data.id] })
      setSelectedPolicyId(data.id)
      setSaveMessage('Draft activated. New assessments will use this policy.')
    },
  })

  const deleteDraftMutation = useMutation({
    mutationFn: (policyId) => api.delete(`/assessment-policy/${policyId}`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assessment-policies'] })
      qc.invalidateQueries({ queryKey: ['assessment-policy-active'] })
      qc.invalidateQueries({ queryKey: ['assessment-policy', selectedPolicyId] })
      qc.invalidateQueries({ queryKey: ['assessment-policy-preview', selectedPolicyId] })
      setDraftState(null)
      setSelectedPolicyId(activePolicy?.id || null)
      setSaveMessage('Draft deleted.')
    },
  })

  const saveMutation = useMutation({
    mutationFn: async (state) => {
      const metadataPayload = {
        name: state.name,
        description: state.description,
        notes: state.notes,
        default_thresholds: state.default_thresholds || {},
      }
      await api.patch(`/assessment-policy/${state.id}`, metadataPayload)
      for (const bucket of state.buckets || []) {
        await api.patch(`/assessment-policy/${state.id}/buckets/${bucket.bucket_key}`, {
          label: bucket.label,
          description: bucket.description,
          sort_order: bucket.sort_order,
          objective_weight: bucket.objective_weight,
          critical_by_default: bucket.critical_by_default,
          minimum_evidence_strength: bucket.minimum_evidence_strength,
          negative_evidence_penalty: bucket.negative_evidence_penalty,
          contradiction_penalty: bucket.contradiction_penalty,
          future_state_cap: bucket.future_state_cap,
          inheritance_allowed: bucket.inheritance_allowed,
          compensating_allowed: bucket.compensating_allowed,
          confidence_cap_if_only_weak_evidence: bucket.confidence_cap_if_only_weak_evidence,
          confidence_cap_if_compensating_only: bucket.confidence_cap_if_compensating_only,
          active: bucket.active,
        })
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assessment-policies'] })
      qc.invalidateQueries({ queryKey: ['assessment-policy', selectedPolicyId] })
      qc.invalidateQueries({ queryKey: ['assessment-policy-preview', selectedPolicyId] })
      qc.invalidateQueries({ queryKey: ['assessment-policy-active'] })
      setSaveMessage('Draft policy saved.')
    },
  })

  const bucketChange = (bucketKey, field, value) => {
    setDraftState((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        buckets: prev.buckets.map((bucket) =>
          bucket.bucket_key === bucketKey ? { ...bucket, [field]: value } : bucket
        ),
      }
    })
  }

  const thresholdChange = (field, value) => {
    setDraftState((prev) => ({
      ...prev,
      default_thresholds: {
        ...(prev?.default_thresholds || {}),
        [field]: value,
      },
    }))
  }

  const sortedBuckets = useMemo(
    () => [...(draftState?.buckets || [])].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)),
    [draftState]
  )

  const canEdit = draftState?.status === 'draft'
  const canCreateDraft = !!selectedPolicyId && draftState?.status !== 'draft'
  const changedBucketCount = preview?.impact_summary?.changed_bucket_count || 0

  return (
    <div className="p-8 max-w-7xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate(-1)}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            <ArrowLeft size={16} />
            Back
          </button>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Assessment Policy</h1>
            <p className="mt-1 text-sm text-gray-500">
              Organization-wide adjudication settings for how ATO Bot scores evidence and controls.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              qc.invalidateQueries({ queryKey: ['assessment-policies'] })
              qc.invalidateQueries({ queryKey: ['assessment-policy', selectedPolicyId] })
              qc.invalidateQueries({ queryKey: ['assessment-policy-preview', selectedPolicyId] })
              qc.invalidateQueries({ queryKey: ['assessment-policy-active'] })
            }}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <RefreshCw size={16} />
            Refresh
          </button>
          {canCreateDraft ? (
            <button
              onClick={() => createDraftMutation.mutate(selectedPolicyId)}
              className="inline-flex items-center gap-2 rounded-lg border border-violet-300 px-4 py-2 text-sm font-medium text-violet-700 hover:bg-violet-50"
            >
              <Copy size={16} />
              Create Editable Draft
            </button>
          ) : null}
          {canEdit ? (
            <button
              onClick={() => saveMutation.mutate(draftState)}
              disabled={saveMutation.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <Save size={16} />
              {saveMutation.isPending ? 'Saving...' : 'Save Draft'}
            </button>
          ) : null}
          {canEdit ? (
            <button
              onClick={() => activateMutation.mutate(draftState.id)}
              disabled={activateMutation.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              <CheckCircle2 size={16} />
              {activateMutation.isPending ? 'Activating...' : 'Activate Draft'}
            </button>
          ) : null}
          {canEdit ? (
            <button
              onClick={() => {
                if (window.confirm('Delete this draft policy? This will not affect the active policy.')) {
                  deleteDraftMutation.mutate(draftState.id)
                }
              }}
              disabled={deleteDraftMutation.isPending}
              className="inline-flex items-center gap-2 rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
            >
              <Trash2 size={16} />
              {deleteDraftMutation.isPending ? 'Deleting...' : 'Delete Draft'}
            </button>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <SummaryCard label="Policies" value={policies.length} hint="Active, draft, and retired versions" />
        <SummaryCard label="Active Version" value={activePolicy?.version ?? '—'} hint={activePolicy?.name || 'No active policy'} />
        <SummaryCard label="Buckets" value={draftState?.buckets?.length ?? 0} hint="Calibration buckets in this policy" />
        <SummaryCard label="Changed Buckets" value={changedBucketCount} hint={preview?.impact_summary?.impact_note || 'Preview compares this policy to the active version'} />
      </div>

      {saveMessage ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {saveMessage}
        </div>
      ) : null}

      <div className="grid grid-cols-1 xl:grid-cols-[320px,minmax(0,1fr)] gap-6">
        <div className="space-y-4">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex items-center gap-2 mb-4">
              <ShieldCheck size={16} className="text-emerald-600" />
              <h2 className="font-semibold text-gray-900">Policy Versions</h2>
            </div>
            <div className="space-y-3">
              {policiesLoading ? (
                <p className="text-sm text-gray-500">Loading policies...</p>
              ) : (
                policies.map((policy) => (
                  <button
                    key={policy.id}
                    onClick={() => setSelectedPolicyId(policy.id)}
                    className={`w-full rounded-xl border p-4 text-left transition-colors ${
                      selectedPolicyId === policy.id ? 'border-blue-300 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-semibold text-gray-900 truncate">{policy.name}</p>
                        <p className="mt-1 text-xs text-gray-500">Version {policy.version}</p>
                      </div>
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                          policy.status === 'active'
                            ? 'bg-emerald-100 text-emerald-700'
                            : policy.status === 'draft'
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {policy.status}
                      </span>
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>

          <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-5 text-sm text-indigo-900">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles size={16} className="text-indigo-600" />
              <p className="font-semibold">How this works</p>
            </div>
            <p>
              This policy is organization-wide. Projects should change risk acceptance, inheritance, or compensating controls, not the way scoring itself works.
            </p>
            <p className="mt-2">
              Create Editable Draft makes a safe copy of the selected policy. You edit the draft, review the impact, and only change organization scoring after you activate that draft.
            </p>
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Policy Summary</p>
                <h2 className="mt-1 text-xl font-semibold text-gray-900">
                  {draftState?.name || 'Select a policy'}
                </h2>
              </div>
              <span
                className={`rounded-full px-3 py-1 text-xs font-semibold ${
                  draftState?.status === 'active'
                    ? 'bg-emerald-100 text-emerald-700'
                    : draftState?.status === 'draft'
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-gray-100 text-gray-600'
                }`}
              >
                {draftState?.status || '—'}
              </span>
            </div>

            {selectedLoading || !draftState ? (
              <p className="mt-4 text-sm text-gray-500">Loading policy details...</p>
            ) : (
              <div className="mt-4 space-y-4">
                {canEdit ? (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    You are editing a draft. Changes here do not affect assessments until you activate this draft.
                  </div>
                ) : (
                  <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600">
                    Active and retired policies are read-only. Create an editable draft to make changes safely.
                  </div>
                )}
                <input
                  value={draftState.name || ''}
                  disabled={!canEdit}
                  onChange={(e) => setDraftState((prev) => ({ ...prev, name: e.target.value }))}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
                />
                <textarea
                  value={draftState.description || ''}
                  disabled={!canEdit}
                  onChange={(e) => setDraftState((prev) => ({ ...prev, description: e.target.value }))}
                  rows={3}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
                />
                <textarea
                  value={draftState.notes || ''}
                  disabled={!canEdit}
                  onChange={(e) => setDraftState((prev) => ({ ...prev, notes: e.target.value }))}
                  rows={2}
                  placeholder="Policy notes"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
                />
              </div>
            )}
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex items-center gap-2 mb-4">
              <SlidersHorizontal size={16} className="text-blue-600" />
              <h2 className="font-semibold text-gray-900">Thresholds</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {THRESHOLD_FIELDS.map(([field, label]) => (
                <label key={field} className="space-y-1">
                  <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">{label}</span>
                  <NumberInput
                    value={draftState?.default_thresholds?.[field] ?? ''}
                    onChange={(value) => thresholdChange(field, value)}
                    disabled={!canEdit}
                  />
                </label>
              ))}
              <div className="space-y-2">
                <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Critical failure blocks compliant</span>
                <Toggle
                  checked={!!draftState?.default_thresholds?.critical_failure_blocks_compliant}
                  onChange={(value) => thresholdChange('critical_failure_blocks_compliant', value)}
                  disabled={!canEdit}
                />
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Bucket Calibration</p>
                <h2 className="mt-1 text-lg font-semibold text-gray-900">Organization scoring buckets</h2>
              </div>
              <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold text-gray-600">
                {sortedBuckets.length} buckets
              </span>
            </div>
            <div className="space-y-4">
              {sortedBuckets.map((bucket) => {
                const previewBucket = preview?.bucket_preview?.find((item) => item.bucket_key === bucket.bucket_key)
                return (
                  <div key={bucket.bucket_key} className="rounded-xl border border-gray-200 p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="font-semibold text-gray-900">{bucket.label}</h3>
                        <p className="mt-1 text-sm text-gray-500">{bucket.description}</p>
                      </div>
                      {previewBucket?.changed_from_active ? (
                        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700">
                          changed from active
                        </span>
                      ) : null}
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                      <span className="rounded-full bg-blue-50 px-2.5 py-1 font-medium text-blue-700">
                        {previewBucket?.mapped_controls_count || 0} controls
                      </span>
                      <span className="rounded-full bg-violet-50 px-2.5 py-1 font-medium text-violet-700">
                        {previewBucket?.mapped_objectives_count || 0} objectives
                      </span>
                      {(previewBucket?.families || []).slice(0, 5).map((family) => (
                        <span key={family} className="rounded-full bg-gray-100 px-2 py-1 font-medium text-gray-600">
                          {family}
                        </span>
                      ))}
                    </div>

                    <div className="mt-4 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
                      <label className="space-y-1">
                        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Weight</span>
                        <NumberInput value={bucket.objective_weight} onChange={(value) => bucketChange(bucket.bucket_key, 'objective_weight', value)} disabled={!canEdit} />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Min evidence</span>
                        <NumberInput value={bucket.minimum_evidence_strength} onChange={(value) => bucketChange(bucket.bucket_key, 'minimum_evidence_strength', value)} disabled={!canEdit} />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Negative penalty</span>
                        <NumberInput value={bucket.negative_evidence_penalty} onChange={(value) => bucketChange(bucket.bucket_key, 'negative_evidence_penalty', value)} disabled={!canEdit} />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Contradiction</span>
                        <NumberInput value={bucket.contradiction_penalty} onChange={(value) => bucketChange(bucket.bucket_key, 'contradiction_penalty', value)} disabled={!canEdit} />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Future-state cap</span>
                        <NumberInput value={bucket.future_state_cap} onChange={(value) => bucketChange(bucket.bucket_key, 'future_state_cap', value)} disabled={!canEdit} />
                      </label>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-3">
                      <div className="space-y-1">
                        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Critical by default</span>
                        <Toggle checked={!!bucket.critical_by_default} onChange={(value) => bucketChange(bucket.bucket_key, 'critical_by_default', value)} disabled={!canEdit} />
                      </div>
                      <div className="space-y-1">
                        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Inheritance allowed</span>
                        <Toggle checked={!!bucket.inheritance_allowed} onChange={(value) => bucketChange(bucket.bucket_key, 'inheritance_allowed', value)} disabled={!canEdit} />
                      </div>
                      <div className="space-y-1">
                        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Compensating allowed</span>
                        <Toggle checked={!!bucket.compensating_allowed} onChange={(value) => bucketChange(bucket.bucket_key, 'compensating_allowed', value)} disabled={!canEdit} />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles size={16} className="text-violet-600" />
              <h2 className="font-semibold text-gray-900">Impact Preview</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <SummaryCard label="Changed Buckets" value={preview?.impact_summary?.changed_bucket_count ?? 0} />
              <SummaryCard label="Catalog Controls" value={preview?.impact_summary?.catalog_control_count ?? 0} />
              <SummaryCard label="Catalog Objectives" value={preview?.impact_summary?.catalog_objective_count ?? 0} />
              <SummaryCard label="Buckets With Mappings" value={preview?.impact_summary?.affected_bucket_count ?? 0} />
            </div>
            <p className="mt-4 text-sm text-gray-500">
              {preview?.impact_summary?.impact_note || 'Select a policy to review bucket impact.'}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
