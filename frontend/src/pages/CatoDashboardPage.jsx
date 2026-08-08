import { Fragment, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  Building2,
  ChevronRight,
  Download,
  Globe,
  MessageSquare,
  Search,
  Server,
  ShieldCheck,
  X,
} from 'lucide-react'
import api from '../api/client'
import { openCyberAssistant } from '../components/cyberAssistant'

const DOMAIN_STYLES = {
  'Identity & Access': { bar: 'bg-sky-600', chip: 'bg-sky-50 text-sky-700 border-sky-200' },
  'Platform & Container Security': { bar: 'bg-cyan-600', chip: 'bg-cyan-50 text-cyan-700 border-cyan-200' },
  'Configuration & Secrets': { bar: 'bg-violet-600', chip: 'bg-violet-50 text-violet-700 border-violet-200' },
  'Monitoring & Audit': { bar: 'bg-emerald-600', chip: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  'Boundary & Session Security': { bar: 'bg-amber-500', chip: 'bg-amber-50 text-amber-700 border-amber-200' },
  'Remediation & Risk': { bar: 'bg-rose-600', chip: 'bg-rose-50 text-rose-700 border-rose-200' },
  'Operational Resilience': { bar: 'bg-slate-600', chip: 'bg-slate-100 text-slate-700 border-slate-200' },
}

const OVERVIEW_LENS_SELECTED = {
  needs_attention: 'border-rose-400 ring-2 ring-rose-200 bg-white',
  runtime_risk: 'border-amber-400 ring-2 ring-amber-200 bg-white',
  build_risk: 'border-violet-400 ring-2 ring-violet-200 bg-white',
  drift_since_build: 'border-sky-400 ring-2 ring-sky-200 bg-white',
  evidence_gaps: 'border-slate-400 ring-2 ring-slate-200 bg-white',
}

const OVERVIEW_GROUP_ORDER = {
  source: ['live', 'build', 'change', 'evidence'],
  severity: ['critical', 'high', 'medium', 'low'],
}

function getDomain(group = '') {
  const lower = group.toLowerCase()
  if (lower.includes('access')) return 'Identity & Access'
  if (lower.includes('container')) return 'Platform & Container Security'
  if (lower.includes('secrets') || lower.includes('configuration') || lower.includes('build')) return 'Configuration & Secrets'
  if (lower.includes('audit') || lower.includes('monitor')) return 'Monitoring & Audit'
  if (lower.includes('boundary') || lower.includes('browser')) return 'Boundary & Session Security'
  if (lower.includes('remediation') || lower.includes('risk')) return 'Remediation & Risk'
  if (lower.includes('operational') || lower.includes('service')) return 'Operational Resilience'
  return 'Monitoring & Audit'
}

function statusLabel(status) {
  if (status === 'completed') return 'Completed'
  if (status === 'attention') return 'Needs Attention'
  return 'In Progress'
}

function statusTone(status) {
  if (status === 'completed') return 'bg-emerald-100 text-emerald-700 border-emerald-200'
  if (status === 'attention') return 'bg-rose-100 text-rose-700 border-rose-200'
  return 'bg-amber-100 text-amber-700 border-amber-200'
}

function severityTone(severity) {
  if (severity === 'critical') return 'bg-red-100 text-red-700 border-red-200'
  if (severity === 'high') return 'bg-rose-100 text-rose-700 border-rose-200'
  if (severity === 'medium') return 'bg-amber-100 text-amber-700 border-amber-200'
  return 'bg-slate-100 text-slate-700 border-slate-200'
}

function severityRank(severity) {
  if (severity === 'critical') return 4
  if (severity === 'high') return 3
  if (severity === 'medium') return 2
  return 1
}

function changeStatusTone(status) {
  if (status === 'needs_review') return 'bg-rose-100 text-rose-700 border-rose-200'
  if (status === 'expected') return 'bg-emerald-100 text-emerald-700 border-emerald-200'
  return 'bg-slate-100 text-slate-700 border-slate-200'
}

function reviewStatusTone(status) {
  if (status === 'Regressed') return 'bg-rose-100 text-rose-700 border-rose-200'
  if (status === 'To address') return 'bg-amber-100 text-amber-700 border-amber-200'
  if (status === 'Planned') return 'bg-sky-100 text-sky-700 border-sky-200'
  if (status === 'Risk accepted') return 'bg-slate-100 text-slate-700 border-slate-200'
  if (status === 'Recently added' || status === 'Recently updated') return 'bg-violet-100 text-violet-700 border-violet-200'
  return 'bg-emerald-100 text-emerald-700 border-emerald-200'
}

function verificationStatusTone(status) {
  if (status === 'fail' || status === 'error') return 'bg-rose-100 text-rose-700 border-rose-200'
  if (status === 'degraded') return 'bg-amber-100 text-amber-700 border-amber-200'
  return 'bg-emerald-100 text-emerald-700 border-emerald-200'
}

function summarizeChangeHeadline(item) {
  if (!item) return 'No tracked changes yet.'
  const label = item.details?.setting_label || item.category || item.summary || 'Tracked setting'
  const normalized = String(label).toLowerCase()
  if (normalized.includes('image digest')) return 'Image digest changed'
  if (normalized.includes('dependency vulnerability count')) return 'Dependency vulnerability count changed'
  if (normalized.includes('image scan')) return 'Image scan coverage changed'
  if (normalized.includes('healthcheck')) return 'Container healthcheck posture changed'
  if (normalized.includes('mutable image')) return 'Image tag mutability changed'
  return String(label)
}

function severityRailTone(severity) {
  if (severity === 'critical') return 'bg-red-500'
  if (severity === 'high') return 'bg-rose-500'
  if (severity === 'medium') return 'bg-amber-500'
  return 'bg-slate-400'
}

function queueSourceMeta(source) {
  if (source === 'app') {
    return {
      label: 'App API',
      tone: 'bg-violet-50 text-violet-700 border-violet-200',
      Icon: ShieldCheck,
    }
  }
  if (source === 'live') {
    return {
      label: 'Live',
      tone: 'bg-amber-50 text-amber-700 border-amber-200',
      Icon: Server,
    }
  }
  if (source === 'build') {
    return {
      label: 'Build',
      tone: 'bg-violet-50 text-violet-700 border-violet-200',
      Icon: Building2,
    }
  }
  if (source === 'change') {
    return {
      label: 'Change',
      tone: 'bg-sky-50 text-sky-700 border-sky-200',
      Icon: ChevronRight,
    }
  }
  return {
    label: 'Evidence',
    tone: 'bg-slate-100 text-slate-700 border-slate-200',
    Icon: ShieldCheck,
  }
}

const OVERVIEW_SOURCE_ORDER = ['live', 'build', 'change', 'evidence']

function recommendationPriority(item) {
  if ((item.potential_points || 0) >= 14 || (item.unhealthy_resources || 0) >= 3) return 'critical'
  if ((item.potential_points || 0) >= 10 || (item.unhealthy_resources || 0) >= 2) return 'high'
  if ((item.potential_points || 0) >= 6 || (item.unhealthy_resources || 0) >= 1) return 'medium'
  return 'low'
}

function recommendationRail(priority) {
  if (priority === 'critical') return 'bg-red-500'
  if (priority === 'high') return 'bg-rose-500'
  if (priority === 'medium') return 'bg-amber-500'
  return 'bg-slate-400'
}

function tacticalRecommendationSeverity(item) {
  if (item?.severity) return item.severity
  if ((item?.score_impact || 0) >= 12 || (item?.asset_count || 0) >= 3) return 'high'
  if ((item?.score_impact || 0) >= 8 || (item?.asset_count || 0) >= 1) return 'medium'
  return 'low'
}

function numericSeverity(value) {
  if (value === 'critical') return 4
  if (value === 'high') return 3
  if (value === 'medium') return 2
  return 1
}

function textIncludes(value, terms) {
  const haystack = String(value || '').toLowerCase()
  return terms.some((term) => haystack.includes(term))
}

function isBuildCollector(collector) {
  return textIncludes(`${collector?.name || ''} ${collector?.connector_type || ''}`, ['build', 'factory', 'supply'])
}

function isBuildFinding(item) {
  return textIncludes(
    `${item?.title || ''} ${item?.category || ''} ${item?.metadata?.summary || ''} ${item?.metadata?.asset_name || ''}`,
    ['build', 'dependency', 'package', 'image', 'sbom', 'scan', 'supply'],
  )
}

function isBuildRecommendation(item) {
  return textIncludes(
    `${item?.title || ''} ${item?.domain || ''} ${item?.summary || ''}`,
    ['build', 'dependency', 'package', 'image', 'sbom', 'scan', 'supply', 'docker'],
  )
}

function isAppApiFinding(item) {
  return String(item?.source || '').startsWith('app_api:')
}

function recommendationFindingIds(item) {
  return (item?.metadata?.findings || []).map((finding) => String(finding?.id || ''))
}

function isAppApiRecommendation(item) {
  if (String(item?.id || '').startsWith('internal:')) return true
  return recommendationFindingIds(item).some((id) => id.startsWith('app_api:'))
}

function appApiScopeForFinding(item) {
  const source = String(item?.source || '')
  if (source === 'app_api:identity') return 'identity'
  if (source === 'app_api:configuration') return 'configuration'
  if (source === 'app_api:jobs') return 'jobs'
  if (source === 'app_api:data_protection') return 'data_protection'
  if (source === 'app_api:change_events') return 'change_events'
  if (source === 'app_api:detections') return 'detections'
  if (source === 'app_api:incidents') return 'incidents'
  return null
}

function appApiScopeForRecommendation(item) {
  const ids = recommendationFindingIds(item)
  if (ids.some((id) => id.startsWith('app_api:identity'))) return 'identity'
  if (ids.some((id) => id.startsWith('app_api:configuration'))) return 'configuration'
  if (ids.some((id) => id.startsWith('app_api:jobs'))) return 'jobs'
  if (ids.some((id) => id.startsWith('app_api:data_protection'))) return 'data_protection'
  if (ids.some((id) => id.startsWith('app_api:change_events'))) return 'change_events'
  if (ids.some((id) => id.startsWith('app_api:detections'))) return 'detections'
  if (ids.some((id) => id.startsWith('app_api:incidents'))) return 'incidents'
  return null
}

function telemetrySourceMeta(kind, scope = null) {
  if (kind === 'app') {
    const scopeLabel = scope ? titleCase(scope) : 'Application'
    return {
      label: 'App-native telemetry',
      summary: `${scopeLabel} findings are being produced directly by the system security API.`,
      facts: [
        { label: 'Telemetry lane', value: 'Internal app API' },
        { label: 'Scope', value: scopeLabel },
      ],
    }
  }
  if (kind === 'build') {
    return {
      label: 'Build telemetry',
      summary: 'This issue was derived from the recurring software-factory or supply-chain lane.',
      facts: [
        { label: 'Telemetry lane', value: 'Build snapshot' },
        { label: 'Scope', value: 'Software factory' },
      ],
    }
  }
  return {
    label: 'Collector telemetry',
    summary: 'This issue was derived from collector-fed runtime telemetry around the system environment.',
    facts: [
      { label: 'Telemetry lane', value: 'Collector ingest' },
      { label: 'Scope', value: 'Runtime environment' },
    ],
  }
}

function sourceInstanceLabel(source = '') {
  const value = String(source || '')
  if (value.startsWith('collector:')) {
    return `collector ${value.split(':')[1] || '?'}`
  }
  if (value.startsWith('build:')) {
    return `build source ${value.split(':')[1] || '?'}`
  }
  if (value.startsWith('app_api:')) {
    return titleCase(value.split(':')[1] || 'app')
  }
  return value || 'unknown source'
}

function tacticalSourceKind(item, kind = 'finding') {
  if (kind === 'recommendation') {
    if (isAppApiRecommendation(item)) return 'app'
    if (isBuildRecommendation(item)) return 'build'
    return 'live'
  }
  if (isAppApiFinding(item)) return 'app'
  if (isBuildFinding(item)) return 'build'
  return 'live'
}

function recommendationSource(item) {
  const title = String(item?.title || '').toLowerCase()
  const group = String(item?.group || '').toLowerCase()
  if (title.includes('dependency') || title.includes('build') || title.includes('scan') || group.includes('configuration') || group.includes('secrets')) return 'build'
  if ((item?.unhealthy_resources || 0) > 0 || title.includes('container') || title.includes('host') || title.includes('mfa') || title.includes('audit')) return 'live'
  return 'evidence'
}

function scoreBar(value, tone) {
  return (
    <div className="h-2 rounded-full bg-slate-200 overflow-hidden">
      <div className={`h-full ${tone}`} style={{ width: `${Math.max(0, Math.min(100, value || 0))}%` }} />
    </div>
  )
}

function resourceBar(item) {
  const total = Math.max(item.total_resources || 0, 1)
  const unhealthy = ((item.unhealthy_resources || 0) / total) * 100
  const healthy = ((item.healthy_resources || 0) / total) * 100
  const na = ((item.not_applicable_resources || 0) / total) * 100
  return (
    <div className="h-2 rounded-full bg-slate-200 overflow-hidden flex">
      <div className="bg-rose-500" style={{ width: `${unhealthy}%` }} />
      <div className="bg-lime-500" style={{ width: `${healthy}%` }} />
      <div className="bg-slate-300" style={{ width: `${na}%` }} />
    </div>
  )
}

function donutStyle(resourceHealth) {
  const total = Math.max(resourceHealth.total || 0, 1)
  const unhealthyEnd = ((resourceHealth.unhealthy || 0) / total) * 100
  const healthyEnd = (((resourceHealth.unhealthy || 0) + (resourceHealth.healthy || 0)) / total) * 100
  return {
    background: `conic-gradient(#ef4444 0 ${unhealthyEnd}%, #84cc16 ${unhealthyEnd}% ${healthyEnd}%, #cbd5e1 ${healthyEnd}% 100%)`,
  }
}

function titleCase(value = '') {
  return String(value)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase())
}

function formatEvidenceValue(value) {
  if (value === null || value === undefined || value === '') return 'none'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (Array.isArray(value)) return value.join(', ') || 'none'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function getDetailContract(detail) {
  const metadata = detail?.metadata || {}
  const metadataContract = metadata.detail_contract || {}
  return {
    finding_type: detail?.finding_type || metadata.finding_type || metadataContract.finding_type || detail?.kind || 'security_finding',
    source_scope:
      detail?.source_scope ||
      metadata.source_scope ||
      metadataContract.source_scope ||
      (String(detail?.source || '').startsWith('build:') ? 'build' : 'live'),
    observed: detail?.observed || metadataContract.observed || [],
    expected: detail?.expected || metadataContract.expected || [],
    evidence: detail?.evidence || metadataContract.evidence || [],
    fix_steps: detail?.fix_steps || metadataContract.fix_steps || [],
    verification_checks: detail?.verification_checks || metadataContract.verification_checks || [],
    history: detail?.history || metadataContract.history || [],
    generated_guidance:
      detail?.generated_guidance ||
      metadata.generated_guidance ||
      metadataContract.generated_guidance ||
      {},
  }
}

function buildEvidenceSections(detail) {
  const metadata = detail?.metadata || {}
  const contract = getDetailContract(detail)
  const guidance = contract.generated_guidance || {}
  const sections = []

  if (detail?.provenance?.length) {
    sections.push({
      key: 'provenance',
      title: 'Telemetry Provenance',
      type: 'facts',
      items: detail.provenance,
    })
  }

  if (guidance.operator_summary_text) {
    sections.push({
      key: 'guidance-summary',
      title: 'Generated Summary',
      type: 'text',
      value: String(guidance.operator_summary_text),
    })
  }

  if (guidance.why_it_matters_text) {
    sections.push({
      key: 'guidance-why',
      title: 'Why It Matters',
      type: 'text',
      value: String(guidance.why_it_matters_text),
    })
  }

  if (contract.observed?.length) {
    sections.push({
      key: 'observed',
      title: 'Observed',
      type: 'facts',
      items: contract.observed,
    })
  }

  if (contract.expected?.length) {
    sections.push({
      key: 'expected',
      title: 'Expected',
      type: 'facts',
      items: contract.expected,
    })
  }

  if (guidance.fix_steps_text) {
    sections.push({
      key: 'guidance-fix',
      title: 'Fix Guidance',
      type: 'text',
      value: String(guidance.fix_steps_text),
    })
  }

  if (contract.fix_steps?.length) {
    sections.push({
      key: 'fix-steps',
      title: 'Fix Steps',
      type: 'steps',
      items: contract.fix_steps.map((item) => ({ title: item })),
    })
  }

  if (guidance.verification_text) {
    sections.push({
      key: 'guidance-verify',
      title: 'Verification Guidance',
      type: 'text',
      value: String(guidance.verification_text),
    })
  }

  if (contract.verification_checks?.length) {
    sections.push({
      key: 'verification',
      title: 'Verification Checks',
      type: 'steps',
      items: contract.verification_checks.map((item) => ({ title: item })),
    })
  }

  if (contract.evidence?.length) {
    sections.push({
      key: 'contract-evidence',
      title: 'Evidence',
      type: 'facts',
      items: contract.evidence,
    })
  }

  if (contract.history?.length) {
    sections.push({
      key: 'history',
      title: 'History',
      type: 'facts',
      items: contract.history,
    })
  }

  if (metadata.counts && typeof metadata.counts === 'object') {
    sections.push({
      key: 'counts',
      title: 'Scan Counts',
      type: 'facts',
      items: Object.entries(metadata.counts)
        .filter(([, value]) => Number(value) > 0)
        .map(([key, value]) => ({ label: titleCase(key), value: String(value) })),
    })
  }

  if (metadata.affected_assets?.length) {
    sections.push({
      key: 'assets',
      title: 'Affected Assets',
      type: 'list',
      items: metadata.affected_assets.map((item) => ({ title: item })),
    })
  }

  if (detail?.packages?.length) {
    sections.push({
      key: 'packages',
      title: 'Affected Packages',
      type: 'packages',
      items: detail.packages,
    })
  }

  if (detail?.vulnerabilities?.length) {
    sections.push({
      key: 'vulnerabilities',
      title: 'Vulnerability Detail',
      type: 'vulnerabilities',
      items: detail.vulnerabilities,
    })
  }

  if (metadata.findings?.length) {
    sections.push({
      key: 'findings',
      title: 'Underlying Findings',
      type: 'list',
      items: metadata.findings.map((item) => ({
        title: item.title,
        subtitle: [item.asset_name, item.category, item.summary].filter(Boolean).join(' | '),
      })),
    })
  }

  if (metadata.records?.length) {
    sections.push({
      key: 'records',
      title: 'Underlying Records',
      type: 'list',
      items: metadata.records,
    })
  }

  if (metadata.ports?.length) {
    sections.push({
      key: 'ports',
      title: 'Published Ports',
      type: 'list',
      items: metadata.ports.map((item) => ({ title: item })),
    })
  }

  if (metadata.storage_locations?.length) {
    sections.push({
      key: 'storage-locations',
      title: 'Storage Locations',
      type: 'list',
      items: metadata.storage_locations,
    })
  }

  if (metadata.failed_documents?.length) {
    sections.push({
      key: 'failed-documents',
      title: 'Failed Documents',
      type: 'list',
      items: metadata.failed_documents,
    })
  }

  if (metadata.change_events?.length) {
    sections.push({
      key: 'change-events',
      title: 'Recent Change Events',
      type: 'list',
      items: metadata.change_events,
    })
  }

  if (metadata.detections?.length) {
    sections.push({
      key: 'detections',
      title: 'Detection Detail',
      type: 'list',
      items: metadata.detections,
    })
  }

  if (metadata.incidents?.length) {
    sections.push({
      key: 'incidents',
      title: 'Incident Detail',
      type: 'list',
      items: metadata.incidents,
    })
  }

  if (metadata.event_types?.length) {
    sections.push({
      key: 'event-types',
      title: 'Event Types',
      type: 'list',
      items: metadata.event_types.map((item) => ({ title: item })),
    })
  }

  if (metadata.severity_counts && typeof metadata.severity_counts === 'object') {
    sections.push({
      key: 'severity-breakdown',
      title: 'Severity Breakdown',
      type: 'facts',
      items: Object.entries(metadata.severity_counts)
        .filter(([, value]) => Number(value) > 0)
        .map(([key, value]) => ({ label: titleCase(key), value: String(value) })),
    })
  }

  if (metadata.detail) {
    sections.push({
      key: 'detail',
      title: 'Scanner Detail',
      type: 'text',
      value: String(metadata.detail),
    })
  }

  const excludedKeys = new Set([
    'recommendation_key',
    'recommendation_title',
    'domain',
    'score_impact',
    'action',
    'summary',
    'asset_name',
    'counts',
    'affected_assets',
    'packages',
    'vulnerabilities',
    'findings',
    'records',
    'ports',
    'storage_locations',
    'failed_documents',
    'change_events',
    'detections',
    'incidents',
    'event_types',
    'severity_counts',
    'detail',
    'detail_contract',
    'generated_guidance',
  ])

  const scalarFacts = Object.entries(metadata)
    .filter(([key, value]) => !excludedKeys.has(key) && !Array.isArray(value) && typeof value !== 'object')
    .map(([key, value]) => ({ label: titleCase(key), value: formatEvidenceValue(value) }))

  if (scalarFacts.length) {
    sections.push({
      key: 'facts',
      title: 'Key Facts',
      type: 'facts',
      items: scalarFacts,
    })
  }

  return sections.filter((section) => {
    if (section.type === 'text') return Boolean(section.value)
    return Boolean(section.items?.length)
  })
}

function partitionEvidenceSections(sections = []) {
  const groups = {
    summary: [],
    fix: [],
    verify: [],
    evidence: [],
    history: [],
  }

  for (const section of sections) {
    if (['guidance-summary', 'guidance-why', 'observed', 'expected', 'counts', 'severity-breakdown'].includes(section.key)) {
      groups.summary.push(section)
      continue
    }
    if (['guidance-fix', 'fix-steps'].includes(section.key)) {
      groups.fix.push(section)
      continue
    }
    if (['guidance-verify', 'verification'].includes(section.key)) {
      groups.verify.push(section)
      continue
    }
    if (section.key === 'history') {
      groups.history.push(section)
      continue
    }
    groups.evidence.push(section)
  }

  return groups
}

function FilterChip({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium transition-colors ${active ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 bg-white text-slate-600 hover:border-slate-400'}`}
    >
      {children}
    </button>
  )
}

function DetailSection({ section }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{section.title}</p>
        {section.items ? <span className="text-[10px] text-slate-500">{section.items.length} item(s)</span> : null}
      </div>
      {section.type === 'text' ? (
        <p className="mt-2 text-sm leading-6 text-slate-700">{section.value}</p>
      ) : null}
      {section.type === 'facts' ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {section.items.map((item) => (
            <span key={`${section.key}-${item.label}`} className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-700">
              {item.label}: {item.value}
            </span>
          ))}
        </div>
      ) : null}
      {section.type === 'list' || section.type === 'steps' ? (
        <div className="mt-2 space-y-2">
          {section.items.slice(0, 10).map((item, index) => (
            <div key={`${section.key}-${item.title || index}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-sm font-semibold text-slate-900">{section.type === 'steps' ? `${index + 1}. ${item.title}` : item.title}</p>
              {item.subtitle ? <p className="mt-0.5 text-[11px] text-slate-600">{item.subtitle}</p> : null}
            </div>
          ))}
        </div>
      ) : null}
      {section.type === 'packages' ? (
        <div className="mt-2 space-y-2">
          {section.items.slice(0, 8).map((pkg) => (
            <div key={`${pkg.name}-${pkg.version || pkg.installed_version || ''}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-slate-900">{pkg.name}</p>
                <span className="text-[11px] text-slate-500">{pkg.version || pkg.installed_version || 'unknown version'}</span>
              </div>
              <p className="mt-0.5 text-[11px] text-slate-600">{pkg.vulnerability_count || (pkg.vulnerabilities || []).length} vulnerable issue(s)</p>
            </div>
          ))}
        </div>
      ) : null}
      {section.type === 'vulnerabilities' ? (
        <div className="mt-2 space-y-2">
          {section.items.slice(0, 10).map((vuln, index) => (
            <div key={`${vuln.id || vuln.title || 'vuln'}-${vuln.package || index}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-slate-900">{vuln.id || vuln.title || 'Vulnerability'}</p>
                <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${severityTone((vuln.severity || 'medium').toLowerCase())}`}>
                  {(vuln.severity || 'medium').toLowerCase()}
                </span>
              </div>
              <p className="mt-0.5 text-[11px] text-slate-600">
                {vuln.package || 'package'}{vuln.installed_version ? ` @ ${vuln.installed_version}` : ''}
              </p>
              {vuln.fix_versions?.length ? (
                <p className="mt-1 text-[11px] text-emerald-700">Fix versions: {vuln.fix_versions.join(', ')}</p>
              ) : vuln.fix_version ? (
                <p className="mt-1 text-[11px] text-emerald-700">Fix: {vuln.fix_version}</p>
              ) : null}
              {vuln.aliases?.length ? <p className="mt-1 text-[11px] text-slate-500">Aliases: {vuln.aliases.join(', ')}</p> : null}
              {vuln.description ? <p className="mt-1 text-[11px] leading-5 text-slate-600">{vuln.description}</p> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function TabChip({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${active ? 'border-slate-900 bg-slate-900 text-white shadow-sm' : 'border-slate-300 bg-white text-slate-600 hover:border-slate-400 hover:bg-slate-50'}`}
    >
      {children}
    </button>
  )
}

export default function CatoDashboardPage() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('overview')
  const [search, setSearch] = useState('')
  const [domainFilter, setDomainFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [healthFilter, setHealthFilter] = useState('all')
  const [selectedId, setSelectedId] = useState(null)
  const [selectedTactical, setSelectedTactical] = useState(null)
  const [liveFocus, setLiveFocus] = useState('all')
  const [selectedLens, setSelectedLens] = useState('needs_attention')
  const [selectedOverviewItemKey, setSelectedOverviewItemKey] = useState(null)
  const [overviewInspectorOpen, setOverviewInspectorOpen] = useState(false)
  const [overviewInspectorTab, setOverviewInspectorTab] = useState('summary')
  const [overviewGroupBy, setOverviewGroupBy] = useState('source')
  const [selectedOverview, setSelectedOverview] = useState('secure_score')
  const [inspectorTab, setInspectorTab] = useState('summary')
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [includeSource, setIncludeSource] = useState('both')
  const [actionStatusFilter, setActionStatusFilter] = useState('all')
  const [tableSort, setTableSort] = useState({ key: 'score', direction: 'desc' })
  const [showOps, setShowOps] = useState(false)
  const [selectedAssuranceStatus, setSelectedAssuranceStatus] = useState('all')
  const [selectedControlId, setSelectedControlId] = useState('all')
  const [selectedVerificationKey, setSelectedVerificationKey] = useState(null)

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get(`/projects/${projectId}`).then((r) => r.data),
    enabled: Boolean(projectId),
    refetchOnMount: 'always',
    refetchOnReconnect: 'always',
    refetchOnWindowFocus: true,
    staleTime: 0,
  })

  const { data: posture } = useQuery({
    queryKey: ['ato-bot-security', projectId],
    queryFn: () => api.get(`/projects/${projectId}/integrations/ato-bot-security`).then((r) => r.data),
    enabled: Boolean(projectId),
    refetchOnMount: 'always',
    refetchOnReconnect: 'always',
    refetchOnWindowFocus: true,
    staleTime: 0,
  })
  const { data: securityOverview, error: securityOverviewError, isLoading: securityOverviewLoading } = useQuery({
    queryKey: ['security-overview', projectId],
    queryFn: () => api.get(`/projects/${projectId}/security/overview`).then((r) => r.data),
    enabled: Boolean(projectId),
    refetchOnMount: 'always',
    refetchOnReconnect: 'always',
    refetchOnWindowFocus: true,
    staleTime: 0,
  })
  const { data: liveState, error: liveStateError, isLoading: liveStateLoading } = useQuery({
    queryKey: ['security-live-state', projectId],
    queryFn: () => api.get(`/projects/${projectId}/security/live-state`).then((r) => r.data),
    enabled: Boolean(projectId),
    refetchOnMount: 'always',
    refetchOnReconnect: 'always',
    refetchOnWindowFocus: true,
    staleTime: 0,
  })
  const { data: verificationData } = useQuery({
    queryKey: ['security-verifications', projectId],
    queryFn: () => api.get(`/projects/${projectId}/security/verifications`).then((r) => r.data),
    enabled: Boolean(projectId),
    refetchOnMount: 'always',
    refetchOnReconnect: 'always',
    refetchOnWindowFocus: true,
    staleTime: 0,
  })
  const { data: controlSupportData } = useQuery({
    queryKey: ['security-control-support', projectId],
    queryFn: () => api.get(`/projects/${projectId}/security/control-support`).then((r) => r.data),
    enabled: Boolean(projectId),
    refetchOnMount: 'always',
    refetchOnReconnect: 'always',
    refetchOnWindowFocus: true,
    staleTime: 0,
  })

  const secureScore = posture?.secure_score || { percentage: 0, earned_points: 0, total_points: 0 }
  const recommendationStatus = posture?.recommendation_status || { completed_controls: 0, total_controls: 0, completed_recommendations: 0, total_recommendations: 0 }
  const resourceHealth = posture?.resource_health || { healthy: 0, unhealthy: 0, not_applicable: 0, total: 0 }
  const assertions = posture?.security_assertions || []
  const attestations = posture?.implementation_attestations || []
  const supporting = posture?.supporting_context || {}
  const metrics = posture?.metrics || {}
  const containerSecurity = supporting.container_security || { healthy: 0, total: 0, services: [], default_secret_fallbacks: [], attestations: [] }
  const tacticalSummary = securityOverview?.summary || { collector_count: 0, asset_count: 0, open_findings: 0, critical_findings: 0, high_findings: 0 }
  const tacticalCollectors = securityOverview?.collectors || []
  const tacticalFindings = securityOverview?.findings || []
  const tacticalRecommendations = securityOverview?.recommendations || []
  const identityDomain = securityOverview?.identity_domain || { summary: {}, findings: [], recommendations: [] }
  const configurationDomain = securityOverview?.configuration_domain || { summary: {}, findings: [], recommendations: [] }
  const jobsDomain = securityOverview?.jobs_domain || { summary: {}, findings: [], recommendations: [] }
  const dataProtectionDomain = securityOverview?.data_protection_domain || { summary: {}, findings: [], recommendations: [] }
  const changeEventsDomain = securityOverview?.change_events_domain || { summary: {}, findings: [], recommendations: [] }
  const detectionsDomain = securityOverview?.detections_domain || { summary: {}, findings: [], recommendations: [] }
  const incidentsDomain = securityOverview?.incidents_domain || { summary: {}, findings: [], recommendations: [] }
  const latestBuildSnapshot = securityOverview?.latest_build_snapshot || null
  const latestRuntimeSnapshot = securityOverview?.latest_runtime_snapshot || null
  const recentChanges = securityOverview?.recent_changes || []
  const liveAssets = liveState?.assets || []
  const liveSignals = liveState?.signals || []
  const liveFindings = liveState?.findings || []
  const liveRecommendations = liveState?.recommendations || []
  const liveDetections = liveState?.detections || []
  const liveChangeEvents = liveState?.change_events || []
  const liveRiskState = liveState?.risk_state || {}
  const verificationResults = verificationData?.results || []
  const controlSupport = controlSupportData?.controls || []
  const liveSummary = useMemo(() => ({
    collector_count: tacticalCollectors.length || 0,
    asset_count: liveAssets.length || 0,
    open_findings: liveFindings.filter((item) => item.status === 'open').length,
    critical_findings: liveRiskState.critical_findings || 0,
    high_findings: liveRiskState.high_findings || 0,
  }), [tacticalCollectors.length, liveAssets.length, liveFindings, liveRiskState])

  const recommendations = useMemo(
    () => (posture?.recommendations || []).map((item) => ({ ...item, domain: getDomain(item.group) })),
    [posture?.recommendations],
  )

  const domainSummary = useMemo(() => {
    const map = new Map()
    for (const item of recommendations) {
      const current = map.get(item.domain) || { domain: item.domain, points: 0, earned: 0, count: 0 }
      current.points += item.points || 0
      current.earned += item.earned_points || 0
      current.count += 1
      map.set(item.domain, current)
    }
    return [...map.values()].map((item) => ({
      ...item,
      percentage: item.points ? Math.round((item.earned / item.points) * 100) : 0,
    }))
  }, [recommendations])

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return recommendations.filter((item) => {
      if (domainFilter !== 'all' && item.domain !== domainFilter) return false
      if (statusFilter !== 'all' && item.status !== statusFilter) return false
      if (healthFilter === 'healthy' && !(item.unhealthy_resources === 0 && item.healthy_resources > 0)) return false
      if (healthFilter === 'unhealthy' && !(item.unhealthy_resources > 0)) return false
      if (healthFilter === 'not_applicable' && !(item.not_applicable_resources > 0)) return false
      if (!needle) return true
      return (
        item.title.toLowerCase().includes(needle)
        || item.group.toLowerCase().includes(needle)
        || item.domain.toLowerCase().includes(needle)
        || item.controls.join(' ').toLowerCase().includes(needle)
        || item.action.toLowerCase().includes(needle)
      )
    })
  }, [recommendations, search, domainFilter, statusFilter, healthFilter])

  const sortedFiltered = useMemo(() => {
    const items = [...filtered]
    const dir = tableSort.direction === 'asc' ? 1 : -1
    items.sort((a, b) => {
      if (tableSort.key === 'score') return ((a.potential_points || 0) - (b.potential_points || 0)) * dir
      if (tableSort.key === 'unhealthy') return ((a.unhealthy_resources || 0) - (b.unhealthy_resources || 0)) * dir
      if (tableSort.key === 'title') return a.title.localeCompare(b.title) * dir
      return 0
    })
    return items
  }, [filtered, tableSort])

  const maxPotentialPoints = useMemo(
    () => Math.max(...sortedFiltered.map((item) => item.potential_points || 0), 1),
    [sortedFiltered],
  )

  useEffect(() => {
    if (!sortedFiltered.length) {
      setSelectedId(null)
      return
    }
    if (!sortedFiltered.some((item) => item.id === selectedId)) {
      setSelectedId(sortedFiltered[0].id)
    }
  }, [sortedFiltered, selectedId])

  const selected = sortedFiltered.find((item) => item.id === selectedId) || null
  const topActions = recommendations.filter((item) => item.potential_points > 0).slice(0, 3)
  const trustLevel = secureScore.percentage >= 80 && (metrics.unresolved_critical_events || 0) === 0 ? 'high' : secureScore.percentage >= 55 ? 'medium' : 'low'
  const openTacticalFindings = useMemo(
    () => liveFindings.filter((item) => item.status === 'open'),
    [liveFindings],
  )
  const selectedLiveCollector = useMemo(
    () => (liveFocus.startsWith('collector:') ? tacticalCollectors.find((item) => item.id === Number(liveFocus.split(':')[1])) || null : null),
    [liveFocus, tacticalCollectors],
  )
  const appApiSummary = useMemo(() => ({
    totalFindings: liveFindings.filter((item) => isAppApiFinding(item) && item.status === 'open').length,
    totalRecommendations: liveRecommendations.filter((item) => isAppApiRecommendation(item)).length,
    identity: identityDomain.findings?.length || 0,
    configuration: configurationDomain.findings?.length || 0,
    jobs: jobsDomain.findings?.length || 0,
    dataProtection: dataProtectionDomain.findings?.length || 0,
    changeEvents: changeEventsDomain.findings?.length || 0,
    detections: Math.max(detectionsDomain.findings?.length || 0, liveDetections.filter((item) => !item.resolved).length || 0),
  }), [liveFindings, liveRecommendations, identityDomain, configurationDomain, jobsDomain, dataProtectionDomain, changeEventsDomain, detectionsDomain, liveDetections])
  const appTelemetryCards = useMemo(() => ([
      {
        key: 'app:identity',
        label: 'Identity',
        count: identityDomain.findings?.length || 0,
        countLabel: `finding${(identityDomain.findings?.length || 0) === 1 ? '' : 's'}`,
        tone: 'border-sky-200 bg-sky-50 text-sky-700',
        facts: [
          `${identityDomain.summary?.active_refresh_sessions || 0} active sessions`,
          `${identityDomain.summary?.expired_unrevoked_refresh_tokens || 0} expired tokens`,
          `${identityDomain.summary?.stale_refresh_sessions || 0} stale sessions`,
        ],
      },
    {
      key: 'app:configuration',
      label: 'Configuration',
      count: configurationDomain.findings?.length || 0,
      countLabel: `finding${(configurationDomain.findings?.length || 0) === 1 ? '' : 's'}`,
      tone: 'border-violet-200 bg-violet-50 text-violet-700',
      facts: [
        configurationDomain.summary?.wildcard_cors ? 'Wildcard CORS' : 'No wildcard CORS',
        configurationDomain.summary?.csp_unsafe_inline ? 'Unsafe-inline CSP' : 'CSP tightened',
        configurationDomain.summary?.weak_secret ? 'Weak secret posture' : 'Secret posture healthy',
      ],
    },
    {
      key: 'app:jobs',
      label: 'Jobs',
      count: jobsDomain.findings?.length || 0,
      countLabel: `finding${(jobsDomain.findings?.length || 0) === 1 ? '' : 's'}`,
      tone: 'border-emerald-200 bg-emerald-50 text-emerald-700',
      facts: [
        `${jobsDomain.summary?.failed_ingestions_24h || 0} failed ingest (24h)`,
        `${jobsDomain.summary?.stuck_ingestions || 0} stuck jobs`,
        `${jobsDomain.summary?.unresolved_high_security_events || 0} high events`,
      ],
    },
    {
      key: 'app:data_protection',
      label: 'Data Protection',
      count: dataProtectionDomain.findings?.length || 0,
      countLabel: `finding${(dataProtectionDomain.findings?.length || 0) === 1 ? '' : 's'}`,
      tone: 'border-cyan-200 bg-cyan-50 text-cyan-700',
      facts: [
        dataProtectionDomain.summary?.database_secret_fallback ? 'DB fallback secret' : 'DB secret ok',
        dataProtectionDomain.summary?.redis_secret_fallback ? 'Redis fallback secret' : 'Redis secret ok',
        dataProtectionDomain.summary?.retention_policy_exposed ? 'Retention exposed' : 'Retention gap',
      ],
    },
    {
      key: 'app:change_events',
      label: 'Change Events',
      count: changeEventsDomain.findings?.length || 0,
      countLabel: `finding${(changeEventsDomain.findings?.length || 0) === 1 ? '' : 's'}`,
      tone: 'border-sky-200 bg-sky-50 text-sky-700',
      facts: [
        `${changeEventsDomain.summary?.recent_changes_7d || 0} signals (7d)`,
        `${changeEventsDomain.summary?.regressions_7d || 0} regressions`,
        `${changeEventsDomain.summary?.unexpected_changes_7d || 0} unexpected`,
      ],
    },
    {
      key: 'app:detections',
      label: 'Detections',
      count: Math.max(detectionsDomain.findings?.length || 0, liveDetections.filter((item) => !item.resolved).length || 0),
      countLabel: 'signals or findings',
      tone: 'border-rose-200 bg-rose-50 text-rose-700',
      facts: [
        `${liveDetections.filter((item) => !item.resolved).length || 0} open signals`,
        `${detectionsDomain.summary?.open_high_detections_7d || 0} high`,
        `${detectionsDomain.summary?.suspicious_detections_7d || 0} suspicious`,
      ],
    },
  ]), [identityDomain, configurationDomain, jobsDomain, dataProtectionDomain, changeEventsDomain, detectionsDomain, liveDetections])
  const liveFocusMeta = useMemo(() => {
    if (liveFocus === 'app:all') {
      return {
        title: 'App API telemetry',
        summary: `${appApiSummary.totalFindings} app-native finding(s) and ${appApiSummary.totalRecommendations} recommendation(s) are coming directly from ATO Bot itself.`,
      }
    }
      if (liveFocus === 'app:identity') {
        return {
          title: 'App identity telemetry',
          summary: `${identityDomain.findings?.length || 0} finding(s) derived from users, MFA posture, failed auth activity, lockouts, and refresh-session hygiene.`,
        }
      }
    if (liveFocus === 'app:configuration') {
      return {
        title: 'App configuration telemetry',
        summary: `${configurationDomain.findings?.length || 0} finding(s) derived from CORS, CSP, secret posture, and auth configuration.`,
      }
    }
    if (liveFocus === 'app:jobs') {
      return {
        title: 'App jobs telemetry',
        summary: `${jobsDomain.findings?.length || 0} finding(s) derived from ingestion, assessment, parser, and security event health.`,
      }
    }
    if (liveFocus === 'app:data_protection') {
      return {
        title: 'App data protection telemetry',
        summary: `${dataProtectionDomain.findings?.length || 0} finding(s) derived from evidence storage, credential fallback posture, and retention visibility.`,
      }
    }
    if (liveFocus === 'app:change_events') {
      return {
        title: 'App change telemetry',
        summary: `${changeEventsDomain.summary?.recent_changes_7d || 0} raw change signal(s) produced ${changeEventsDomain.findings?.length || 0} promoted finding(s) and ${liveRecommendations.filter((item) => appApiScopeForRecommendation(item) === 'change_events').length} recommendation(s).`,
      }
    }
    if (liveFocus === 'app:detections') {
      return {
        title: 'App detection telemetry',
        summary: `${liveDetections.filter((item) => !item.resolved).length || 0} open detection signal(s) produced ${detectionsDomain.findings?.length || 0} promoted finding(s) and ${liveRecommendations.filter((item) => appApiScopeForRecommendation(item) === 'detections').length} recommendation(s).`,
      }
    }
    if (liveFocus === 'collector_count') {
      return {
        title: 'Collector coverage',
        summary: `${liveSummary.collector_count || 0} collector(s) are feeding live tactical telemetry right now.`,
      }
    }
    if (liveFocus === 'asset_count') {
      return {
        title: 'Tracked assets',
        summary: `${liveSummary.asset_count || 0} asset(s) are represented in the current live tactical model.`,
      }
    }
    if (liveFocus === 'open_findings') {
      return {
        title: 'Open findings',
        summary: `${liveSummary.open_findings || 0} open finding(s) are currently driving live risk.`,
      }
    }
    if (liveFocus === 'critical_findings') {
      return {
        title: 'Critical findings',
        summary: `${liveSummary.critical_findings || 0} critical finding(s) are currently open.`,
      }
    }
    if (liveFocus === 'high_findings') {
      return {
        title: 'High findings',
        summary: `${liveSummary.high_findings || 0} high-severity finding(s) are currently open.`,
      }
    }
    if (selectedLiveCollector) {
      return {
        title: selectedLiveCollector.name,
        summary: selectedLiveCollector.last_sync_summary || 'Collector-scoped live telemetry focus.',
      }
    }
    return {
      title: 'All live data',
      summary: 'Runtime findings and recommendations across app-native telemetry, collectors, containers, and host posture.',
    }
  }, [liveFocus, selectedLiveCollector, liveSummary, appApiSummary, identityDomain, configurationDomain, jobsDomain, dataProtectionDomain, changeEventsDomain, detectionsDomain, liveRecommendations, liveDetections])
  const liveFocusedFindings = useMemo(() => {
    if (liveFocus === 'app:all') {
      return openTacticalFindings.filter((item) => isAppApiFinding(item))
    }
    if (liveFocus === 'app:identity') {
      return openTacticalFindings.filter((item) => appApiScopeForFinding(item) === 'identity')
    }
    if (liveFocus === 'app:configuration') {
      return openTacticalFindings.filter((item) => appApiScopeForFinding(item) === 'configuration')
    }
    if (liveFocus === 'app:jobs') {
      return openTacticalFindings.filter((item) => appApiScopeForFinding(item) === 'jobs')
    }
    if (liveFocus === 'app:data_protection') {
      return openTacticalFindings.filter((item) => appApiScopeForFinding(item) === 'data_protection')
    }
    if (liveFocus === 'app:change_events') {
      return openTacticalFindings.filter((item) => appApiScopeForFinding(item) === 'change_events')
    }
    if (liveFocus === 'app:detections') {
      return openTacticalFindings.filter((item) => appApiScopeForFinding(item) === 'detections')
    }
    if (liveFocus === 'critical_findings') {
      return openTacticalFindings.filter((item) => item.severity === 'critical')
    }
    if (liveFocus === 'high_findings') {
      return openTacticalFindings.filter((item) => item.severity === 'high')
    }
    if (liveFocus === 'asset_count') {
      return openTacticalFindings.filter((item) => item.metadata?.asset_name)
    }
    if (liveFocus === 'collector_count') {
      return openTacticalFindings.filter((item) => textIncludes(`${item.category || ''} ${item.title || ''}`, ['scan', 'coverage', 'collector', 'telemetry']))
    }
    if (selectedLiveCollector) {
      return openTacticalFindings.filter((item) => (isBuildCollector(selectedLiveCollector) ? isBuildFinding(item) : !isBuildFinding(item)))
    }
    return openTacticalFindings
  }, [liveFocus, openTacticalFindings, selectedLiveCollector])
  const liveFocusedRecommendations = useMemo(() => {
    if (liveFocus === 'app:all') {
      return liveRecommendations.filter((item) => isAppApiRecommendation(item))
    }
    if (liveFocus === 'app:identity') {
      return liveRecommendations.filter((item) => appApiScopeForRecommendation(item) === 'identity')
    }
    if (liveFocus === 'app:configuration') {
      return liveRecommendations.filter((item) => appApiScopeForRecommendation(item) === 'configuration')
    }
    if (liveFocus === 'app:jobs') {
      return liveRecommendations.filter((item) => appApiScopeForRecommendation(item) === 'jobs')
    }
    if (liveFocus === 'app:data_protection') {
      return liveRecommendations.filter((item) => appApiScopeForRecommendation(item) === 'data_protection')
    }
    if (liveFocus === 'app:change_events') {
      return liveRecommendations.filter((item) => appApiScopeForRecommendation(item) === 'change_events')
    }
    if (liveFocus === 'app:detections') {
      return liveRecommendations.filter((item) => appApiScopeForRecommendation(item) === 'detections')
    }
    if (liveFocus === 'critical_findings') {
      return liveRecommendations.filter((item) => tacticalRecommendationSeverity(item) === 'critical')
    }
    if (liveFocus === 'high_findings') {
      return liveRecommendations.filter((item) => ['critical', 'high'].includes(tacticalRecommendationSeverity(item)))
    }
    if (liveFocus === 'asset_count') {
      return liveRecommendations.filter((item) => (item.asset_count || 0) > 0)
    }
    if (liveFocus === 'collector_count') {
      return liveRecommendations.filter((item) => textIncludes(`${item.title || ''} ${item.summary || ''}`, ['scan', 'coverage', 'collector', 'telemetry']))
    }
    if (liveFocus === 'open_findings') {
      return liveRecommendations.filter((item) => ['critical', 'high', 'medium'].includes(tacticalRecommendationSeverity(item)))
    }
    if (selectedLiveCollector) {
      return liveRecommendations.filter((item) => (isBuildCollector(selectedLiveCollector) ? isBuildRecommendation(item) : !isBuildRecommendation(item)))
    }
    return liveRecommendations
  }, [liveFocus, liveRecommendations, selectedLiveCollector])

  const liveFocusedRecords = useMemo(() => {
    const detectionRows = (liveDetections || [])
      .filter((item) => !item.resolved)
      .map((item) => ({
        key: `record-detection-${item.id}`,
        kind: 'record',
        id: `detection-${item.id}`,
        title: `Detection: ${titleCase(item.event_type || 'security event')}`,
        scope: 'App detection event',
        source: 'app',
        severity: item.severity || 'medium',
        status: item.resolved ? 'resolved' : 'open',
        nextStep: 'Review the detection, determine whether it represents malicious or expected activity, and either resolve it or escalate it.',
        score: numericSeverity(item.severity || 'medium'),
        metadata: {
          detail_contract: {
            observed: [
              { label: 'Event type', value: titleCase(item.event_type || 'security event') },
              { label: 'Severity', value: item.severity || 'medium' },
              { label: 'Status', value: item.resolved ? 'resolved' : 'open' },
              { label: 'Timestamp', value: item.timestamp || 'unknown' },
            ],
            expected: [{ label: 'Status', value: 'resolved or dispositioned' }],
            evidence: [{ label: 'Description', value: item.description || 'No description available' }],
            fix_steps: [
              'Review the triggering activity and determine whether it is malicious, expected, or false positive noise.',
              'Resolve the detection or escalate it into the incident workflow with documented disposition.',
            ],
            verification_checks: [
              'The detections API shows this event resolved or formally dispositioned.',
              'Any related control or alert tuning change is documented.',
            ],
            history: [{ label: 'Telemetry lane', value: 'App-native detections' }],
          },
          event_type: item.event_type,
          event_timestamp: item.timestamp,
          description: item.description,
        },
        chips: [
          { label: 'detection', tone: 'bg-rose-100 text-rose-700 border-rose-200' },
          { label: item.resolved ? 'resolved' : 'open', tone: item.resolved ? 'bg-emerald-100 text-emerald-700 border-emerald-200' : 'bg-rose-100 text-rose-700 border-rose-200' },
        ],
      }))

    if (liveFocus === 'app:detections') return detectionRows
    if (liveFocus === 'app:all') return detectionRows
    return []
  }, [liveFocus, liveDetections])
  const tacticalRecommendationRows = useMemo(
    () => liveFocusedRecommendations.slice(0, 6),
    [liveFocusedRecommendations],
  )
  const tacticalFindingRows = useMemo(
    () => liveFocusedFindings.slice(0, 6),
    [liveFocusedFindings],
  )

  useEffect(() => {
    if (selectedTactical) {
      if (selectedTactical.kind === 'recommendation' && tacticalRecommendationRows.some((item) => item.id === selectedTactical.id)) return
      if (selectedTactical.kind === 'finding' && tacticalFindingRows.some((item) => item.id === selectedTactical.id)) return
      if (selectedTactical.kind === 'record' && liveFocusedRecords.some((item) => item.id === selectedTactical.id)) return
      if (selectedTactical.kind === 'collector' && selectedLiveCollector?.id === selectedTactical.id) return
      if (selectedTactical.kind === 'summary' && selectedTactical.id === liveFocus) return
    }

    if (tacticalRecommendationRows.length) {
      setSelectedTactical({ kind: 'recommendation', id: tacticalRecommendationRows[0].id })
      return
    }
    if (tacticalFindingRows.length) {
      setSelectedTactical({ kind: 'finding', id: tacticalFindingRows[0].id })
      return
    }
    if (liveFocusedRecords.length) {
      setSelectedTactical({ kind: 'record', id: liveFocusedRecords[0].id })
      return
    }
    if (selectedLiveCollector) {
      setSelectedTactical({ kind: 'collector', id: selectedLiveCollector.id })
      return
    }
    setSelectedTactical({ kind: 'summary', id: liveFocus === 'all' ? 'open_findings' : liveFocus })
  }, [selectedTactical, tacticalRecommendationRows, tacticalFindingRows, liveFocusedRecords, selectedLiveCollector, liveFocus])

  const selectedTacticalDetail = useMemo(() => {
    if (!selectedTactical) return null
    if (selectedTactical.kind === 'recommendation') {
      const match = liveRecommendations.find((item) => item.id === selectedTactical.id)
      if (!match) return null
      const guidance = match.generated_guidance || match.metadata?.generated_guidance || match.metadata?.detail_contract?.generated_guidance || {}
      const sourceKind = tacticalSourceKind(match, 'recommendation')
      const sourceMeta = telemetrySourceMeta(sourceKind, appApiScopeForRecommendation(match))
      return {
        kind: 'recommendation',
        title: match.title,
        subtitle: match.domain,
        severity: match.severity,
        status: match.status,
        action: guidance.fix_steps_text || match.action,
        summary: guidance.operator_summary_text || match.summary,
        metadata: match.metadata || {},
        finding_type: match.finding_type,
        source_scope: match.source_scope,
        observed: match.observed || [],
        expected: match.expected || [],
        evidence: match.evidence || [],
        fix_steps: match.fix_steps || [],
        verification_checks: match.verification_checks || [],
        history: match.history || [],
        generated_guidance: guidance,
        packages: match.metadata?.packages || [],
        vulnerabilities: match.metadata?.vulnerabilities || [],
        findings: match.metadata?.findings || [],
        sourceLabel: sourceMeta.label,
        sourceSummary: sourceMeta.summary,
        provenance: sourceMeta.facts,
        chips: [
          { label: `+${match.score_impact || 0} score`, tone: 'bg-sky-100 text-sky-700 border-sky-200' },
          { label: `${match.asset_count || 0} asset${match.asset_count === 1 ? '' : 's'}`, tone: 'bg-slate-100 text-slate-700 border-slate-200' },
        ],
      }
    }
    if (selectedTactical.kind === 'finding') {
      const match = liveFindings.find((item) => item.id === selectedTactical.id)
      if (!match) return null
      const guidance = match.generated_guidance || match.metadata?.generated_guidance || match.metadata?.detail_contract?.generated_guidance || {}
      const sourceKind = tacticalSourceKind(match, 'finding')
      const sourceMeta = telemetrySourceMeta(sourceKind, appApiScopeForFinding(match))
      return {
        kind: 'finding',
        title: match.title,
        subtitle: match.metadata?.asset_name || match.category,
        severity: match.severity,
        status: match.status,
        action: guidance.fix_steps_text || match.metadata?.recommended_action || 'Review the affected asset, verify the runtime or build condition, and remediate the underlying cause.',
        summary: guidance.operator_summary_text || match.metadata?.summary || match.title,
        metadata: match.metadata || {},
        finding_type: match.finding_type,
        source_scope: match.source_scope,
        observed: match.observed || [],
        expected: match.expected || [],
        evidence: match.evidence || [],
        fix_steps: match.fix_steps || [],
        verification_checks: match.verification_checks || [],
        history: match.history || [],
        generated_guidance: guidance,
        packages: match.metadata?.packages || [],
        vulnerabilities: match.metadata?.vulnerabilities || [],
        sourceLabel: sourceMeta.label,
        sourceSummary: sourceMeta.summary,
        provenance: [
          ...sourceMeta.facts,
          { label: 'Finding source', value: match.source || 'collector' },
        ],
        chips: [
          { label: match.category || 'finding', tone: 'bg-slate-100 text-slate-700 border-slate-200' },
          { label: match.source || 'collector', tone: 'bg-slate-100 text-slate-700 border-slate-200' },
        ],
      }
    }
    if (selectedTactical.kind === 'record') {
      const match = liveFocusedRecords.find((item) => item.id === selectedTactical.id)
      if (!match) return null
      const sourceMeta = telemetrySourceMeta('app', 'detections')
      return {
        kind: 'record',
        title: match.title,
        subtitle: match.scope,
        severity: match.severity,
        status: match.status,
        action: match.nextStep,
        summary: match.metadata?.detail_contract?.evidence?.[0]?.value || match.title,
        metadata: match.metadata || {},
        finding_type: match.finding_type,
        source_scope: match.source_scope,
        observed: match.observed || [],
        expected: match.expected || [],
        evidence: match.evidence || [],
        fix_steps: match.fix_steps || [],
        verification_checks: match.verification_checks || [],
        history: match.history || [],
        generated_guidance: match.generated_guidance || {},
        sourceLabel: sourceMeta.label,
        sourceSummary: sourceMeta.summary,
        provenance: sourceMeta.facts,
        chips: match.chips || [],
      }
    }
    if (selectedTactical.kind === 'collector') {
      const match = tacticalCollectors.find((item) => item.id === selectedTactical.id)
      if (!match) return null
      const sourceMeta = telemetrySourceMeta('live')
      return {
        kind: 'collector',
        title: match.name,
        subtitle: match.connector_type || 'security collector',
        severity: match.status === 'healthy' ? 'low' : 'medium',
        status: match.status,
        action: 'Review the latest sync, verify the collector is still posting signed telemetry, and confirm the collector scope still reflects the assets you want monitored.',
        summary: match.last_sync_summary || 'Collector is registered and available for tactical security telemetry.',
        sourceLabel: sourceMeta.label,
        sourceSummary: sourceMeta.summary,
        provenance: [
          ...sourceMeta.facts,
          { label: 'Collector', value: match.name },
          { label: 'Auth mode', value: match.auth_mode || 'signed' },
        ],
        chips: [
          { label: match.auth_mode || 'signed', tone: 'bg-slate-100 text-slate-700 border-slate-200' },
          { label: match.status || 'unknown', tone: match.status === 'healthy' ? 'bg-emerald-100 text-emerald-700 border-emerald-200' : 'bg-amber-100 text-amber-700 border-amber-200' },
        ],
      }
    }
    if (selectedTactical.kind === 'summary') {
      const key = selectedTactical.id
      const map = {
        'app:all': {
          title: 'App API',
          subtitle: 'Internal application telemetry',
          severity: 'medium',
          status: 'healthy',
          action: 'Use the app-native findings to understand identity, configuration, and job health from inside ATO Bot itself.',
          summary: `${appApiSummary.totalFindings} open app-native finding(s) and ${appApiSummary.totalRecommendations} related recommendation(s) are currently in scope.`,
          sourceLabel: 'App-native telemetry',
          sourceSummary: 'These findings are produced directly by ATO Bot and represent what the app can say about itself.',
          provenance: telemetrySourceMeta('app').facts,
          chips: [
            { label: `${appApiSummary.identity} identity`, tone: 'bg-sky-100 text-sky-700 border-sky-200' },
            { label: `${appApiSummary.configuration} configuration`, tone: 'bg-violet-100 text-violet-700 border-violet-200' },
            { label: `${appApiSummary.jobs} jobs`, tone: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
            { label: `${appApiSummary.dataProtection} data protection`, tone: 'bg-cyan-100 text-cyan-700 border-cyan-200' },
            { label: `${appApiSummary.changeEvents} change events`, tone: 'bg-sky-100 text-sky-700 border-sky-200' },
            { label: `${appApiSummary.detections} detections`, tone: 'bg-rose-100 text-rose-700 border-rose-200' },
          ],
        },
        'app:identity': {
          title: 'Identity',
          subtitle: 'Internal user, MFA, and session telemetry',
          severity: 'medium',
          status: (identityDomain.findings?.length || 0) > 0 ? 'attention' : 'healthy',
          action: 'Review refresh-session hygiene, MFA coverage, dormant access, and recent authentication activity.',
          summary: `${identityDomain.findings?.length || 0} app-native identity finding(s) are currently open, including refresh-session hygiene issues.`,
          sourceLabel: 'App-native telemetry',
          sourceSummary: 'Identity findings come from the internal security API and reflect accounts, MFA posture, auth events, and refresh-session hygiene.',
          provenance: telemetrySourceMeta('app', 'identity').facts,
          chips: [
            { label: `${identityDomain.summary?.active_refresh_sessions || 0} active sessions`, tone: 'bg-sky-100 text-sky-700 border-sky-200' },
            { label: `${identityDomain.summary?.expired_unrevoked_refresh_tokens || 0} expired tokens`, tone: 'bg-rose-100 text-rose-700 border-rose-200' },
            { label: `${identityDomain.summary?.stale_refresh_sessions || 0} stale sessions`, tone: 'bg-amber-100 text-amber-700 border-amber-200' },
          ],
        },
        'app:configuration': {
          title: 'Configuration',
          subtitle: 'Internal config and middleware telemetry',
          severity: 'medium',
          status: 'healthy',
          action: 'Review security posture from configuration: CORS, CSP, secret strength, and login protection.',
          summary: `${configurationDomain.findings?.length || 0} app-native configuration finding(s) are currently open.`,
          sourceLabel: 'App-native telemetry',
          sourceSummary: 'Configuration findings come from the internal security API and reflect the running app settings and middleware posture.',
          provenance: telemetrySourceMeta('app', 'configuration').facts,
          chips: [
            { label: `${configurationDomain.summary?.wildcard_cors ? 'wildcard CORS' : 'no wildcard CORS'}`, tone: configurationDomain.summary?.wildcard_cors ? 'bg-rose-100 text-rose-700 border-rose-200' : 'bg-emerald-100 text-emerald-700 border-emerald-200' },
            { label: `${configurationDomain.summary?.csp_unsafe_inline ? 'unsafe-inline CSP' : 'CSP tightened'}`, tone: configurationDomain.summary?.csp_unsafe_inline ? 'bg-amber-100 text-amber-700 border-amber-200' : 'bg-emerald-100 text-emerald-700 border-emerald-200' },
          ],
        },
        'app:jobs': {
          title: 'Jobs',
          subtitle: 'Internal pipeline and monitoring telemetry',
          severity: 'medium',
          status: 'healthy',
          action: 'Review ingestion, assessment, parser, and security-event backlog health from inside the app.',
          summary: `${jobsDomain.findings?.length || 0} app-native jobs and monitoring finding(s) are currently open.`,
          sourceLabel: 'App-native telemetry',
          sourceSummary: 'Jobs findings come from the internal security API and reflect ingestion, assessment, and security event health.',
          provenance: telemetrySourceMeta('app', 'jobs').facts,
          chips: [
            { label: `${jobsDomain.summary?.failed_ingestions_24h || 0} failed ingest`, tone: 'bg-amber-100 text-amber-700 border-amber-200' },
            { label: `${jobsDomain.summary?.stuck_ingestions || 0} stuck`, tone: 'bg-rose-100 text-rose-700 border-rose-200' },
          ],
        },
        'app:data_protection': {
          title: 'Data Protection',
          subtitle: 'Evidence storage and backing-service posture',
          severity: 'medium',
          status: 'attention',
          action: 'Review credential fallback posture, evidence storage protections, and retention visibility from inside the app.',
          summary: `${dataProtectionDomain.findings?.length || 0} app-native data protection finding(s) are currently open.`,
          sourceLabel: 'App-native telemetry',
          sourceSummary: 'Data protection findings come from the internal security API and reflect evidence storage, service credentials, and retention posture.',
          provenance: telemetrySourceMeta('app', 'data protection').facts,
          chips: [
            { label: dataProtectionDomain.summary?.database_secret_fallback ? 'DB fallback secret' : 'DB secret ok', tone: dataProtectionDomain.summary?.database_secret_fallback ? 'bg-rose-100 text-rose-700 border-rose-200' : 'bg-emerald-100 text-emerald-700 border-emerald-200' },
            { label: dataProtectionDomain.summary?.redis_secret_fallback ? 'Redis fallback secret' : 'Redis secret ok', tone: dataProtectionDomain.summary?.redis_secret_fallback ? 'bg-rose-100 text-rose-700 border-rose-200' : 'bg-emerald-100 text-emerald-700 border-emerald-200' },
          ],
        },
        'app:change_events': {
          title: 'Change Events',
          subtitle: 'Recent drift and regression telemetry',
          severity: 'medium',
          status: 'attention',
          action: 'Review recent regressions, unexpected drift, and config churn to understand what changed and what needs review.',
          summary: `${changeEventsDomain.findings?.length || 0} app-native change finding(s) are currently open.`,
          sourceLabel: 'App-native telemetry',
          sourceSummary: 'Change findings come from tracked security changes and recent configuration drift in the internal security API.',
          provenance: telemetrySourceMeta('app', 'change events').facts,
          chips: [
            { label: `${changeEventsDomain.summary?.regressions_7d || 0} regressions`, tone: 'bg-rose-100 text-rose-700 border-rose-200' },
            { label: `${changeEventsDomain.summary?.unexpected_changes_7d || 0} unexpected`, tone: 'bg-amber-100 text-amber-700 border-amber-200' },
          ],
        },
        'app:detections': {
          title: 'Detections',
          subtitle: 'Active cyber signal and detection backlog',
          severity: 'medium',
          status: 'attention',
          action: 'Review unresolved detections and suspicious activity clusters to decide whether escalation or investigation is required.',
          summary: `${detectionsDomain.summary?.open_detections_7d || 0} detection event(s) are currently open, with ${detectionsDomain.findings?.length || 0} promoted finding(s).`,
          sourceLabel: 'App-native telemetry',
          sourceSummary: 'Detection findings come from the internal security API and reflect unresolved security signals and suspicious events.',
          provenance: telemetrySourceMeta('app', 'detections').facts,
          chips: [
            { label: `${detectionsDomain.summary?.open_detections_7d || 0} open`, tone: 'bg-slate-100 text-slate-700 border-slate-200' },
            { label: `${detectionsDomain.summary?.open_high_detections_7d || 0} high`, tone: 'bg-rose-100 text-rose-700 border-rose-200' },
          ],
        },
        collector_count: {
          title: 'Collectors',
          subtitle: 'Telemetry coverage',
          severity: 'low',
          status: 'healthy',
          action: 'Add more collectors only when they improve visibility. Keep collector scope narrow and signed.',
          summary: `${tacticalSummary.collector_count || 0} collector(s) are currently feeding tactical security data.`,
          sourceLabel: 'Collector telemetry',
          sourceSummary: 'Collectors provide external runtime and environment observations around the system.',
          provenance: telemetrySourceMeta('live').facts,
          chips: tacticalCollectors.slice(0, 3).map((item) => ({ label: item.name, tone: 'bg-slate-100 text-slate-700 border-slate-200' })),
        },
        asset_count: {
          title: 'Assets',
          subtitle: 'Assets currently represented in tactical telemetry',
          severity: 'low',
          status: 'healthy',
          action: 'Use collector scope and asset coverage to make sure the dashboard reflects the system you actually care about.',
          summary: `${tacticalSummary.asset_count || 0} asset(s) are represented in the current tactical security model.`,
          chips: [],
        },
        open_findings: {
          title: 'Open Findings',
          subtitle: 'Immediate tactical risk',
          severity: 'medium',
          status: 'attention',
          action: 'Focus remediation on the highest-impact open findings first, especially anything affecting the runtime or supply-chain posture.',
          summary: `${tacticalSummary.open_findings || 0} open finding(s) are currently driving the tactical security score.`,
          chips: [
            { label: `${tacticalSummary.critical_findings || 0} critical`, tone: 'bg-red-100 text-red-700 border-red-200' },
            { label: `${tacticalSummary.high_findings || 0} high`, tone: 'bg-rose-100 text-rose-700 border-rose-200' },
          ],
        },
        critical_findings: {
          title: 'Critical Findings',
          subtitle: 'Most urgent tactical issues',
          severity: 'critical',
          status: 'attention',
          action: 'Treat critical findings as immediate action items and verify whether any of them should block promotion or continued operation.',
          summary: `${tacticalSummary.critical_findings || 0} critical finding(s) are currently open.`,
          chips: [],
        },
        high_findings: {
          title: 'High Findings',
          subtitle: 'High-priority tactical issues',
          severity: 'high',
          status: 'attention',
          action: 'Review the highest-severity findings and recommendations first because they move the security score fastest and usually represent the biggest operational risk.',
          summary: `${tacticalSummary.high_findings || 0} high-severity finding(s) are currently open.`,
          chips: [],
        },
      }
      return { kind: 'summary', ...map[key] }
    }
    return null
  }, [selectedTactical, liveRecommendations, liveFindings, liveFocusedRecords, tacticalCollectors, liveSummary, appApiSummary, identityDomain, configurationDomain, jobsDomain, dataProtectionDomain, changeEventsDomain, detectionsDomain, liveFocus])

  const selectedTacticalEvidenceSections = useMemo(
    () => (selectedTacticalDetail ? buildEvidenceSections(selectedTacticalDetail) : []),
    [selectedTacticalDetail],
  )
  const selectedTacticalSectionGroups = useMemo(
    () => partitionEvidenceSections(selectedTacticalEvidenceSections),
    [selectedTacticalEvidenceSections],
  )
  const selectedTacticalRelatedFindings = useMemo(() => {
    if (!selectedTactical) return []
    if (selectedTactical.kind === 'finding') {
      return liveFindings.filter((item) => item.id === selectedTactical.id)
    }
    const targetId = String(selectedTactical.id)
    return liveFindings.filter((item) => {
      const relatedRecommendations = (item.metadata?.related_recommendation_ids || []).map((value) => String(value))
      const relatedSignals = (item.metadata?.related_signal_ids || []).map((value) => String(value))
      if (selectedTactical.kind === 'recommendation') return relatedRecommendations.includes(targetId)
      if (selectedTactical.kind === 'record') return relatedSignals.includes(targetId)
      return false
    })
  }, [selectedTactical, liveFindings])
  const selectedTacticalRelatedRecommendations = useMemo(() => {
    if (!selectedTactical) return []
    if (selectedTactical.kind === 'recommendation') {
      return liveRecommendations.filter((item) => item.id === selectedTactical.id)
    }
    const targetId = String(selectedTactical.id)
    return liveRecommendations.filter((item) => {
      const findingIds = (item.finding_ids || []).map((value) => String(value))
      const relatedSignals = (item.metadata?.related_signal_ids || []).map((value) => String(value))
      if (selectedTactical.kind === 'finding') return findingIds.includes(targetId)
      if (selectedTactical.kind === 'record') return relatedSignals.includes(targetId)
      return false
    })
  }, [selectedTactical, liveRecommendations])
  const selectedTacticalRelatedVerificationChecks = useMemo(() => {
    if (!selectedTactical) return []
    const targetId = String(selectedTactical.id)
    return verificationResults.filter((item) => {
      const metadata = item.metadata || {}
      if (selectedTactical.kind === 'finding') {
        return (metadata.related_finding_ids || []).map((value) => String(value)).includes(targetId)
      }
      if (selectedTactical.kind === 'recommendation') {
        return (metadata.related_recommendation_ids || []).map((value) => String(value)).includes(targetId)
      }
      if (selectedTactical.kind === 'record') {
        return (metadata.related_signal_ids || []).map((value) => String(value)).includes(targetId)
      }
      return false
    })
  }, [selectedTactical, verificationResults])
  const selectedTacticalRelatedControls = useMemo(() => {
    if (!selectedTactical) return []
    const targetId = String(selectedTactical.id)
    return controlSupport.filter((item) => {
      if (selectedTactical.kind === 'finding') {
        return (item.related_finding_ids || []).map((value) => String(value)).includes(targetId)
      }
      if (selectedTactical.kind === 'recommendation') {
        return (item.related_recommendation_ids || []).map((value) => String(value)).includes(targetId)
      }
      if (selectedTactical.kind === 'record') {
        return (item.related_signal_ids || []).map((value) => String(value)).includes(targetId)
      }
      return false
    })
  }, [selectedTactical, controlSupport])

  const openVerificationFromLive = (check) => {
    if (!check) return
    setSelectedAssuranceStatus('all')
    setSelectedControlId(check.control_id || 'all')
    setSelectedVerificationKey(check.check_key)
    setActiveTab('assurance')
  }

  const openControlFromLive = (control) => {
    if (!control) return
    setSelectedAssuranceStatus('all')
    setSelectedControlId(control.control_id || 'all')
    const firstCheck = (control.checks || [])[0]
    if (firstCheck?.check_key) {
      setSelectedVerificationKey(firstCheck.check_key)
    }
    setActiveTab('assurance')
  }

  const openAssuranceFindingInLive = (finding) => {
    if (!finding) return
    const source = String(finding.source || '')
    const scope = appApiScopeForFinding(finding)
    if (scope) {
      setLiveFocus(`app:${scope}`)
    } else if (source.startsWith('collector:')) {
      setLiveFocus('all')
    } else if (source.startsWith('build:')) {
      setActiveTab('build')
      return
    } else {
      setLiveFocus('all')
    }
    setSelectedTactical({ kind: 'finding', id: finding.id })
    setActiveTab('live')
  }

  const openAssuranceRecommendationInLive = (recommendation) => {
    if (!recommendation) return
    const scope = appApiScopeForRecommendation(recommendation)
    if (scope) {
      setLiveFocus(`app:${scope}`)
    } else {
      setLiveFocus('all')
    }
    setSelectedTactical({ kind: 'recommendation', id: recommendation.id })
    setActiveTab('live')
  }

  const liveIssueRows = useMemo(() => {
    const recommendationRows = liveFocusedRecommendations.map((item) => ({
      key: `recommendation-${item.id}`,
      kind: 'recommendation',
      id: item.id,
      title: item.title,
      scope: item.domain,
      source: tacticalSourceKind(item, 'recommendation'),
      severity: tacticalRecommendationSeverity(item),
      status: item.status || 'attention',
      nextStep: item.action,
      score: item.score_impact || 0,
      chips: [
        { label: `+${item.score_impact || 0} pts`, tone: 'bg-sky-100 text-sky-700 border-sky-200' },
        { label: `${item.asset_count || 0} asset${item.asset_count === 1 ? '' : 's'}`, tone: 'bg-slate-100 text-slate-700 border-slate-200' },
      ],
    }))

    const findingRows = liveFocusedFindings.map((item) => ({
      key: `finding-${item.id}`,
      kind: 'finding',
      id: item.id,
      title: item.title,
      scope: item.metadata?.asset_name || item.category,
      source: tacticalSourceKind(item, 'finding'),
      severity: item.severity || 'medium',
      status: item.status || 'open',
      nextStep: item.metadata?.recommended_action || 'Inspect the affected runtime asset and remediate the underlying issue.',
      score: 0,
      chips: [
        { label: item.category || 'finding', tone: 'bg-slate-100 text-slate-700 border-slate-200' },
      ],
    }))

    return [...recommendationRows, ...findingRows, ...liveFocusedRecords].sort((a, b) => {
      const severityDelta = severityRank(b.severity) - severityRank(a.severity)
      if (severityDelta !== 0) return severityDelta
      return (b.score || 0) - (a.score || 0)
    })
  }, [liveFocusedRecommendations, liveFocusedFindings, liveFocusedRecords])

  const liveScopeCounts = useMemo(() => {
    const base = {
      findings: liveFocusedFindings.length,
      recommendations: liveFocusedRecommendations.length,
      rows: liveIssueRows.length,
      signalCount: null,
      signalLabel: null,
    }

    if (liveFocus === 'app:change_events') {
      return {
        ...base,
        signalCount: changeEventsDomain.summary?.recent_changes_7d || 0,
        signalLabel: 'signals',
      }
    }

    if (liveFocus === 'app:detections') {
      return {
        ...base,
        signalCount: liveDetections.filter((item) => !item.resolved).length || 0,
        signalLabel: 'open signals',
      }
    }

    return base
  }, [
    liveFocus,
    liveFocusedFindings.length,
    liveFocusedRecommendations.length,
    liveIssueRows.length,
    changeEventsDomain.summary,
    liveDetections,
  ])

  const selectedLiveIssue = useMemo(() => {
    if (!selectedTactical) return liveIssueRows[0] || null
    return liveIssueRows.find((item) => item.kind === selectedTactical.kind && item.id === selectedTactical.id) || liveIssueRows[0] || null
  }, [liveIssueRows, selectedTactical])

  const selectedOverviewDetail = useMemo(() => {
    const map = {
      secure_score: {
        title: 'Secure Score',
        summary: `${secureScore.earned_points || 0} of ${secureScore.total_points || 0} points are currently earned from the active recommendation model.`,
        helper: 'Use this as the fast overall posture signal, then drill into the recommendations and tactical findings driving the score.',
        chips: [
          { label: `${secureScore.percentage || 0}%`, tone: 'bg-blue-100 text-blue-700 border-blue-200' },
          { label: `${recommendationStatus.total_recommendations || 0} recommendations`, tone: 'bg-slate-100 text-slate-700 border-slate-200' },
        ],
      },
      controls_completed: {
        title: 'Completed Controls',
        summary: `${recommendationStatus.completed_controls || 0} of ${recommendationStatus.total_controls || 0} control groupings are currently considered complete.`,
        helper: 'This lets you contrast what is already healthy against what still needs remediation.',
        chips: [
          { label: `${recommendationStatus.completed_controls || 0}/${recommendationStatus.total_controls || 0}`, tone: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
        ],
      },
      recommendation_closure: {
        title: 'Recommendation Closure',
        summary: `${recommendationStatus.completed_recommendations || 0} of ${recommendationStatus.total_recommendations || 0} recommendations are currently closed.`,
        helper: 'This is the fastest operational view of how much work remains in the current recommendation set.',
        chips: [
          { label: `${recommendationStatus.completed_recommendations || 0}/${recommendationStatus.total_recommendations || 0}`, tone: 'bg-slate-100 text-slate-700 border-slate-200' },
        ],
      },
      unhealthy_resources: {
        title: 'Unhealthy Resources',
        summary: `${resourceHealth.unhealthy || 0} resource(s) currently back active risk signals or unresolved recommendations.`,
        helper: 'Use this when you want to focus on the actual affected assets instead of the higher-level score.',
        chips: [
          { label: `${resourceHealth.unhealthy || 0} unhealthy`, tone: 'bg-rose-100 text-rose-700 border-rose-200' },
          { label: `${resourceHealth.total || 0} total`, tone: 'bg-slate-100 text-slate-700 border-slate-200' },
        ],
      },
      healthy_resources: {
        title: 'Healthy Resources',
        summary: `${resourceHealth.healthy || 0} resource(s) are currently healthy against the recommendation model.`,
        helper: 'This is useful for seeing what is already stabilized and where the dashboard has positive coverage.',
        chips: [
          { label: `${resourceHealth.healthy || 0} healthy`, tone: 'bg-lime-100 text-lime-700 border-lime-200' },
        ],
      },
      na_resources: {
        title: 'Not Applicable Resources',
        summary: `${resourceHealth.not_applicable || 0} resource(s) are currently outside the active recommendation scope.`,
        helper: 'This explains why some totals do not map to actionable work in the table below.',
        chips: [
          { label: `${resourceHealth.not_applicable || 0} N/A`, tone: 'bg-slate-100 text-slate-700 border-slate-200' },
        ],
      },
      evidence_trust: {
        title: 'Evidence Trust',
        summary: `${metrics.static_attestations_healthy || 0} of ${metrics.static_attestations_total || 0} implementation attestations are currently healthy.`,
        helper: 'Trust is separate from tactical risk. It tells you whether the evidence base is believable enough to support cATO decisions.',
        chips: [
          { label: trustLevel, tone: trustLevel === 'high' ? 'bg-emerald-100 text-emerald-700 border-emerald-200' : trustLevel === 'medium' ? 'bg-amber-100 text-amber-700 border-amber-200' : 'bg-rose-100 text-rose-700 border-rose-200' },
        ],
      },
    }
    return map[selectedOverview] || map.secure_score
  }, [selectedOverview, secureScore, recommendationStatus, resourceHealth, metrics, trustLevel])

  const overviewFocus = useMemo(() => {
    const focusRecommendations = (() => {
      if (selectedOverview === 'controls_completed') {
        return recommendations.filter((item) => item.status === 'completed').slice(0, 4)
      }
      if (selectedOverview === 'recommendation_closure') {
        return recommendations.filter((item) => item.status !== 'completed').slice(0, 4)
      }
      if (selectedOverview === 'unhealthy_resources') {
        return recommendations.filter((item) => (item.unhealthy_resources || 0) > 0).slice(0, 4)
      }
      if (selectedOverview === 'healthy_resources') {
        return recommendations.filter((item) => (item.unhealthy_resources || 0) === 0 && (item.healthy_resources || 0) > 0).slice(0, 4)
      }
      if (selectedOverview === 'na_resources') {
        return recommendations.filter((item) => (item.not_applicable_resources || 0) > 0).slice(0, 4)
      }
      if (selectedOverview === 'evidence_trust') {
        return recommendations.filter((item) => item.status === 'attention').slice(0, 4)
      }
      return topActions.slice(0, 4)
    })()

    const summaryMap = {
      secure_score: {
        title: 'Priority Queue',
        helper: 'Highest-value recommendations driving the overall security score.',
        cta: { label: 'Go to live', tab: 'live' },
      },
      controls_completed: {
        title: 'Completed Coverage',
        helper: 'Recommendations already stabilized so you can compare healthy coverage against remaining risk.',
        cta: { label: 'Review live state', tab: 'live' },
      },
      recommendation_closure: {
        title: 'Remaining Work',
        helper: 'The open queue still dragging closure and score improvement.',
        cta: { label: 'Open live queue', tab: 'live' },
      },
      unhealthy_resources: {
        title: 'Affected Assets',
        helper: 'Recommendations with live unhealthy resources behind them right now.',
        cta: { label: 'Open live issues', tab: 'live' },
      },
      healthy_resources: {
        title: 'Healthy Coverage',
        helper: 'Recommendations currently backed by healthy resources and clean runtime posture.',
        cta: { label: 'Open live coverage', tab: 'live' },
      },
      na_resources: {
        title: 'Out of Scope',
        helper: 'Recommendations currently marked not applicable so they do not distort the tactical queue.',
        cta: { label: 'Inspect evidence', tab: 'evidence' },
      },
      evidence_trust: {
        title: 'Trust Pressure',
        helper: 'Signals that matter most when deciding whether the evidence base is strong enough to rely on.',
        cta: { label: 'Open evidence', tab: 'evidence' },
      },
    }

    return {
      ...summaryMap[selectedOverview],
      rows: focusRecommendations,
    }
  }, [selectedOverview, recommendations, topActions])

  const tabSummary = useMemo(() => ([
    { key: 'overview', label: 'Overview', detail: 'Assessment actions, evidence gaps, and improvement queue' },
    { key: 'assurance', label: 'Assurance', detail: 'Continuous assurance checks, control support, and linked live proof' },
    { key: 'live', label: 'Live', detail: 'Runtime issues, collectors, and tactical findings' },
    { key: 'build', label: 'Build', detail: 'Software factory posture, snapshots, and supply-chain findings' },
    { key: 'changes', label: 'Changes', detail: 'Drift, trend lines, and recently changed security state' },
  ]), [])

  const activeTabMeta = useMemo(
    () => tabSummary.find((tab) => tab.key === activeTab) || tabSummary[0],
    [tabSummary, activeTab],
  )

  const liveVsBuild = useMemo(() => {
    const liveScore = latestRuntimeSnapshot?.security_score ?? 0
    const buildScore = latestBuildSnapshot?.security_score ?? 0
    return {
      liveScore,
      buildScore,
      delta: liveScore - buildScore,
      changeCount: securityOverview?.summary?.changes_since_build || 0,
      runtimeFindings: latestRuntimeSnapshot?.summary?.finding_count || 0,
      buildFindings: latestBuildSnapshot?.summary?.finding_count || 0,
    }
  }, [latestRuntimeSnapshot, latestBuildSnapshot, securityOverview?.summary?.changes_since_build])

  const verificationSummary = useMemo(() => ({
    total: verificationResults.length,
    pass: verificationResults.filter((item) => item.result === 'pass').length,
    degraded: verificationResults.filter((item) => item.result === 'degraded').length,
    fail: verificationResults.filter((item) => item.result === 'fail' || item.result === 'error').length,
    fresh: verificationResults.filter((item) => item.is_fresh).length,
  }), [verificationResults])

  const attentionVerificationChecks = useMemo(
    () => verificationResults
      .filter((item) => item.result !== 'pass')
      .sort((a, b) => {
        const rank = { fail: 3, error: 3, degraded: 2, pass: 1 }
        return (rank[b.result] || 0) - (rank[a.result] || 0)
      })
      .slice(0, 4),
    [verificationResults],
  )

  const prioritizedControlSupport = useMemo(
    () => [...controlSupport]
      .sort((a, b) => {
        const rank = { fail: 3, degraded: 2, pass: 1 }
        return (rank[b.status] || 0) - (rank[a.status] || 0)
      }),
    [controlSupport],
  )

  const assuranceChecks = useMemo(() => {
    const items = [...verificationResults].sort((a, b) => {
      const rank = { fail: 4, error: 4, degraded: 3, pass: 2 }
      const resultDelta = (rank[b.result] || 0) - (rank[a.result] || 0)
      if (resultDelta !== 0) return resultDelta
      return String(a.name || '').localeCompare(String(b.name || ''))
    })

    return items.filter((item) => {
      if (selectedControlId !== 'all' && item.control_id !== selectedControlId) return false
      if (selectedAssuranceStatus === 'pass') return item.result === 'pass'
      if (selectedAssuranceStatus === 'degraded') return item.result === 'degraded'
      if (selectedAssuranceStatus === 'fail') return ['fail', 'error'].includes(item.result)
      if (selectedAssuranceStatus === 'fresh') return Boolean(item.is_fresh)
      return true
    })
  }, [verificationResults, selectedControlId, selectedAssuranceStatus])

  const selectedAssuranceCheck = useMemo(
    () => assuranceChecks.find((item) => item.check_key === selectedVerificationKey) || null,
    [assuranceChecks, selectedVerificationKey],
  )

  useEffect(() => {
    if (!assuranceChecks.length) {
      setSelectedVerificationKey(null)
      return
    }
    if (!assuranceChecks.some((item) => item.check_key === selectedVerificationKey)) {
      setSelectedVerificationKey(null)
    }
  }, [assuranceChecks, selectedVerificationKey])

  const selectedAssuranceRelatedFindings = useMemo(() => {
    const ids = new Set((selectedAssuranceCheck?.metadata?.related_finding_ids || []).map((value) => String(value)))
    return liveFindings.filter((item) => ids.has(String(item.id)))
  }, [selectedAssuranceCheck, liveFindings])

  const selectedAssuranceRelatedRecommendations = useMemo(() => {
    const ids = new Set((selectedAssuranceCheck?.metadata?.related_recommendation_ids || []).map((value) => String(value)))
    return liveRecommendations.filter((item) => ids.has(String(item.id)))
  }, [selectedAssuranceCheck, liveRecommendations])

  const selectedAssuranceRelatedSignals = useMemo(() => {
    const ids = new Set((selectedAssuranceCheck?.metadata?.related_signal_ids || []).map((value) => String(value)))
    const recordSignals = (liveDetections || [])
      .filter((item) => !item.resolved && ids.has(`detection-${item.id}`))
      .map((item) => ({
        kind: 'record',
        id: `detection-${item.id}`,
        title: `Detection: ${titleCase(item.event_type || 'security event')}`,
        scope: 'App detection event',
      }))
    const liveSignalMatches = liveSignals.filter((item) => ids.has(String(item.id)))
    return {
      records: recordSignals,
      signals: liveSignalMatches,
    }
  }, [selectedAssuranceCheck, liveDetections, liveSignals])
  const selectedAssuranceRelatedControls = useMemo(() => {
    if (!selectedAssuranceCheck) return []
    return controlSupport.filter((item) => {
      if (item.control_id === selectedAssuranceCheck.control_id) return true
      return (item.checks || []).some((check) => check.check_key === selectedAssuranceCheck.check_key)
    })
  }, [selectedAssuranceCheck, controlSupport])

  const buildFocusedRecommendations = useMemo(
    () => sortedFiltered.filter((item) => ['Configuration & Secrets', 'Platform & Container Security'].includes(item.domain)).slice(0, 6),
    [sortedFiltered],
  )

  const changeSummary = useMemo(() => {
    const summary = { positive: 0, negative: 0, neutral: 0 }
    for (const item of recentChanges) {
      if (item.impact_direction === 'positive') summary.positive += 1
      else if (item.impact_direction === 'negative') summary.negative += 1
      else summary.neutral += 1
    }
    return summary
  }, [recentChanges])

  const scoreTrendSeries = useMemo(() => ([
    { label: 'Build', value: latestBuildSnapshot?.security_score ?? 0 },
    { label: 'Runtime', value: latestRuntimeSnapshot?.security_score ?? 0 },
    { label: 'Current', value: secureScore.percentage ?? 0 },
  ]), [latestBuildSnapshot?.security_score, latestRuntimeSnapshot?.security_score, secureScore.percentage])

  const scoreTrendPath = useMemo(() => {
    if (!scoreTrendSeries.length) return ''
    return scoreTrendSeries.map((point, index) => {
      const x = scoreTrendSeries.length === 1 ? 120 : (index / (scoreTrendSeries.length - 1)) * 240
      const y = 72 - ((point.value || 0) / 100) * 56
      return `${index === 0 ? 'M' : 'L'} ${x} ${y}`
    }).join(' ')
  }, [scoreTrendSeries])

  const improvementActions = useMemo(() => {
    const recommendationRows = recommendations.map((item) => {
      const source = recommendationSource(item)
      const reviewStatus = item.status === 'completed'
        ? 'Completed'
        : item.status === 'in_progress'
          ? 'Planned'
          : 'To address'
      return {
        key: `program-rec-${item.id}`,
        kind: 'recommendation',
        id: item.id,
        title: item.title,
        source,
        category: item.domain,
        severity: recommendationPriority(item),
        reviewStatus,
        scoreImpact: item.potential_points || 0,
        affectedAssets: item.unhealthy_resources || item.healthy_resources || 0,
        summary: item.action,
        nextAction: item.action,
      }
    })

    const tacticalRecommendationRows = tacticalRecommendations.map((item) => ({
      key: `tactical-rec-${item.id}`,
      kind: 'recommendation',
      id: item.id,
      title: item.title,
      source: isBuildRecommendation(item) ? 'build' : 'live',
      category: item.domain || getDomain(item.group || item.title),
      severity: tacticalRecommendationSeverity(item),
      reviewStatus: item.status === 'healthy' || item.status === 'completed' ? 'Completed' : 'To address',
      scoreImpact: item.score_impact || 0,
      affectedAssets: item.asset_count || 0,
      summary: item.summary || item.title,
      nextAction: item.action || item.summary || 'Review the affected assets and remediate the issue.',
    }))

    const findingRows = openTacticalFindings.map((item) => ({
      key: `tactical-finding-${item.id}`,
      kind: 'finding',
      id: item.id,
      title: item.title,
      source: isBuildFinding(item) ? 'build' : 'live',
      category: item.category || 'Monitoring & Audit',
      severity: item.severity || 'medium',
      reviewStatus: item.impact_direction === 'negative' ? 'Regressed' : 'To address',
      scoreImpact: item.severity === 'critical' ? 12 : item.severity === 'high' ? 8 : 4,
      affectedAssets: 1,
      summary: item.metadata?.summary || item.title,
      nextAction: item.metadata?.recommended_action || 'Inspect the affected asset and remediate the finding.',
    }))

    return [...recommendationRows, ...tacticalRecommendationRows, ...findingRows]
  }, [recommendations, tacticalRecommendations, openTacticalFindings])

  const includedImprovementActions = useMemo(
    () => improvementActions.filter((item) => includeSource === 'both' || item.source === includeSource),
    [improvementActions, includeSource],
  )

  const filteredImprovementActions = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return includedImprovementActions
      .filter((item) => actionStatusFilter === 'all' || item.reviewStatus === actionStatusFilter)
      .filter((item) => (
        !needle
        || item.title.toLowerCase().includes(needle)
        || item.category.toLowerCase().includes(needle)
        || item.summary.toLowerCase().includes(needle)
        || item.nextAction.toLowerCase().includes(needle)
      ))
      .sort((a, b) => {
        if (tableSort.key === 'score') return (b.scoreImpact - a.scoreImpact) * (tableSort.direction === 'asc' ? -1 : 1)
        if (tableSort.key === 'unhealthy') return (b.affectedAssets - a.affectedAssets) * (tableSort.direction === 'asc' ? -1 : 1)
        return a.title.localeCompare(b.title) * (tableSort.direction === 'asc' ? 1 : -1)
      })
  }, [includedImprovementActions, actionStatusFilter, search, tableSort])

  const topImprovementActions = useMemo(
    () => filteredImprovementActions.slice(0, 6),
    [filteredImprovementActions],
  )

  const actionReviewCounts = useMemo(() => ({
    regressed: filteredImprovementActions.filter((item) => item.reviewStatus === 'Regressed').length,
    toAddress: filteredImprovementActions.filter((item) => item.reviewStatus === 'To address').length,
    planned: filteredImprovementActions.filter((item) => item.reviewStatus === 'Planned').length,
    riskAccepted: filteredImprovementActions.filter((item) => item.reviewStatus === 'Risk accepted').length,
    recentlyAdded: recentChanges.filter((item) => item.change_status === 'observed').length,
    recentlyUpdated: recentChanges.length,
  }), [filteredImprovementActions, recentChanges])

  const selectedImprovementAction = useMemo(() => {
    if (!filteredImprovementActions.length) return null
    if (!selectedTactical) return filteredImprovementActions[0]
    return filteredImprovementActions.find((item) => item.kind === selectedTactical.kind && item.id === selectedTactical.id) || filteredImprovementActions[0]
  }, [filteredImprovementActions, selectedTactical])

  const latestChangeHeadline = useMemo(
    () => summarizeChangeHeadline(recentChanges[0]),
    [recentChanges],
  )

  const unhealthyAttestations = useMemo(
    () => attestations.filter((item) => !item.healthy),
    [attestations],
  )

  const degradedAssertions = useMemo(
    () => assertions.filter((item) => item.status !== 'healthy'),
    [assertions],
  )

  const overviewLensCounts = useMemo(() => {
    const recommendationRows = recommendations.map((item) => ({
      source: recommendationSource(item),
      severity: recommendationPriority(item),
    }))
    const findingRows = openTacticalFindings.map((item) => ({
      severity: item.severity || 'medium',
    }))
    const evidenceRows = unhealthyAttestations.length + degradedAssertions.length

    return {
      needs_attention: recommendationRows.filter((item) => item.severity === 'critical' || item.severity === 'high').length + findingRows.length,
      runtime_risk: findingRows.length + recommendationRows.filter((item) => item.source === 'live').length,
      build_risk: recommendationRows.filter((item) => item.source === 'build').length,
      drift_since_build: recentChanges.length,
      evidence_gaps: evidenceRows,
    }
  }, [recommendations, openTacticalFindings, unhealthyAttestations.length, degradedAssertions.length, recentChanges.length])

  const overviewLenses = useMemo(() => ([
    {
      key: 'needs_attention',
      label: 'Needs Attention',
      count: overviewLensCounts.needs_attention,
      tone: 'border-rose-200 bg-rose-50 text-rose-700',
      helper: 'Queue issues that currently need action.',
    },
    {
      key: 'runtime_risk',
      label: 'Runtime Risk',
      count: overviewLensCounts.runtime_risk,
      tone: 'border-amber-200 bg-amber-50 text-amber-700',
      helper: 'Live queue issues coming from the app, host, or running containers.',
    },
    {
      key: 'build_risk',
      label: 'Build Risk',
      count: overviewLensCounts.build_risk,
      tone: 'border-violet-200 bg-violet-50 text-violet-700',
      helper: 'Build queue recommendations tied to the software factory lane.',
    },
    {
      key: 'drift_since_build',
      label: 'Drift Since Build',
      count: overviewLensCounts.drift_since_build,
      tone: 'border-sky-200 bg-sky-50 text-sky-700',
      helper: 'Tracked change signals since the last build snapshot.',
    },
    {
      key: 'evidence_gaps',
      label: 'Evidence Gaps',
      count: overviewLensCounts.evidence_gaps,
      tone: 'border-slate-200 bg-slate-100 text-slate-700',
      helper: 'Evidence queue items that are too weak to trust yet.',
    },
  ]), [overviewLensCounts])

  const overviewActionQueue = useMemo(() => {
    const recommendationRows = recommendations.map((item) => ({
      key: `rec-${item.id}`,
      kind: 'recommendation',
      id: item.id,
      title: item.title,
      summary: item.action,
      severity: recommendationPriority(item),
      source: recommendationSource(item),
      domain: item.domain,
      affected: item.controls.join(' | '),
      nextAction: item.action,
      score: item.potential_points || 0,
      resourceCount: item.unhealthy_resources || 0,
      packages: [],
      vulnerabilities: [],
      metadata: {
        controls: item.controls,
        group: item.group,
        status: item.status,
        healthy_resources: item.healthy_resources,
        unhealthy_resources: item.unhealthy_resources,
        not_applicable_resources: item.not_applicable_resources,
      },
      routeTab: recommendationSource(item) === 'build' ? 'build' : 'live',
      onSelect: () => setSelectedId(item.id),
    }))

    const findingRows = openTacticalFindings.map((item) => ({
      key: `finding-${item.id}`,
      kind: 'finding',
      id: item.id,
      title: item.title,
      summary: item.metadata?.summary || item.title,
      severity: item.severity || 'medium',
      source: 'live',
      domain: 'Platform & Container Security',
      affected: item.metadata?.asset_name || item.category,
      nextAction: item.metadata?.recommended_action || 'Inspect the affected runtime asset and remediate the underlying issue.',
      score: 0,
      resourceCount: 1,
      packages: item.metadata?.packages || [],
      vulnerabilities: item.metadata?.vulnerabilities || [],
      metadata: item.metadata || {},
      routeTab: 'live',
      onSelect: () => setSelectedTactical({ kind: 'finding', id: item.id }),
    }))

    const changeRows = recentChanges.map((item) => ({
      key: `change-${item.id}`,
      kind: 'change',
      id: item.id,
      title: item.summary,
      summary: `${item.details?.setting_label || item.category} changed in ${item.source_snapshot_type}.`,
      severity: item.impact_direction === 'negative' ? 'high' : item.impact_direction === 'positive' ? 'low' : 'medium',
      source: 'change',
      domain: item.category || 'Operational Resilience',
      affected: item.details?.setting_label || item.category,
      nextAction: item.change_status === 'needs_review'
        ? 'Review the regression, decide whether it was approved, and either roll it back or document the exception.'
        : item.change_status === 'expected'
          ? 'Confirm the change lines up with the intended build or release and keep monitoring the downstream impact.'
          : 'Review the change and confirm whether it should be treated as normal drift or a tracked event.',
      score: 0,
      resourceCount: 0,
      packages: [],
      vulnerabilities: [],
      metadata: item.details || {},
      routeTab: 'changes',
      onSelect: null,
    }))

    const evidenceRows = [
      ...unhealthyAttestations.map((item) => ({
        key: `evidence-attestation-${item.id}`,
        kind: 'evidence',
        id: item.id,
        title: item.label,
        summary: `Implementation attestation is not currently healthy for ${item.controls.join(' | ')}.`,
        severity: 'medium',
        source: 'evidence',
        domain: 'Evidence',
        affected: item.controls.join(' | '),
        nextAction: 'Strengthen the implementation evidence or bring the underlying control support back into a healthy state.',
        score: 0,
        resourceCount: 0,
        packages: [],
        vulnerabilities: [],
        metadata: item,
        routeTab: 'evidence',
        onSelect: null,
      })),
      ...degradedAssertions.map((item) => ({
        key: `evidence-assertion-${item.label}`,
        kind: 'evidence',
        id: item.label,
        title: item.label,
        summary: item.hint || `${item.label} is not currently in a healthy state.`,
        severity: 'medium',
        source: 'evidence',
        domain: 'Evidence',
        affected: item.value,
        nextAction: 'Review the supporting signal and decide whether this should block reliance on the evidence set.',
        score: 0,
        resourceCount: 0,
        packages: [],
        vulnerabilities: [],
        metadata: item,
        routeTab: 'evidence',
        onSelect: null,
      })),
    ]

    if (selectedLens === 'runtime_risk') return [...findingRows, ...recommendationRows.filter((item) => item.source === 'live')].slice(0, 12)
    if (selectedLens === 'build_risk') return recommendationRows.filter((item) => item.source === 'build').slice(0, 12)
    if (selectedLens === 'drift_since_build') return changeRows.slice(0, 12)
    if (selectedLens === 'evidence_gaps') return evidenceRows.slice(0, 12)
    return [...recommendationRows.filter((item) => item.severity === 'critical' || item.severity === 'high'), ...findingRows].slice(0, 12)
  }, [recommendations, openTacticalFindings, recentChanges, unhealthyAttestations, degradedAssertions, selectedLens])

  const selectedOverviewQueueItem = useMemo(
    () => overviewActionQueue.find((item) => item.key === selectedOverviewItemKey) || overviewActionQueue[0] || null,
    [overviewActionQueue, selectedOverviewItemKey],
  )

  const selectedOverviewEvidenceSections = useMemo(
    () => (selectedOverviewQueueItem ? buildEvidenceSections(selectedOverviewQueueItem) : []),
    [selectedOverviewQueueItem],
  )
  const selectedOverviewSectionGroups = useMemo(
    () => partitionEvidenceSections(selectedOverviewEvidenceSections),
    [selectedOverviewEvidenceSections],
  )

  const selectedLensMeta = useMemo(
    () => overviewLenses.find((lens) => lens.key === selectedLens) || overviewLenses[0] || null,
    [overviewLenses, selectedLens],
  )

  const groupedOverviewQueue = useMemo(() => {
    if (overviewGroupBy === 'source') {
      return OVERVIEW_GROUP_ORDER.source
        .map((source) => ({
          key: source,
          meta: queueSourceMeta(source),
          items: overviewActionQueue.filter((item) => item.source === source),
        }))
        .filter((group) => group.items.length)
    }
    if (overviewGroupBy === 'severity') {
      return OVERVIEW_GROUP_ORDER.severity
        .map((severity) => ({
          key: severity,
          meta: {
            label: severity[0].toUpperCase() + severity.slice(1),
            tone: severityTone(severity),
            Icon: AlertTriangle,
          },
          items: overviewActionQueue.filter((item) => item.severity === severity),
        }))
        .filter((group) => group.items.length)
    }
    const domains = [...new Set(overviewActionQueue.map((item) => item.domain).filter(Boolean))]
    return domains.map((domain) => ({
      key: domain,
      meta: {
        label: domain,
        tone: DOMAIN_STYLES[domain]?.chip || 'bg-slate-100 text-slate-700 border-slate-200',
        Icon: ShieldCheck,
      },
      items: overviewActionQueue.filter((item) => item.domain === domain),
    }))
  }, [overviewActionQueue, overviewGroupBy])

  const overviewQueueCounts = useMemo(() => ({
    rows: overviewActionQueue.length,
    recommendations: overviewActionQueue.filter((item) => item.kind === 'recommendation').length,
    findings: overviewActionQueue.filter((item) => item.kind === 'finding').length,
    changes: overviewActionQueue.filter((item) => item.kind === 'change').length,
    evidence: overviewActionQueue.filter((item) => item.kind === 'evidence').length,
  }), [overviewActionQueue])

  useEffect(() => {
    if (!overviewActionQueue.length) {
      setSelectedOverviewItemKey(null)
      return
    }
    if (!overviewActionQueue.some((item) => item.key === selectedOverviewItemKey)) {
      setSelectedOverviewItemKey(overviewActionQueue[0].key)
    }
  }, [overviewActionQueue, selectedOverviewItemKey])

  const clearFilters = () => {
    setDomainFilter('all')
    setStatusFilter('all')
    setHealthFilter('all')
    setSearch('')
  }

  const selectOverviewQueueItem = (item) => {
    setSelectedOverviewItemKey(item.key)
    item.onSelect?.()
  }

  const moveOverviewSelection = (direction) => {
    if (!overviewActionQueue.length) return
    const currentIndex = overviewActionQueue.findIndex((item) => item.key === selectedOverviewItemKey)
    const nextIndex = currentIndex === -1
      ? 0
      : Math.max(0, Math.min(overviewActionQueue.length - 1, currentIndex + direction))
    const nextItem = overviewActionQueue[nextIndex]
    if (nextItem) {
      setSelectedOverviewItemKey(nextItem.key)
      nextItem.onSelect?.()
    }
  }

  const handleOverviewQueueKeyDown = (event) => {
    if (!overviewActionQueue.length) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      moveOverviewSelection(1)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      moveOverviewSelection(-1)
      return
    }
    if (event.key === 'Home') {
      event.preventDefault()
      const firstItem = overviewActionQueue[0]
      if (firstItem) selectOverviewQueueItem(firstItem)
      return
    }
    if (event.key === 'End') {
      event.preventDefault()
      const lastItem = overviewActionQueue[overviewActionQueue.length - 1]
      if (lastItem) selectOverviewQueueItem(lastItem)
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (selectedOverviewQueueItem) {
        selectOverviewQueueItem(selectedOverviewQueueItem)
      }
    }
  }

  const selectRecommendation = (id) => {
    setSelectedId(id)
  }

  const openInspectorForRecommendation = (id) => {
    selectRecommendation(id)
    setSelectedTactical({ kind: 'recommendation', id })
    setInspectorTab('summary')
    setInspectorOpen(true)
  }

  const openInspectorForImprovement = (item) => {
    if (!item) return
    if (item.kind === 'recommendation') {
      openInspectorForRecommendation(item.id)
      return
    }
    setSelectedTactical({ kind: item.kind, id: item.id })
    setInspectorTab('summary')
    setInspectorOpen(true)
  }

  const toggleTableSort = (key) => {
    setTableSort((current) => (
      current.key === key
        ? { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
        : { key, direction: key === 'title' ? 'asc' : 'desc' }
    ))
  }

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(posture || {}, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${project?.name || 'project'}-ato-bot-security-posture.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const selectedSecurityContext = useMemo(() => {
    if (activeTab === 'live' && selectedTacticalDetail) {
      const currentFindings = selectedTactical?.kind === 'finding' ? [liveFindings.find((item) => item.id === selectedTactical.id)].filter(Boolean) : selectedTacticalRelatedFindings
      const currentRecommendations = selectedTactical?.kind === 'recommendation' ? [liveRecommendations.find((item) => item.id === selectedTactical.id)].filter(Boolean) : selectedTacticalRelatedRecommendations
      const currentSignals = selectedTactical?.kind === 'record'
        ? [{ kind: 'record', id: selectedTactical.id, title: selectedTacticalDetail.title, scope: selectedTacticalDetail.subtitle }]
        : []

      return {
        title: selectedTacticalDetail.title,
        summary: selectedTacticalDetail.summary || selectedTacticalDetail.sourceSummary || 'Current live security object and its connected assurance context.',
        label: 'Selected Security Context',
        sourceLabel: selectedTacticalDetail.sourceLabel || 'Live telemetry',
        findings: currentFindings,
        recommendations: currentRecommendations,
        verificationChecks: selectedTacticalRelatedVerificationChecks,
        controls: selectedTacticalRelatedControls,
        signals: currentSignals,
      }
    }

    if (activeTab === 'assurance' && selectedAssuranceCheck) {
      return {
        title: selectedAssuranceCheck.name,
        summary: selectedAssuranceCheck.summary || 'Current assurance object and the live issues behind it.',
        label: 'Selected Security Context',
        sourceLabel: 'Assurance',
        findings: selectedAssuranceRelatedFindings,
        recommendations: selectedAssuranceRelatedRecommendations,
        verificationChecks: [selectedAssuranceCheck],
        controls: selectedAssuranceRelatedControls,
        signals: [...selectedAssuranceRelatedSignals.records, ...selectedAssuranceRelatedSignals.signals],
      }
    }

    return null
  }, [
    activeTab,
    selectedTacticalDetail,
    selectedTactical,
    liveFindings,
    liveRecommendations,
    selectedTacticalRelatedFindings,
    selectedTacticalRelatedRecommendations,
    selectedTacticalRelatedVerificationChecks,
    selectedTacticalRelatedControls,
    selectedAssuranceCheck,
    selectedAssuranceRelatedFindings,
    selectedAssuranceRelatedRecommendations,
    selectedAssuranceRelatedControls,
    selectedAssuranceRelatedSignals,
  ])

  return (
    <div className="min-h-screen bg-[#f5f8fc]">
      <div className="max-w-[1600px] mx-auto px-5 py-4 space-y-3">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate(`/projects/${projectId}`)} className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">
              <ArrowLeft size={15} />
              Back
            </button>
            <div>
              <h1 className="text-3xl font-bold tracking-tight text-slate-900">cATO Dashboard</h1>
              <p className="text-sm text-slate-500">Security recommendations for {project?.name || 'ATO Bot'}.</p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={downloadJson} className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">
              <Download size={15} />
              Download JSON
            </button>
            <button onClick={() => navigate(`/projects/${projectId}/integrations`)} className="inline-flex items-center gap-2 rounded-xl border border-sky-300 bg-white px-3 py-2 text-sm text-sky-700 hover:bg-sky-50">
              <Globe size={15} />
              Integrations
            </button>
            <button onClick={() => navigate(`/projects/${projectId}/architecture-tools`)} className="inline-flex items-center gap-2 rounded-xl border border-indigo-300 bg-white px-3 py-2 text-sm text-indigo-700 hover:bg-indigo-50">
              <Building2 size={15} />
              Architecture & Tools
            </button>
            <button
              onClick={() => openCyberAssistant({
                mode: 'workspace',
                title: `${project?.name || 'Project'} cATO Assistant`,
                projectId: Number(projectId),
                attachments: [{ type: 'project', resource_id: String(projectId), context_json: { view: 'cato_dashboard_security' } }],
                initialPrompt: 'Summarize the top ATO Bot security recommendations and explain the most important next actions.',
              })}
              className="inline-flex items-center gap-2 rounded-xl border border-violet-300 bg-white px-3 py-2 text-sm text-violet-700 hover:bg-violet-50"
            >
              <MessageSquare size={15} />
              Ask AI
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              {tabSummary.map((tab) => (
                <TabChip
                  key={tab.key}
                  active={activeTab === tab.key}
                  onClick={() => {
                    setActiveTab(tab.key)
                    setInspectorOpen(false)
                  }}
                >
                  {tab.label}
                </TabChip>
              ))}
            </div>
            <p className="text-xs text-slate-500">
              {activeTabMeta?.detail}
            </p>
          </div>
        </div>

        {activeTab === 'live' && selectedSecurityContext ? (
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{selectedSecurityContext.label}</p>
                <div className="mt-1 flex items-center gap-2 flex-wrap">
                  <p className="text-lg font-semibold text-slate-900">{selectedSecurityContext.title}</p>
                  <span className="inline-flex items-center rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-700">
                    {selectedSecurityContext.sourceLabel}
                  </span>
                </div>
                <p className="mt-1 max-w-4xl text-sm text-slate-600">{selectedSecurityContext.summary}</p>
              </div>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">{selectedSecurityContext.findings.length} findings</span>
                <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">{selectedSecurityContext.recommendations.length} recommendations</span>
                <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">{selectedSecurityContext.verificationChecks.length} checks</span>
                <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">{selectedSecurityContext.controls.length} controls</span>
                <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">{selectedSecurityContext.signals.length} signals</span>
              </div>
            </div>
            <div className="mt-3 grid gap-3 xl:grid-cols-5">
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Findings</p>
                  <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">{selectedSecurityContext.findings.length}</span>
                </div>
                <div className="mt-2 space-y-2">
                  {selectedSecurityContext.findings.length ? selectedSecurityContext.findings.slice(0, 3).map((item) => (
                    <button
                      key={`context-finding-${item.id}`}
                      type="button"
                      onClick={() => openAssuranceFindingInLive(item)}
                      className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-sky-50"
                    >
                      <p className="text-[11px] font-semibold text-slate-900">{item.title}</p>
                      <p className="mt-0.5 text-[10px] text-slate-500">{item.metadata?.asset_name || item.category || item.source_scope}</p>
                    </button>
                  )) : <p className="text-[11px] text-slate-500">No linked findings.</p>}
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Recommendations</p>
                  <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">{selectedSecurityContext.recommendations.length}</span>
                </div>
                <div className="mt-2 space-y-2">
                  {selectedSecurityContext.recommendations.length ? selectedSecurityContext.recommendations.slice(0, 3).map((item) => (
                    <button
                      key={`context-recommendation-${item.id}`}
                      type="button"
                      onClick={() => openAssuranceRecommendationInLive(item)}
                      className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-sky-50"
                    >
                      <p className="text-[11px] font-semibold text-slate-900">{item.title}</p>
                      <p className="mt-0.5 text-[10px] text-slate-500">{item.domain || item.owner_scope || 'recommendation'}</p>
                    </button>
                  )) : <p className="text-[11px] text-slate-500">No linked recommendations.</p>}
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Verification</p>
                  <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">{selectedSecurityContext.verificationChecks.length}</span>
                </div>
                <div className="mt-2 space-y-2">
                  {selectedSecurityContext.verificationChecks.length ? selectedSecurityContext.verificationChecks.slice(0, 3).map((item) => (
                    <button
                      key={`context-check-${item.check_key}`}
                      type="button"
                      onClick={() => openVerificationFromLive(item)}
                      className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-sky-50"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-[11px] font-semibold text-slate-900">{item.name}</p>
                        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${verificationStatusTone(item.result)}`}>{item.result}</span>
                      </div>
                      <p className="mt-0.5 text-[10px] text-slate-500">{item.control_id || item.domain || 'verification'}</p>
                    </button>
                  )) : <p className="text-[11px] text-slate-500">No linked checks.</p>}
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Control Support</p>
                  <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">{selectedSecurityContext.controls.length}</span>
                </div>
                <div className="mt-2 space-y-2">
                  {selectedSecurityContext.controls.length ? selectedSecurityContext.controls.slice(0, 3).map((item) => (
                    <button
                      key={`context-control-${item.control_id}`}
                      type="button"
                      onClick={() => openControlFromLive(item)}
                      className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-sky-50"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-[11px] font-semibold text-slate-900">{item.control_id}</p>
                        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${item.status === 'pass' ? 'border-emerald-200 bg-emerald-100 text-emerald-700' : item.status === 'degraded' ? 'border-amber-200 bg-amber-100 text-amber-700' : 'border-rose-200 bg-rose-100 text-rose-700'}`}>{item.status}</span>
                      </div>
                      <p className="mt-0.5 text-[10px] text-slate-500">{item.capability || 'cATO-relevant capability'}</p>
                    </button>
                  )) : <p className="text-[11px] text-slate-500">No linked control state.</p>}
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Signals</p>
                  <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">{selectedSecurityContext.signals.length}</span>
                </div>
                <div className="mt-2 space-y-2">
                  {selectedSecurityContext.signals.length ? selectedSecurityContext.signals.slice(0, 3).map((item, index) => (
                    item.kind === 'record' ? (
                      <button
                        key={`context-signal-record-${item.id}`}
                        type="button"
                        onClick={() => {
                          setActiveTab('live')
                          setLiveFocus('app:detections')
                          setSelectedTactical({ kind: item.kind, id: item.id })
                        }}
                        className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-sky-50"
                      >
                        <p className="text-[11px] font-semibold text-slate-900">{item.title}</p>
                        <p className="mt-0.5 text-[10px] text-slate-500">{item.scope}</p>
                      </button>
                    ) : (
                      <div key={`context-signal-${item.id || index}`} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2">
                        <p className="text-[11px] font-semibold text-slate-900">{titleCase(item.type || item.domain || 'signal')}</p>
                        <p className="mt-0.5 text-[10px] text-slate-500">{item.asset_id || item.id || 'live signal'}</p>
                      </div>
                    )
                  )) : <p className="text-[11px] text-slate-500">No linked signals.</p>}
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {activeTab === 'overview' || activeTab === 'assurance' ? (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur-sm">
              <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-slate-900">{activeTab === 'assurance' ? 'Continuous Assurance' : 'Security Overview'}</h2>
                  <p className="text-xs text-slate-500">
                    {activeTab === 'assurance'
                      ? 'Verification checks, control support, and linked operational proof.'
                      : 'One command surface for assessment posture, drift, and improvement actions.'}
                  </p>
                </div>
              </div>

              {activeTab === 'assurance' ? (
              <div className="border-t border-slate-200 px-4 py-3">
                <div className="grid gap-3 xl:grid-cols-[1fr_1.4fr]">
                  <div className="self-start rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Assurance</p>
                        <p className="mt-1 text-sm font-semibold text-slate-900">
                          {selectedAssuranceCheck ? selectedAssuranceCheck.name : 'Verification status'}
                        </p>
                      </div>
                      <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">
                        {verificationSummary.total} checks
                      </span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {[
                        { key: 'all', label: 'All', value: verificationSummary.total, tone: 'bg-slate-100 text-slate-700 border-slate-200' },
                        { key: 'pass', label: 'Pass', value: verificationSummary.pass, tone: verificationStatusTone('pass') },
                        { key: 'degraded', label: 'Degraded', value: verificationSummary.degraded, tone: verificationStatusTone('degraded') },
                        { key: 'fail', label: 'Fail', value: verificationSummary.fail, tone: verificationStatusTone('fail') },
                        { key: 'fresh', label: 'Fresh', value: verificationSummary.fresh, tone: 'bg-sky-100 text-sky-700 border-sky-200' },
                      ].map((item) => (
                        <button
                          key={item.label}
                          type="button"
                          onClick={() => setSelectedAssuranceStatus(item.key)}
                          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium transition ${selectedAssuranceStatus === item.key ? `${item.tone} ring-2 ring-slate-200` : item.tone}`}
                        >
                          {item.label}: {item.value}
                        </button>
                      ))}
                    </div>
                    {selectedAssuranceCheck ? (
                      <div className="mt-3 space-y-3">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${verificationStatusTone(selectedAssuranceCheck.result)}`}>
                            {selectedAssuranceCheck.result}
                          </span>
                          <span className="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-700">
                            {selectedAssuranceCheck.control_id || selectedAssuranceCheck.domain}
                          </span>
                          <span className="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-700">
                            {selectedAssuranceCheck.is_fresh ? 'fresh' : 'stale'}
                          </span>
                        </div>
                        <p className="text-xs leading-6 text-slate-700">{selectedAssuranceCheck.summary}</p>
                        <div className="grid gap-2 md:grid-cols-2">
                          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Observed</p>
                            <div className="mt-2 flex flex-wrap gap-1">
                              {Object.entries(selectedAssuranceCheck.evidence?.observed || {}).map(([key, value]) => (
                                <span key={key} className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">
                                  {titleCase(key)}: {formatEvidenceValue(value)}
                                </span>
                              ))}
                            </div>
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Expected</p>
                            <div className="mt-2 flex flex-wrap gap-1">
                              {Object.entries(selectedAssuranceCheck.evidence?.expected || {}).map(([key, value]) => (
                                <span key={key} className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">
                                  {titleCase(key)}: {formatEvidenceValue(value)}
                                </span>
                              ))}
                            </div>
                          </div>
                        </div>
                        <div className="grid gap-2 md:grid-cols-3">
                          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Live Findings</p>
                              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                                {selectedAssuranceRelatedFindings.length}
                              </span>
                            </div>
                            <div className="mt-2 space-y-2">
                              {selectedAssuranceRelatedFindings.length ? selectedAssuranceRelatedFindings.slice(0, 4).map((item) => (
                                <button
                                  key={`assurance-finding-${item.id}`}
                                  type="button"
                                  onClick={() => openAssuranceFindingInLive(item)}
                                  className="w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-left hover:bg-sky-50"
                                >
                                  <p className="text-[11px] font-semibold text-slate-900">{item.title}</p>
                                  <p className="mt-0.5 text-[10px] text-slate-500">{item.metadata?.asset_name || item.category}</p>
                                </button>
                              )) : (
                                <p className="text-[11px] text-slate-500">No linked live findings.</p>
                              )}
                            </div>
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Recommendations</p>
                              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                                {selectedAssuranceRelatedRecommendations.length}
                              </span>
                            </div>
                            <div className="mt-2 space-y-2">
                              {selectedAssuranceRelatedRecommendations.length ? selectedAssuranceRelatedRecommendations.slice(0, 4).map((item) => (
                                <button
                                  key={`assurance-rec-${item.id}`}
                                  type="button"
                                  onClick={() => openAssuranceRecommendationInLive(item)}
                                  className="w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-left hover:bg-sky-50"
                                >
                                  <p className="text-[11px] font-semibold text-slate-900">{item.title}</p>
                                  <p className="mt-0.5 text-[10px] text-slate-500">{item.domain || 'recommendation'}</p>
                                </button>
                              )) : (
                                <p className="text-[11px] text-slate-500">No linked recommendations.</p>
                              )}
                            </div>
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Signals</p>
                              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                                {selectedAssuranceRelatedSignals.records.length + selectedAssuranceRelatedSignals.signals.length}
                              </span>
                            </div>
                            <div className="mt-2 space-y-2">
                              {selectedAssuranceRelatedSignals.records.length ? selectedAssuranceRelatedSignals.records.slice(0, 4).map((item) => (
                                <button
                                  key={`assurance-signal-record-${item.id}`}
                                  type="button"
                                  onClick={() => {
                                    setLiveFocus('app:detections')
                                    setSelectedTactical({ kind: item.kind, id: item.id })
                                    setActiveTab('live')
                                  }}
                                  className="w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-left hover:bg-sky-50"
                                >
                                  <p className="text-[11px] font-semibold text-slate-900">{item.title}</p>
                                  <p className="mt-0.5 text-[10px] text-slate-500">{item.scope}</p>
                                </button>
                              )) : selectedAssuranceRelatedSignals.signals.length ? selectedAssuranceRelatedSignals.signals.slice(0, 4).map((item) => (
                                <div key={`assurance-signal-${item.id}`} className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2">
                                  <p className="text-[11px] font-semibold text-slate-900">{titleCase(item.type || item.domain || 'signal')}</p>
                                  <p className="mt-0.5 text-[10px] text-slate-500">{item.asset_id || item.domain}</p>
                                </div>
                              )) : (
                                <p className="text-[11px] text-slate-500">No linked signals.</p>
                              )}
                            </div>
                          </div>
                        </div>
                        <p className="text-[10px] uppercase tracking-[0.12em] text-slate-400">
                          Verified {selectedAssuranceCheck.verified_at ? new Date(selectedAssuranceCheck.verified_at).toLocaleString() : 'unknown'}
                          {selectedAssuranceCheck.expires_at ? ` | expires ${new Date(selectedAssuranceCheck.expires_at).toLocaleString()}` : ''}
                        </p>
                      </div>
                    ) : (
                      <p className="mt-3 text-xs text-slate-600">
                        Select a control chip or verification card to inspect the linked live findings, recommendations, and evidence behind it.
                      </p>
                    )}
                  </div>

                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Control Support</p>
                        <p className="mt-1 text-sm font-semibold text-slate-900">Current cATO-relevant capability state</p>
                      </div>
                      <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                        {controlSupport.length} controls
                      </span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {prioritizedControlSupport.map((item) => (
                        <button
                          key={item.control_id}
                          type="button"
                          onClick={() => setSelectedControlId((current) => (current === item.control_id ? 'all' : item.control_id))}
                          className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition ${verificationStatusTone(item.status)} ${selectedControlId === item.control_id ? 'ring-2 ring-slate-200' : ''}`}
                        >
                          <span>{item.control_id}</span>
                          <span>{item.status}</span>
                        </button>
                      ))}
                      {selectedControlId !== 'all' ? (
                        <button
                          type="button"
                          onClick={() => setSelectedControlId('all')}
                          className="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600 hover:bg-slate-50"
                        >
                          Clear control
                        </button>
                      ) : null}
                    </div>
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      {assuranceChecks.length ? assuranceChecks.map((item) => (
                        <button
                          key={item.check_key}
                          type="button"
                          onClick={() => setSelectedVerificationKey(item.check_key)}
                          className={`rounded-lg border px-3 py-2 text-left transition ${selectedAssuranceCheck?.check_key === item.check_key ? 'border-sky-300 bg-sky-50 ring-2 ring-sky-200' : 'border-slate-200 bg-slate-50 hover:bg-white'}`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-xs font-semibold text-slate-900">{item.name}</p>
                            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${verificationStatusTone(item.result)}`}>
                              {item.result}
                            </span>
                          </div>
                          <p className="mt-1 text-[11px] leading-5 text-slate-600">{item.summary}</p>
                          <p className="mt-1 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                            {item.control_id || item.domain} | verified {item.verified_at ? new Date(item.verified_at).toLocaleString() : 'unknown'}
                          </p>
                        </button>
                      )) : (
                        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 md:col-span-2">
                          No verification checks match the current selection.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
              ) : null}

            </div>

            {activeTab === 'assurance' && selectedSecurityContext ? (
              <div className="border-t border-slate-200 bg-slate-50/40 px-4 py-3">
                <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{selectedSecurityContext.label}</p>
                      <div className="mt-1 flex items-center gap-2 flex-wrap">
                        <p className="text-lg font-semibold text-slate-900">{selectedSecurityContext.title}</p>
                        <span className="inline-flex items-center rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-700">
                          {selectedSecurityContext.sourceLabel}
                        </span>
                      </div>
                      <p className="mt-1 max-w-4xl text-sm text-slate-600">{selectedSecurityContext.summary}</p>
                    </div>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">{selectedSecurityContext.findings.length} findings</span>
                      <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">{selectedSecurityContext.recommendations.length} recommendations</span>
                      <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">{selectedSecurityContext.verificationChecks.length} checks</span>
                      <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">{selectedSecurityContext.controls.length} controls</span>
                      <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">{selectedSecurityContext.signals.length} signals</span>
                    </div>
                  </div>
                  <div className="mt-3 grid gap-3 xl:grid-cols-5">
                    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Findings</p>
                        <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">{selectedSecurityContext.findings.length}</span>
                      </div>
                      <div className="mt-2 space-y-2">
                        {selectedSecurityContext.findings.length ? selectedSecurityContext.findings.slice(0, 3).map((item) => (
                          <button
                            key={`context-finding-${item.id}`}
                            type="button"
                            onClick={() => openAssuranceFindingInLive(item)}
                            className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-sky-50"
                          >
                            <p className="text-[11px] font-semibold text-slate-900">{item.title}</p>
                            <p className="mt-0.5 text-[10px] text-slate-500">{item.metadata?.asset_name || item.category || item.source_scope}</p>
                          </button>
                        )) : <p className="text-[11px] text-slate-500">No linked findings.</p>}
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Recommendations</p>
                        <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">{selectedSecurityContext.recommendations.length}</span>
                      </div>
                      <div className="mt-2 space-y-2">
                        {selectedSecurityContext.recommendations.length ? selectedSecurityContext.recommendations.slice(0, 3).map((item) => (
                          <button
                            key={`context-recommendation-${item.id}`}
                            type="button"
                            onClick={() => openAssuranceRecommendationInLive(item)}
                            className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-sky-50"
                          >
                            <p className="text-[11px] font-semibold text-slate-900">{item.title}</p>
                            <p className="mt-0.5 text-[10px] text-slate-500">{item.domain || item.owner_scope || 'recommendation'}</p>
                          </button>
                        )) : <p className="text-[11px] text-slate-500">No linked recommendations.</p>}
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Verification</p>
                        <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">{selectedSecurityContext.verificationChecks.length}</span>
                      </div>
                      <div className="mt-2 space-y-2">
                        {selectedSecurityContext.verificationChecks.length ? selectedSecurityContext.verificationChecks.slice(0, 3).map((item) => (
                          <button
                            key={`context-check-${item.check_key}`}
                            type="button"
                            onClick={() => openVerificationFromLive(item)}
                            className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-sky-50"
                          >
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-[11px] font-semibold text-slate-900">{item.name}</p>
                              <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${verificationStatusTone(item.result)}`}>{item.result}</span>
                            </div>
                            <p className="mt-0.5 text-[10px] text-slate-500">{item.control_id || item.domain || 'verification'}</p>
                          </button>
                        )) : <p className="text-[11px] text-slate-500">No linked checks.</p>}
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Control Support</p>
                        <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">{selectedSecurityContext.controls.length}</span>
                      </div>
                      <div className="mt-2 space-y-2">
                        {selectedSecurityContext.controls.length ? selectedSecurityContext.controls.slice(0, 3).map((item) => (
                          <button
                            key={`context-control-${item.control_id}`}
                            type="button"
                            onClick={() => openControlFromLive(item)}
                            className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-sky-50"
                          >
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-[11px] font-semibold text-slate-900">{item.control_id}</p>
                              <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${item.status === 'pass' ? 'border-emerald-200 bg-emerald-100 text-emerald-700' : item.status === 'degraded' ? 'border-amber-200 bg-amber-100 text-amber-700' : 'border-rose-200 bg-rose-100 text-rose-700'}`}>{item.status}</span>
                            </div>
                            <p className="mt-0.5 text-[10px] text-slate-500">{item.capability || 'cATO-relevant capability'}</p>
                          </button>
                        )) : <p className="text-[11px] text-slate-500">No linked control state.</p>}
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Signals</p>
                        <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">{selectedSecurityContext.signals.length}</span>
                      </div>
                      <div className="mt-2 space-y-2">
                        {selectedSecurityContext.signals.length ? selectedSecurityContext.signals.slice(0, 3).map((item, index) => (
                          item.kind === 'record' ? (
                            <button
                              key={`context-signal-record-${item.id}`}
                              type="button"
                              onClick={() => {
                                setActiveTab('live')
                                setLiveFocus('app:detections')
                                setSelectedTactical({ kind: item.kind, id: item.id })
                              }}
                              className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-sky-50"
                            >
                              <p className="text-[11px] font-semibold text-slate-900">{item.title}</p>
                              <p className="mt-0.5 text-[10px] text-slate-500">{item.scope}</p>
                            </button>
                          ) : (
                            <div key={`context-signal-${item.id || index}`} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2">
                              <p className="text-[11px] font-semibold text-slate-900">{titleCase(item.type || item.domain || 'signal')}</p>
                              <p className="mt-0.5 text-[10px] text-slate-500">{item.asset_id || item.id || 'live signal'}</p>
                            </div>
                          )
                        )) : <p className="text-[11px] text-slate-500">No linked signals.</p>}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : null}

            {activeTab === 'overview' ? (
            <>
            <div className="border-t border-slate-200 px-4 py-2">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="text-lg font-semibold text-slate-900">Action Queue</span>
                  <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-xs font-medium text-slate-600">
                    {overviewActionQueue.length} rows
                  </span>
                  {selectedOverviewQueueItem ? (
                    <span className="min-w-0 max-w-[520px] truncate rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700">
                      {selectedOverviewQueueItem.title}
                    </span>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-900">
                    {secureScore.percentage}% posture
                  </span>
                  <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${trustLevel === 'high' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : trustLevel === 'medium' ? 'border-amber-200 bg-amber-50 text-amber-700' : 'border-rose-200 bg-rose-50 text-rose-700'}`}>
                    Trust {trustLevel}
                  </span>
                  <div className="flex items-center gap-1 rounded-full border border-slate-200 bg-white p-1">
                    {[
                      { key: 'both', label: 'Both' },
                      { key: 'live', label: 'Live' },
                      { key: 'build', label: 'Build' },
                    ].map((option) => (
                      <button
                        key={option.key}
                        type="button"
                        onClick={() => setIncludeSource(option.key)}
                        className={`rounded-full px-2.5 py-1 text-xs font-medium ${includeSource === option.key ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-1 rounded-full border border-slate-200 bg-white p-1">
                    <button
                      type="button"
                      onClick={() => setOverviewGroupBy('source')}
                      className={`rounded-full px-3 py-1 text-xs font-medium ${overviewGroupBy === 'source' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                    >
                      By source
                    </button>
                    <button
                      type="button"
                      onClick={() => setOverviewGroupBy('severity')}
                      className={`rounded-full px-3 py-1 text-xs font-medium ${overviewGroupBy === 'severity' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                    >
                      By severity
                    </button>
                    <button
                      type="button"
                      onClick={() => setOverviewGroupBy('domain')}
                      className={`rounded-full px-3 py-1 text-xs font-medium ${overviewGroupBy === 'domain' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                    >
                      By domain
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setOverviewInspectorTab('summary')
                      setOverviewInspectorOpen(true)
                    }}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Detail
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            </div>

            <div className="border-t border-slate-200 bg-slate-50/60 px-4 py-3">
              <div className="flex gap-2 overflow-x-auto pb-1">
                {overviewLenses.map((lens) => {
                  const selected = selectedLens === lens.key
                  return (
                    <button
                      key={lens.key}
                      type="button"
                      onClick={() => setSelectedLens(lens.key)}
                      className={`min-w-[188px] shrink-0 rounded-full border px-3 py-2 text-left transition ${selected ? OVERVIEW_LENS_SELECTED[lens.key] : lens.tone}`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[10px] font-semibold uppercase tracking-[0.18em]">{lens.label}</span>
                        <span className="text-base font-bold">{lens.count}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px]">
                <div className="flex items-center gap-2 text-slate-700">
                  <span className="font-semibold uppercase tracking-[0.16em] text-slate-500">Focus</span>
                  <span className="font-semibold text-slate-900">{selectedLensMeta?.label}</span>
                  <span className="text-slate-500">{selectedLensMeta?.helper}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold uppercase tracking-[0.16em] text-slate-500">Review</span>
                  {[
                    { label: 'Regressed', value: actionReviewCounts.regressed },
                    { label: 'To address', value: actionReviewCounts.toAddress },
                    { label: 'Planned', value: actionReviewCounts.planned },
                    { label: 'Risk accepted', value: actionReviewCounts.riskAccepted },
                  ].map((item) => (
                    <span key={item.label} className={`inline-flex items-center rounded-full border px-2 py-0.5 font-medium ${reviewStatusTone(item.label)}`}>
                      {item.label}: {item.value}
                    </span>
                  ))}
                </div>
                <div className="flex items-center gap-2 text-slate-700">
                  <span className="font-semibold uppercase tracking-[0.16em] text-slate-500">Live vs build</span>
                  <span>Runtime {liveVsBuild.liveScore}%</span>
                  <span>Build {liveVsBuild.buildScore}%</span>
                  <span className={liveVsBuild.delta < 0 ? 'text-rose-700' : liveVsBuild.delta > 0 ? 'text-emerald-700' : 'text-slate-700'}>
                    Delta {liveVsBuild.delta > 0 ? '+' : ''}{liveVsBuild.delta}%
                  </span>
                  <span>Drift {liveVsBuild.changeCount}</span>
                </div>
                <div className="flex min-w-0 items-center gap-2 text-slate-700">
                  <span className="font-semibold uppercase tracking-[0.16em] text-slate-500">Latest</span>
                  <span className="truncate">{latestChangeHeadline}</span>
                </div>
                <div className="flex min-w-0 flex-wrap items-center gap-2 text-slate-700">
                  <span className="font-semibold uppercase tracking-[0.16em] text-slate-500">Queue</span>
                  <span>{overviewQueueCounts.rows} rows</span>
                  <span className="text-slate-300">|</span>
                  <span>{overviewQueueCounts.recommendations} recommendations</span>
                  <span className="text-slate-300">|</span>
                  <span>{overviewQueueCounts.findings} findings</span>
                  <span className="text-slate-300">|</span>
                  <span>{overviewQueueCounts.changes} change signals</span>
                  <span className="text-slate-300">|</span>
                  <span>{overviewQueueCounts.evidence} evidence items</span>
                </div>
              </div>
            </div>

            <div className="max-h-[calc(100vh-21rem)] overflow-auto" onKeyDown={handleOverviewQueueKeyDown} tabIndex={0}>
              <div className="sticky top-0 z-10 grid grid-cols-[1.9fr_0.6fr_0.7fr_1.2fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 max-[1180px]:grid-cols-1">
                <div>Issue</div>
                <div>Source</div>
                <div>Severity</div>
                <div>Next Step</div>
              </div>

              {groupedOverviewQueue.map((group) => (
                <div key={group.key}>
                  <div className="sticky top-[37px] z-[5] flex items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 py-2 backdrop-blur-sm">
                    <div className="flex items-center gap-2">
                      <group.meta.Icon size={13} className="text-slate-500" />
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${group.meta.tone}`}>
                        {group.meta.label}
                      </span>
                    </div>
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                      {group.items.length}
                    </span>
                  </div>

                  {group.items.map((item) => {
                    const sourceMeta = queueSourceMeta(item.source)
                    const selected = selectedOverviewQueueItem?.key === item.key
                    return (
                      <Fragment key={item.key}>
                        <button
                          type="button"
                          onClick={() => selectOverviewQueueItem(item)}
                          className={`relative grid w-full grid-cols-[1.9fr_0.6fr_0.7fr_1.2fr] gap-3 border-b px-4 py-2.5 text-left max-[1180px]:grid-cols-1 ${selected ? 'border-sky-200 bg-sky-50/50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
                        >
                          <span className={`absolute inset-y-0 left-0 w-1 ${severityRailTone(item.severity)}`} />
                          <div className="min-w-0 pl-2">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {item.score ? (
                                <span className="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-700">
                                  +{item.score} pts
                                </span>
                              ) : null}
                              {item.resourceCount ? (
                                <span className="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-700">
                                  {item.resourceCount} unhealthy
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-1 text-sm font-semibold leading-5 text-slate-900">{item.title}</p>
                            <p className="mt-0.5 text-[11px] text-slate-500">{item.affected}</p>
                          </div>
                          <div className="self-center max-[1180px]:hidden">
                            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${sourceMeta.tone}`}>
                              <sourceMeta.Icon size={11} />
                              {sourceMeta.label}
                            </span>
                          </div>
                          <div className="self-center max-[1180px]:hidden">
                            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${severityTone(item.severity)}`}>
                              <span className={`h-1.5 w-1.5 rounded-full ${severityRailTone(item.severity)}`} />
                              {item.severity}
                            </span>
                          </div>
                          <div className="self-center text-[11px] text-slate-600 max-[1180px]:hidden">
                            {item.nextAction}
                          </div>
                        </button>
                        {selected ? (
                          <div className="border-b border-sky-100 bg-sky-50/40 px-5 py-2.5">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="min-w-0">
                                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Quick Triage</p>
                                <p className="mt-1 text-sm text-slate-700">{item.summary}</p>
                                <p className="mt-1 text-xs text-slate-600">Next step: {item.nextAction}</p>
                              </div>
                              <button
                                type="button"
                                onClick={() => {
                                  setOverviewInspectorTab('summary')
                                  setOverviewInspectorOpen(true)
                                }}
                                className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
                              >
                                Full detail
                                <ChevronRight size={13} />
                              </button>
                            </div>
                          </div>
                        ) : null}
                      </Fragment>
                    )
                  })}
                </div>
              ))}
            </div>
            </>
            ) : null}
          </div>
        ) : null}

        {activeTab === 'overview' ? (
          <div className={`fixed inset-0 z-40 transition ${overviewInspectorOpen ? 'pointer-events-auto' : 'pointer-events-none'}`}>
            <button
              type="button"
              className={`absolute inset-0 bg-slate-950/30 transition-opacity ${overviewInspectorOpen ? 'opacity-100' : 'opacity-0'}`}
              onClick={() => setOverviewInspectorOpen(false)}
            />
            <div className={`absolute inset-y-0 right-0 flex w-full max-w-[480px] transform flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform ${overviewInspectorOpen ? 'translate-x-0' : 'translate-x-full'}`}>
              <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
                <div>
                  <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-700">Selected Issue</h2>
                  <p className="mt-1 text-xs text-slate-500">Overview detail and next action</p>
                </div>
                <button
                  type="button"
                  onClick={() => setOverviewInspectorOpen(false)}
                  className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50"
                >
                  <X size={18} />
                </button>
              </div>
              <div className="border-b border-slate-200 px-5 py-3">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <FilterChip active={overviewInspectorTab === 'summary'} onClick={() => setOverviewInspectorTab('summary')}>Summary</FilterChip>
                  <FilterChip active={overviewInspectorTab === 'fix'} onClick={() => setOverviewInspectorTab('fix')}>Fix</FilterChip>
                  <FilterChip active={overviewInspectorTab === 'verify'} onClick={() => setOverviewInspectorTab('verify')}>Verify</FilterChip>
                  <FilterChip active={overviewInspectorTab === 'evidence'} onClick={() => setOverviewInspectorTab('evidence')}>Evidence</FilterChip>
                  <FilterChip active={overviewInspectorTab === 'history'} onClick={() => setOverviewInspectorTab('history')}>History</FilterChip>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto px-5 py-4">
                {selectedOverviewQueueItem ? (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${queueSourceMeta(selectedOverviewQueueItem.source).tone}`}>
                        {queueSourceMeta(selectedOverviewQueueItem.source).label}
                      </span>
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${severityTone(selectedOverviewQueueItem.severity)}`}>
                        {selectedOverviewQueueItem.severity}
                      </span>
                      {selectedOverviewQueueItem.score ? (
                        <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-700">
                          +{selectedOverviewQueueItem.score} pts
                        </span>
                      ) : null}
                    </div>
                    <div>
                      <p className="text-2xl font-semibold leading-9 text-slate-900">{selectedOverviewQueueItem.title}</p>
                      <p className="mt-1 text-sm text-slate-500">{selectedOverviewQueueItem.affected}</p>
                    </div>
                    {overviewInspectorTab === 'summary' ? (
                      <>
                        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Why It Matters</p>
                          <p className="mt-2 text-sm leading-7 text-slate-700">{selectedOverviewQueueItem.summary}</p>
                        </div>
                        {selectedOverviewQueueItem.resourceCount ? (
                          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
                            {selectedOverviewQueueItem.resourceCount} unhealthy resource(s) are tied to this issue.
                          </div>
                        ) : null}
                        {selectedOverviewSectionGroups.summary.map((section) => (
                          <DetailSection key={section.key} section={section} />
                        ))}
                      </>
                    ) : null}
                    {overviewInspectorTab === 'fix' ? (
                      <>
                        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Next Step</p>
                          <p className="mt-2 text-sm leading-7 text-slate-700">{selectedOverviewQueueItem.nextAction}</p>
                        </div>
                        {selectedOverviewSectionGroups.fix.length ? selectedOverviewSectionGroups.fix.map((section) => (
                          <DetailSection key={section.key} section={section} />
                        )) : (
                          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
                            No structured remediation steps were provided for this issue yet.
                          </div>
                        )}
                      </>
                    ) : null}
                    {overviewInspectorTab === 'verify' ? (
                      <>
                        {selectedOverviewSectionGroups.verify.length ? selectedOverviewSectionGroups.verify.map((section) => (
                          <DetailSection key={section.key} section={section} />
                        )) : (
                          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
                            No verification guidance was provided for this issue yet.
                          </div>
                        )}
                      </>
                    ) : null}
                    {overviewInspectorTab === 'evidence' ? (
                      <>
                        {selectedOverviewSectionGroups.evidence.length ? selectedOverviewSectionGroups.evidence.map((section) => (
                          <DetailSection key={section.key} section={section} />
                        )) : (
                          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
                            No evidence detail is available for this issue yet.
                          </div>
                        )}
                      </>
                    ) : null}
                    {overviewInspectorTab === 'history' ? (
                      <>
                        {selectedOverviewSectionGroups.history.length ? selectedOverviewSectionGroups.history.map((section) => (
                          <DetailSection key={section.key} section={section} />
                        )) : (
                          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
                            No history has been captured for this issue yet.
                          </div>
                        )}
                      </>
                    ) : null}
                    <div className="flex items-center gap-2 flex-wrap">
                      <button
                        type="button"
                        onClick={() => {
                          setActiveTab(selectedOverviewQueueItem.routeTab)
                          setOverviewInspectorOpen(false)
                        }}
                        className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                      >
                        Open {selectedOverviewQueueItem.routeTab}
                        <ChevronRight size={14} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">Select an item from the action queue.</p>
                )}
              </div>
            </div>
          </div>
        ) : null}

        {activeTab === 'live' ? (
          <div className="space-y-2">
            {liveStateError ? (
              <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                Live security telemetry did not load. This page will otherwise fall back to empty defaults.
                Re-authenticate and refresh the page, then try again.
              </div>
            ) : null}
            {!liveState && !liveStateError ? (
              <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                Loading live security telemetry...
              </div>
            ) : null}
            {liveState ? (
              <>
            <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Live Tactical Security</h2>
                  <p className="text-xs text-slate-500">Runtime risk from app-native telemetry, collectors, containers, and host posture.</p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setLiveFocus('all')}
                    className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium ${liveFocus === 'all' ? 'border-slate-900 bg-white text-slate-900 ring-2 ring-slate-200' : 'border-slate-200 bg-slate-50 text-slate-700 hover:bg-white'}`}
                  >
                    All live data
                  </button>
                  {[
                    { key: 'app:all', label: 'App API' },
                    { key: 'app:identity', label: 'Identity' },
                    { key: 'app:configuration', label: 'Configuration' },
                    { key: 'app:jobs', label: 'Jobs' },
                    { key: 'app:data_protection', label: 'Data Protection' },
                    { key: 'app:change_events', label: 'Change Events' },
                    { key: 'app:detections', label: 'Detections' },
                  ].map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => {
                        setLiveFocus(item.key)
                        setSelectedTactical({ kind: 'summary', id: item.key })
                      }}
                      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium ${liveFocus === item.key ? 'border-violet-400 bg-white text-violet-700 ring-2 ring-violet-200' : 'border-slate-200 bg-slate-50 text-slate-700 hover:bg-white'}`}
                    >
                      {item.label}
                    </button>
                  ))}
                  {tacticalCollectors.slice(0, 4).map((collector) => (
                    <button
                      key={collector.id}
                      type="button"
                      onClick={() => {
                        setLiveFocus(`collector:${collector.id}`)
                        setSelectedTactical({ kind: 'collector', id: collector.id })
                      }}
                      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium ${liveFocus === `collector:${collector.id}` ? 'border-sky-400 bg-white text-sky-700 ring-2 ring-sky-200' : 'border-slate-200 bg-slate-50 text-slate-700 hover:bg-white'}`}
                    >
                      {collector.name}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                {[
                  { key: 'collector_count', label: 'Collectors', value: tacticalSummary.collector_count || 0, tone: 'border-slate-200 bg-slate-50 text-slate-700' },
                  { key: 'app:all', label: 'App API', value: appApiSummary.totalFindings || 0, tone: 'border-violet-200 bg-violet-50 text-violet-700' },
                  { key: 'app:detections', label: 'Detections', value: appApiSummary.detections || 0, tone: 'border-rose-200 bg-rose-50 text-rose-700' },
                  { key: 'asset_count', label: 'Assets', value: liveSummary.asset_count || 0, tone: 'border-slate-200 bg-slate-50 text-slate-700' },
                  { key: 'open_findings', label: 'Open', value: liveSummary.open_findings || 0, tone: 'border-rose-200 bg-rose-50 text-rose-700' },
                  { key: 'critical_findings', label: 'Critical', value: liveSummary.critical_findings || 0, tone: 'border-red-200 bg-red-50 text-red-700' },
                  { key: 'high_findings', label: 'High', value: liveSummary.high_findings || 0, tone: 'border-amber-200 bg-amber-50 text-amber-700' },
                ].map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => {
                      setLiveFocus(item.key)
                      setSelectedTactical({ kind: 'summary', id: item.key })
                    }}
                    className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 font-medium ${liveFocus === item.key ? 'border-sky-400 bg-white text-sky-700 ring-2 ring-sky-200' : item.tone}`}
                  >
                    <span className="uppercase tracking-[0.14em] text-[10px]">{item.label}</span>
                    <span className="text-sm font-semibold">{item.value}</span>
                  </button>
                ))}
                <span className="mx-1 text-slate-300">|</span>
                <span className="text-slate-600">
                  {containerSecurity.default_secret_fallbacks?.length
                    ? `Fallback secrets: ${containerSecurity.default_secret_fallbacks.join(', ')}`
                    : 'No default secret fallbacks detected'}
                </span>
                <span className="text-slate-300">|</span>
                <span className="text-slate-600">Runtime services {supporting.runtime_service_summary?.healthy || 0}/{supporting.runtime_service_summary?.total || 0} healthy</span>
              </div>

              <div className="mt-2 grid gap-2 xl:grid-cols-4">
                {appTelemetryCards.map((card) => (
                  <button
                    key={card.key}
                    type="button"
                    onClick={() => {
                      setLiveFocus(card.key)
                      setSelectedTactical({ kind: 'summary', id: card.key })
                    }}
                    className={`rounded-lg border px-3 py-2 text-left transition ${liveFocus === card.key ? 'ring-2 ring-sky-200 border-sky-300 bg-white' : 'hover:bg-white'} ${card.tone}`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[10px] font-semibold uppercase tracking-[0.16em]">{card.label}</span>
                      <span className="text-right">
                        <span className="block text-sm font-semibold">{card.count}</span>
                        <span className="block text-[9px] font-medium uppercase tracking-[0.12em] text-slate-500">{card.countLabel}</span>
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {card.facts.map((fact) => (
                        <span key={`${card.key}-${fact}`} className="inline-flex items-center rounded-full border border-white/80 bg-white/80 px-2 py-0.5 text-[10px] font-medium text-slate-700">
                          {fact}
                        </span>
                      ))}
                    </div>
                  </button>
                ))}
              </div>

              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-2">
                <div className="flex min-w-0 flex-wrap items-center gap-2 text-[11px] text-slate-600">
                  <span className="font-semibold uppercase tracking-[0.16em] text-slate-500">Focus</span>
                  <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 font-medium text-slate-800">{liveFocusMeta.title}</span>
                  {liveScopeCounts.signalCount !== null ? (
                    <>
                      <span>{liveScopeCounts.signalCount} {liveScopeCounts.signalLabel}</span>
                      <span className="text-slate-300">|</span>
                    </>
                  ) : null}
                  <span>{liveScopeCounts.findings} findings</span>
                  <span className="text-slate-300">|</span>
                  <span>{liveScopeCounts.recommendations} recommendations</span>
                  <span className="text-slate-300">|</span>
                  <span>{liveScopeCounts.rows} rows</span>
                  {selectedLiveIssue ? (
                    <>
                      <span className="text-slate-300">|</span>
                      <span className="truncate">Selected: {selectedLiveIssue.title}</span>
                    </>
                  ) : null}
                </div>
                <div className="flex items-center gap-2">
                  <span className="max-w-[420px] truncate text-[11px] text-slate-600">{liveFocusMeta.summary}</span>
                  <button
                    type="button"
                    onClick={() => setInspectorOpen(true)}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-[11px] font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Detail
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            </div>

            <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Live issue queue</span>
                  <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600">
                    {liveIssueRows.length} rows in scope
                  </span>
                </div>
                <div className="grid min-w-[720px] grid-cols-[1.8fr_0.7fr_0.75fr_1.15fr] gap-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 max-[1100px]:hidden">
                  <div>Issue</div>
                  <div>Source</div>
                  <div>Severity</div>
                  <div>Next Step</div>
                </div>
              </div>

              {liveIssueRows.length === 0 ? (
                <div className="px-4 py-10 text-sm text-slate-500">No live issues match the current focus.</div>
              ) : (
                <div className="max-h-[calc(100vh-22rem)] overflow-auto">
                  {liveIssueRows.map((item) => {
                    const sourceMeta = queueSourceMeta(item.source)
                    return (
                      <Fragment key={item.key}>
                        <button
                          type="button"
                          onClick={() => setSelectedTactical({ kind: item.kind, id: item.id })}
                          className={`relative grid w-full grid-cols-[1.8fr_0.7fr_0.75fr_1.15fr] gap-3 border-t px-3 py-2 text-left max-[1100px]:grid-cols-1 ${selectedLiveIssue?.key === item.key ? 'border-sky-200 bg-sky-50/70' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
                        >
                          <span className={`absolute inset-y-0 left-0 w-1 ${severityRailTone(item.severity)}`} />
                          <div className="min-w-0 pl-2">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {item.chips?.slice(0, 2).map((chip) => (
                                <span key={chip.label} className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${chip.tone}`}>
                                  {chip.label}
                                </span>
                              ))}
                              {item.score ? (
                                <span className="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-700">
                                  +{item.score} pts
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-1 text-sm font-semibold leading-5 text-slate-900">{item.title}</p>
                            <p className="mt-0.5 text-[11px] text-slate-500">{item.scope}</p>
                            <p className="mt-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-400">
                              {sourceMeta.label} | {sourceInstanceLabel(item.source)}
                            </p>
                          </div>
                          <div className="self-center max-[1100px]:hidden">
                            <div className="flex min-w-0 flex-col gap-1">
                              <span className={`inline-flex w-fit items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${sourceMeta.tone}`}>
                                <sourceMeta.Icon size={11} />
                                {sourceMeta.label}
                              </span>
                              <span className="truncate text-[10px] text-slate-500">
                                {sourceInstanceLabel(item.source)}
                              </span>
                            </div>
                          </div>
                          <div className="self-center max-[1100px]:hidden">
                            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${severityTone(item.severity)}`}>
                              <span className={`h-1.5 w-1.5 rounded-full ${severityRailTone(item.severity)}`} />
                              {item.severity}
                            </span>
                          </div>
                          <div className="self-center text-[11px] text-slate-600 max-[1100px]:hidden">{item.nextStep}</div>
                        </button>
                        {selectedLiveIssue?.key === item.key ? (
                          <div className="border-t border-sky-100 bg-sky-50/50 px-5 py-2">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="min-w-0">
                                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Quick Triage</p>
                                <p className="mt-1 text-sm text-slate-700">{selectedTacticalDetail?.summary || item.nextStep}</p>
                              </div>
                              <button
                                type="button"
                                onClick={() => setInspectorOpen(true)}
                                className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100"
                              >
                                Full detail
                                <ChevronRight size={13} />
                              </button>
                            </div>
                          </div>
                        ) : null}
                      </Fragment>
                    )
                  })}
                </div>
              )}
            </div>
              </>
            ) : null}
          </div>
        ) : null}

        {activeTab === 'build' ? (
        <div className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 shadow-sm">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Build vs Runtime</h2>
                <p className="text-sm text-slate-500">Compare the latest software-factory snapshot with the current live runtime state.</p>
              </div>
              <div className="text-xs text-slate-500">
              {securityOverview?.summary?.changes_since_build || 0} tracked change signal(s) since the last build
              </div>
            </div>
          <div className="mt-3 grid grid-cols-1 xl:grid-cols-[0.95fr_0.95fr_1.2fr] gap-3">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Latest Build</p>
              {latestBuildSnapshot ? (
                <>
                  <div className="mt-2 flex items-end justify-between gap-3">
                    <div>
                      <p className="text-2xl font-bold text-slate-900">{latestBuildSnapshot.security_score ?? 0}%</p>
                      <p className="text-xs text-slate-500">{latestBuildSnapshot.label}</p>
                    </div>
                    <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700">{latestBuildSnapshot.source}</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">{latestBuildSnapshot.build_date ? new Date(latestBuildSnapshot.build_date).toLocaleString() : 'No date'}</p>
                  <p className="mt-2 text-xs text-slate-600">{latestBuildSnapshot.summary?.finding_count || 0} build finding(s)</p>
                </>
              ) : (
                <p className="mt-2 text-sm text-slate-500">No build snapshot yet.</p>
              )}
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Latest Runtime</p>
              {latestRuntimeSnapshot ? (
                <>
                  <div className="mt-2 flex items-end justify-between gap-3">
                    <div>
                      <p className="text-2xl font-bold text-slate-900">{latestRuntimeSnapshot.security_score ?? 0}%</p>
                      <p className="text-xs text-slate-500">{latestRuntimeSnapshot.source}</p>
                    </div>
                    <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700">runtime</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">{latestRuntimeSnapshot.collected_at ? new Date(latestRuntimeSnapshot.collected_at).toLocaleString() : 'No date'}</p>
                  <p className="mt-2 text-xs text-slate-600">{latestRuntimeSnapshot.summary?.finding_count || 0} runtime finding(s)</p>
                </>
              ) : (
                <p className="mt-2 text-sm text-slate-500">No runtime snapshot yet.</p>
              )}
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Recent Changes</p>
                <span className="text-xs text-slate-500">{recentChanges.length} signals</span>
              </div>
              <div className="mt-2 space-y-2 max-h-44 overflow-auto pr-1">
                {recentChanges.length ? recentChanges.slice(0, 6).map((item) => (
                  <div key={item.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-slate-900">{item.summary}</p>
                      <div className="flex items-center gap-1">
                        <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${item.impact_direction === 'negative' ? 'border-rose-200 bg-rose-50 text-rose-700' : item.impact_direction === 'positive' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-100 text-slate-700'}`}>
                          {item.impact_direction}
                        </span>
                        <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${changeStatusTone(item.change_status)}`}>
                          {(item.change_status || 'observed').replace('_', ' ')}
                        </span>
                      </div>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">{item.details?.setting_label || item.category} | {item.source_snapshot_type}</p>
                  </div>
                )) : (
                  <p className="text-sm text-slate-500">No tracked changes yet.</p>
                )}
              </div>
            </div>
          </div>
        </div>
        ) : null}

        {activeTab === 'build' ? (
          <div className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-slate-900">Build Security Focus</h2>
                <p className="text-xs text-slate-500">Release-time and software supply-chain posture from the latest build lane.</p>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500">
                  {buildFocusedRecommendations.length} recommendation{buildFocusedRecommendations.length === 1 ? '' : 's'}
                </span>
                <button type="button" onClick={() => setActiveTab('live')} className="text-xs font-medium text-sky-700 hover:text-sky-900">
                  Compare with live
                </button>
              </div>
            </div>
            <div className="mt-3 grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-3">
              <div className="rounded-lg border border-slate-200 overflow-hidden">
                <div className="grid grid-cols-[1.7fr_0.6fr_0.5fr] gap-2 bg-slate-50 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  <div>Build Recommendations</div>
                  <div>Severity</div>
                  <div>Score</div>
                </div>
                <div className="divide-y divide-slate-200">
                  {buildFocusedRecommendations.length ? buildFocusedRecommendations.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        setActiveTab('live')
                        setSelectedId(item.id)
                      }}
                      className="grid w-full grid-cols-[1.7fr_0.6fr_0.5fr] gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50"
                    >
                      <div>
                        <p className="font-medium leading-5 text-slate-900">{item.title}</p>
                        <p className="text-[11px] text-slate-500">{item.domain}</p>
                      </div>
                      <div className="self-center">
                        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${severityTone(recommendationPriority(item))}`}>
                          {recommendationPriority(item)}
                        </span>
                      </div>
                      <div className="self-center text-sm font-semibold text-slate-900">+{item.potential_points}</div>
                    </button>
                  )) : (
                    <div className="px-3 py-8 text-sm text-slate-500">No build-focused recommendations available yet.</div>
                  )}
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Build Snapshot Detail</p>
                {latestBuildSnapshot ? (
                  <div className="mt-2 space-y-2 text-sm text-slate-700">
                    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                      <p className="font-semibold text-slate-900">{latestBuildSnapshot.label}</p>
                      <p className="text-[11px] text-slate-500">{latestBuildSnapshot.source} | {latestBuildSnapshot.build_date ? new Date(latestBuildSnapshot.build_date).toLocaleString() : 'No date'}</p>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Build Findings</p>
                      <p className="mt-1 text-lg font-bold text-slate-900">{liveVsBuild.buildFindings}</p>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Drift Against Runtime</p>
                      <p className="mt-1 text-lg font-bold text-slate-900">{liveVsBuild.changeCount}</p>
                    </div>
                  </div>
                ) : (
                  <p className="mt-2 text-sm text-slate-500">No build snapshot is available yet.</p>
                )}
              </div>
            </div>
          </div>
        ) : null}

        {activeTab === 'changes' ? (
          <div className="grid grid-cols-1 xl:grid-cols-[0.8fr_1.2fr] gap-3">
            <div className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 shadow-sm">
              <h2 className="text-base font-semibold text-slate-900">Change Summary</h2>
              <p className="mt-1 text-xs text-slate-500">{recentChanges.length} tracked change signal(s) are currently represented.</p>
              <div className="mt-3 grid grid-cols-3 gap-2">
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-700">Positive Signals</p>
                  <p className="mt-1 text-2xl font-bold text-emerald-800">{changeSummary.positive}</p>
                </div>
                <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-rose-700">Negative Signals</p>
                  <p className="mt-1 text-2xl font-bold text-rose-800">{changeSummary.negative}</p>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Neutral Signals</p>
                  <p className="mt-1 text-2xl font-bold text-slate-900">{changeSummary.neutral}</p>
                </div>
              </div>
              <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                {liveVsBuild.changeCount} tracked change(s) were detected between the latest build and runtime snapshots.
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-slate-900">Recent Change Feed</h2>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-500">{recentChanges.length} signals</span>
                  <button type="button" onClick={() => setActiveTab('build')} className="text-xs font-medium text-sky-700 hover:text-sky-900">
                    View build context
                  </button>
                </div>
              </div>
              <div className="mt-3 space-y-2">
                {recentChanges.length ? recentChanges.map((item) => (
                  <div key={item.id} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-900">{item.summary}</p>
                      <div className="flex items-center gap-1">
                        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${item.impact_direction === 'negative' ? 'border-rose-200 bg-rose-50 text-rose-700' : item.impact_direction === 'positive' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-100 text-slate-700'}`}>
                          {item.impact_direction}
                        </span>
                        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${changeStatusTone(item.change_status)}`}>
                          {(item.change_status || 'observed').replace('_', ' ')}
                        </span>
                      </div>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500">{item.details?.setting_label || item.category} | {item.source_snapshot_type}</p>
                  </div>
                )) : (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-8 text-sm text-slate-500">No tracked changes yet.</div>
                )}
              </div>
            </div>
          </div>
        ) : null}

        {activeTab === 'evidence' ? (
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_1fr] gap-3">
            <div className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-slate-900">Security Signals</h2>
                <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${trustLevel === 'high' ? 'bg-emerald-100 text-emerald-700 border-emerald-200' : trustLevel === 'medium' ? 'bg-amber-100 text-amber-700 border-amber-200' : 'bg-rose-100 text-rose-700 border-rose-200'}`}>
                  trust {trustLevel}
                </span>
              </div>
              <div className="mt-3 space-y-2">
                {assertions.map((item) => (
                  <div key={item.label} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-900">{item.label}</p>
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${item.status === 'healthy' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-700 border-amber-200'}`}>
                        {item.status}
                      </span>
                    </div>
                    <div className="mt-1 flex items-baseline gap-2">
                      <p className="text-lg font-bold text-slate-900">{item.value}</p>
                      <p className="text-[11px] text-slate-500">{item.hint}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 shadow-sm">
              <h2 className="text-base font-semibold text-slate-900">Implementation Evidence</h2>
              <div className="mt-3 space-y-2">
                {attestations.map((item) => (
                  <div key={item.id} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className={`h-2.5 w-2.5 rounded-full ${item.healthy ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                      <p className="text-sm font-semibold text-slate-900">{item.label}</p>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500">{item.controls.join(' | ')}</p>
                  </div>
                ))}
              </div>
              <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                Runtime services: {supporting.runtime_service_summary?.healthy || 0}/{supporting.runtime_service_summary?.total || 0} healthy | Latest assessment: {supporting.latest_assessment?.status || 'none'}
              </div>
            </div>
          </div>
        ) : null}

        {activeTab === 'live' ? (
        <div className={`fixed inset-0 z-40 transition ${inspectorOpen ? 'pointer-events-auto' : 'pointer-events-none'}`}>
          <div
            className={`absolute inset-0 bg-slate-950/30 transition-opacity ${inspectorOpen ? 'opacity-100' : 'opacity-0'}`}
            onClick={() => setInspectorOpen(false)}
          />
          <div className={`absolute inset-y-0 right-0 flex w-full max-w-[480px] transform flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform ${inspectorOpen ? 'translate-x-0' : 'translate-x-full'}`}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-3 py-2">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-700">Inspector</h2>
                <span className="text-[11px] text-slate-500">{selectedTacticalDetail ? selectedTacticalDetail.subtitle : 'live detail'}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setInspectorOpen(false)}
                  className="inline-flex items-center justify-center rounded-lg border border-slate-300 bg-white p-1.5 text-slate-600 hover:bg-slate-100"
                >
                  <X size={15} />
                </button>
              </div>
            </div>

            <div className="border-b border-slate-200 px-3 py-2">
              <div className="flex items-center gap-1.5 flex-wrap">
                <FilterChip active={inspectorTab === 'summary'} onClick={() => setInspectorTab('summary')}>Summary</FilterChip>
                <FilterChip active={inspectorTab === 'fix'} onClick={() => setInspectorTab('fix')}>Fix</FilterChip>
                <FilterChip active={inspectorTab === 'verify'} onClick={() => setInspectorTab('verify')}>Verify</FilterChip>
                <FilterChip active={inspectorTab === 'evidence'} onClick={() => setInspectorTab('evidence')}>Evidence</FilterChip>
                <FilterChip active={inspectorTab === 'history'} onClick={() => setInspectorTab('history')}>History</FilterChip>
              </div>
            </div>

            <div className="flex-1 overflow-auto p-3">
              {inspectorTab === 'summary' ? (
                selectedTacticalDetail ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      {selectedTacticalDetail?.sourceLabel ? (
                        <span className="inline-flex items-center rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-700">
                          {selectedTacticalDetail.sourceLabel}
                        </span>
                      ) : null}
                      {selectedTacticalDetail.status ? (
                        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${selectedTacticalDetail.status === 'healthy' || selectedTacticalDetail.status === 'completed' ? 'bg-emerald-100 text-emerald-700 border-emerald-200' : selectedTacticalDetail.status === 'open' || selectedTacticalDetail.status === 'attention' ? 'bg-rose-100 text-rose-700 border-rose-200' : 'bg-slate-100 text-slate-700 border-slate-200'}`}>{selectedTacticalDetail.status}</span>
                      ) : null}
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${severityTone(selectedTacticalDetail.severity)}`}>{selectedTacticalDetail.severity}</span>
                    </div>
                    <div>
                      <p className="text-base font-semibold leading-6 text-slate-900">{selectedTacticalDetail.title}</p>
                      <p className="mt-1 text-[11px] text-slate-500">{selectedTacticalDetail.subtitle}</p>
                    </div>
                    {selectedTacticalDetail.summary ? (
                      <p className="text-sm leading-6 text-slate-600">{selectedTacticalDetail.summary}</p>
                    ) : null}
                    {selectedTacticalDetail.sourceSummary ? (
                      <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Telemetry Source</p>
                        <p className="mt-1 text-sm leading-6 text-slate-700">{selectedTacticalDetail.sourceSummary}</p>
                      </div>
                    ) : null}
                    {selectedTacticalDetail.chips?.length ? (
                      <div className="flex items-center gap-2 flex-wrap">
                        {selectedTacticalDetail.chips.map((chip) => (
                          <span key={chip.label} className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${chip.tone}`}>
                            {chip.label}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {(selectedTacticalRelatedVerificationChecks.length || selectedTacticalRelatedControls.length) ? (
                      <div className="grid gap-3 md:grid-cols-2">
                        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Verification Checks</p>
                            <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                              {selectedTacticalRelatedVerificationChecks.length}
                            </span>
                          </div>
                          <div className="mt-2 space-y-2">
                            {selectedTacticalRelatedVerificationChecks.length ? selectedTacticalRelatedVerificationChecks.slice(0, 4).map((item) => (
                              <button
                                key={`live-check-${item.check_key}`}
                                type="button"
                                onClick={() => openVerificationFromLive(item)}
                                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-left hover:bg-sky-50"
                              >
                                <div className="flex items-start justify-between gap-2">
                                  <p className="text-[11px] font-semibold text-slate-900">{item.name}</p>
                                  <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${item.result === 'pass' ? 'border-emerald-200 bg-emerald-100 text-emerald-700' : item.result === 'degraded' ? 'border-amber-200 bg-amber-100 text-amber-700' : 'border-rose-200 bg-rose-100 text-rose-700'}`}>
                                    {item.result}
                                  </span>
                                </div>
                                <p className="mt-0.5 text-[10px] text-slate-500">{item.control_id || item.domain || 'verification'}</p>
                              </button>
                            )) : (
                              <p className="text-[11px] text-slate-500">No linked verification checks.</p>
                            )}
                          </div>
                        </div>
                        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Control Support</p>
                            <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                              {selectedTacticalRelatedControls.length}
                            </span>
                          </div>
                          <div className="mt-2 space-y-2">
                            {selectedTacticalRelatedControls.length ? selectedTacticalRelatedControls.slice(0, 4).map((item) => (
                              <button
                                key={`live-control-${item.control_id}`}
                                type="button"
                                onClick={() => openControlFromLive(item)}
                                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-left hover:bg-sky-50"
                              >
                                <div className="flex items-start justify-between gap-2">
                                  <p className="text-[11px] font-semibold text-slate-900">{item.control_id}</p>
                                  <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${item.status === 'pass' ? 'border-emerald-200 bg-emerald-100 text-emerald-700' : item.status === 'degraded' ? 'border-amber-200 bg-amber-100 text-amber-700' : 'border-rose-200 bg-rose-100 text-rose-700'}`}>
                                    {item.status}
                                  </span>
                                </div>
                                <p className="mt-0.5 text-[10px] text-slate-500">{item.capability || 'cATO-relevant capability'}</p>
                              </button>
                            )) : (
                              <p className="text-[11px] text-slate-500">No linked control support state.</p>
                            )}
                          </div>
                        </div>
                      </div>
                    ) : null}
                    {selectedTacticalSectionGroups.summary.map((section) => (
                      <DetailSection key={section.key} section={section} />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">Select a live issue from the table.</p>
                )
              ) : null}

              {inspectorTab === 'fix' ? (
                <div className="space-y-3">
                  {selectedTacticalDetail?.action ? (
                    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Recommended Action</p>
                      <p className="mt-1 text-sm leading-6 text-slate-700">{selectedTacticalDetail.action}</p>
                    </div>
                  ) : null}
                  {selectedTacticalSectionGroups.fix.length ? selectedTacticalSectionGroups.fix.map((section) => (
                    <DetailSection key={section.key} section={section} />
                  )) : (
                    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600">
                      No structured remediation steps are available for this issue yet.
                    </div>
                  )}
                </div>
              ) : null}

              {inspectorTab === 'verify' ? (
                <div className="space-y-3">
                  {selectedTacticalSectionGroups.verify.length ? selectedTacticalSectionGroups.verify.map((section) => (
                    <DetailSection key={section.key} section={section} />
                  )) : (
                    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600">
                      No verification guidance is available for this issue yet.
                    </div>
                  )}
                </div>
              ) : null}

              {inspectorTab === 'evidence' ? (
                <div className="space-y-3">
                  {selectedTacticalSectionGroups.evidence.map((section) => (
                    <DetailSection key={section.key} section={section} />
                  ))}
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Signals</p>
                    <div className="mt-2 space-y-2">
                      {assertions.map((item) => (
                        <div key={item.label} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-slate-900">{item.label}</p>
                            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${item.status === 'healthy' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-700 border-amber-200'}`}>{item.status}</span>
                          </div>
                          <div className="mt-1 flex items-baseline gap-2">
                            <p className="text-lg font-bold text-slate-900">{item.value}</p>
                            <p className="text-[11px] text-slate-500 truncate">{item.hint}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Implementation Evidence</p>
                    <div className="mt-2 space-y-2">
                      {attestations.map((item) => (
                        <div key={item.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                          <div className="flex items-center gap-2">
                            <span className={`h-2.5 w-2.5 rounded-full ${item.healthy ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                            <p className="text-sm font-semibold text-slate-900">{item.label}</p>
                          </div>
                          <p className="mt-1 text-[11px] text-slate-500">{item.controls.join(' | ')}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}

              {inspectorTab === 'history' ? (
                <div className="space-y-3">
                  {selectedTacticalSectionGroups.history.length ? selectedTacticalSectionGroups.history.map((section) => (
                    <DetailSection key={section.key} section={section} />
                  )) : (
                    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600">
                      No history has been recorded for this issue yet.
                    </div>
                  )}
                </div>
              ) : null}

              <div className="mt-3 border-t border-slate-200 pt-3">
                <button type="button" onClick={() => setShowOps((current) => !current)} className="flex w-full items-center justify-between gap-3 text-left">
                  <div className="flex items-center gap-2"><Server size={15} className="text-slate-700" /><span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-700">Operational Context</span></div>
                  <span className="text-[11px] text-slate-500">{showOps ? 'Hide' : 'Show'}</span>
                </button>
                {showOps ? (
                  <div className="mt-2 space-y-2 text-sm text-slate-600">
                    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">Runtime services: {supporting.runtime_service_summary?.healthy || 0}/{supporting.runtime_service_summary?.total || 0}</div>
                    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">Docker: {supporting.docker_runtime?.available ? 'visible' : (supporting.docker_runtime?.detail || 'best-effort only')}</div>
                    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">Latest assessment: {supporting.latest_assessment?.status || 'none'}</div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
        ) : null}
      </div>
    </div>
  )
}

