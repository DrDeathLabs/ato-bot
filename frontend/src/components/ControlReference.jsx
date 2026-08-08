import { createContext, useContext, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, ExternalLink, Loader2, MessageSquare, Scale, X } from 'lucide-react'
import api from '../api/client'
import { openCyberAssistant } from './cyberAssistant'

const ControlReferenceContext = createContext(null)

export function ControlReferenceProvider({ children }) {
  const [activeControlId, setActiveControlId] = useState(null)

  const value = useMemo(() => ({
    openControl: (controlId) => setActiveControlId(controlId),
    closeControl: () => setActiveControlId(null),
  }), [])

  return (
    <ControlReferenceContext.Provider value={value}>
      {children}
      <ControlReferenceDrawer controlId={activeControlId} onClose={() => setActiveControlId(null)} />
    </ControlReferenceContext.Provider>
  )
}

export function useControlReference() {
  const ctx = useContext(ControlReferenceContext)
  if (!ctx) throw new Error('useControlReference must be used inside ControlReferenceProvider')
  return ctx
}

export function ControlReferenceButton({
  controlId,
  label,
  title,
  iconOnly = false,
  className = '',
  stopPropagation = true,
}) {
  const { openControl } = useControlReference()

  const handleClick = (event) => {
    if (stopPropagation) {
      event.preventDefault()
      event.stopPropagation()
    }
    openControl(controlId)
  }

  const buttonTitle = title || `Open NIST SP 800-53 reference for ${controlId}`

  return (
    <button
      type="button"
      onClick={handleClick}
      title={buttonTitle}
      className={iconOnly
        ? `inline-flex items-center justify-center rounded-md border border-blue-200 bg-blue-50 p-1 text-blue-700 hover:bg-blue-100 transition-colors ${className}`
        : `inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors ${className}`
      }
    >
      <BookOpen size={iconOnly ? 12 : 13} />
      {!iconOnly && <span>{label || controlId}</span>}
    </button>
  )
}

function DrawerSection({ title, children }) {
  return (
    <section className="border border-gray-200 rounded-xl bg-white overflow-hidden">
      <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</h3>
      </div>
      <div className="px-4 py-3">{children}</div>
    </section>
  )
}

function ControlReferenceDrawer({ controlId, onClose }) {
  const { openControl } = useControlReference()
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['control-reference', controlId],
    queryFn: () => api.get(`/control-catalog/controls/${encodeURIComponent(controlId)}`).then((response) => response.data),
    enabled: !!controlId,
    staleTime: 5 * 60 * 1000,
  })

  if (!controlId) return null

  return (
    <div className="fixed inset-0 z-[10000] flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div
        className="relative h-full w-full max-w-3xl bg-gray-50 shadow-2xl flex flex-col"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-gray-200 bg-white">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-blue-700 mb-1">
              <Scale size={16} />
              <span className="text-xs font-semibold uppercase tracking-wide">NIST SP 800-53 Rev. 5 Reference</span>
            </div>
            <h2 className="text-lg font-bold text-gray-900 truncate">{controlId}</h2>
            <p className="text-sm text-gray-500 truncate">
              {data?.title || 'Loading control details...'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => openCyberAssistant({
                mode: 'control',
                title: `${controlId} Assistant`,
                attachments: [{
                  type: 'control',
                  resource_id: controlId,
                  context_json: {
                    control_id: controlId,
                    label: `Control: ${controlId}`,
                  },
                }],
              })}
              className="inline-flex items-center gap-1.5 rounded-lg border border-violet-200 bg-violet-50 px-3 py-1.5 text-xs font-medium text-violet-700 hover:bg-violet-100 transition-colors"
            >
              <MessageSquare size={13} />
              Ask AI
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {isLoading && (
            <div className="h-full flex items-center justify-center text-gray-500 gap-2">
              <Loader2 size={18} className="animate-spin" />
              Loading control reference...
            </div>
          )}

          {isError && (
            <div className="border border-red-200 bg-red-50 text-red-700 rounded-xl px-4 py-3 text-sm">
              Failed to load control reference: {error?.response?.data?.detail || error?.message || 'Unknown error'}
            </div>
          )}

          {data && (
            <>
              <DrawerSection title="Overview">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Family</p>
                    <p className="font-medium text-gray-900">{data.family_id} — {data.family_title}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Baselines</p>
                    <div className="flex flex-wrap gap-1.5">
                      {(data.baselines || []).length > 0 ? (
                        data.baselines.map((baseline) => (
                          <span key={baseline} className="inline-flex items-center rounded-full bg-indigo-50 border border-indigo-200 px-2 py-0.5 text-xs font-medium text-indigo-700">
                            {baseline}
                          </span>
                        ))
                      ) : (
                        <span className="text-gray-500">Not mapped to low/moderate/high baseline metadata</span>
                      )}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Catalog ID</p>
                    <p className="font-mono text-gray-800">{data.catalog_id}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Assessment Criteria Source</p>
                    <p className="text-gray-800">
                      {data.assessment_criteria_source === '800-53A' ? 'Published 800-53A objectives' :
                        data.assessment_criteria_source === 'derived_from_statement' ? 'Derived from control statement' :
                          data.assessment_criteria_source === 'not_assessable' ? 'Not assessed independently' :
                            'No criteria available'}
                    </p>
                  </div>
                  {!data.assessable && (
                    <div className="md:col-span-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">System Disposition</p>
                      <p className="text-sm text-slate-700">
                        Withdrawn by NIST and not user-assessable.
                        {(data.incorporated_into || []).length > 0 && (
                          <>
                            {' '}Assessment coverage is handled under{' '}
                            {data.incorporated_into.map((target, index) => (
                              <button
                                key={target}
                                type="button"
                                onClick={() => openControl(target)}
                                className="font-semibold text-blue-700 hover:text-blue-900"
                              >
                                {target}{index < data.incorporated_into.length - 1 ? ', ' : ''}
                              </button>
                            ))}
                            .
                          </>
                        )}
                      </p>
                    </div>
                  )}
                  {data.parent && (
                    <div className="md:col-span-2">
                      <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Parent Control</p>
                      <button
                        type="button"
                        onClick={() => openControl(data.parent.id)}
                        className="inline-flex items-center gap-1 text-blue-700 hover:text-blue-900 text-sm font-medium"
                      >
                        {data.parent.id} — {data.parent.title}
                        <ExternalLink size={13} />
                      </button>
                    </div>
                  )}
                </div>
              </DrawerSection>

              <DrawerSection title="Control Statement">
                <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
                  {data.statement || 'No statement text available.'}
                </p>
              </DrawerSection>

              <DrawerSection title="Assessment Criteria">
                {(data.assessment_criteria || []).length > 0 ? (
                  <div className="space-y-2">
                    {data.assessment_criteria.map((criterion, index) => (
                      <div key={`${data.id}-${index}`} className="flex gap-3 text-sm">
                        <span className="text-gray-400 font-mono text-xs pt-0.5">{String(index + 1).padStart(2, '0')}</span>
                        <p className="text-gray-800 leading-relaxed">{criterion}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">No assessment criteria are available for this control.</p>
                )}
              </DrawerSection>

              <DrawerSection title="Supplemental Guidance">
                <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
                  {data.supplemental_guidance || 'No supplemental guidance text available.'}
                </p>
              </DrawerSection>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
