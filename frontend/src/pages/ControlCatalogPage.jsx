import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, Filter, MessageSquare, Search } from 'lucide-react'
import api from '../api/client'
import { ControlReferenceButton } from '../components/ControlReference'
import { openCyberAssistant } from '../components/cyberAssistant'

export default function ControlCatalogPage() {
  const [search, setSearch] = useState('')
  const [family, setFamily] = useState('')
  const [baseline, setBaseline] = useState('')
  const [includeEnhancements, setIncludeEnhancements] = useState(true)

  const queryParams = useMemo(() => ({
    ...(search.trim() ? { q: search.trim() } : {}),
    ...(family ? { family } : {}),
    ...(baseline ? { baseline } : {}),
    include_enhancements: includeEnhancements,
    limit: 250,
    offset: 0,
  }), [search, family, baseline, includeEnhancements])

  const { data: familyData } = useQuery({
    queryKey: ['control-families'],
    queryFn: () => api.get('/control-catalog/families').then((response) => response.data),
    staleTime: 10 * 60 * 1000,
  })

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['control-catalog', queryParams],
    queryFn: () => api.get('/control-catalog/controls', { params: queryParams }).then((response) => response.data),
    staleTime: 60 * 1000,
  })

  const items = data?.items || []

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <div className="flex items-center gap-2 text-blue-700 mb-2">
              <BookOpen size={18} />
              <span className="text-xs font-semibold uppercase tracking-wide">Reference Library</span>
            </div>
            <h1 className="text-2xl font-bold text-gray-900">NIST SP 800-53 Rev. 5 Catalog</h1>
            <p className="text-sm text-gray-500 mt-1">
              Search controls, enhancements, statements, and assessment criteria. Any result can be opened in the shared reference drawer.
            </p>
          </div>
          <div className="text-right text-sm text-gray-500">
            <div>{data?.total || 0} results</div>
            <div className="text-xs">Assessment criteria come from 800-53A where available</div>
            <button
              type="button"
              onClick={() => openCyberAssistant({
                mode: 'general',
                title: '800-53 Reference Assistant',
                attachments: [{
                  type: 'general',
                  resource_id: 'general',
                  context_json: { label: '800-53 Reference Workspace' },
                }],
                initialPrompt: 'Help me use the 800-53 reference catalog and explain controls in plain English.',
                hiddenInitialMessage: true,
              })}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-xs font-medium text-violet-700 hover:bg-violet-100 transition-colors"
            >
              <MessageSquare size={13} />
              Ask AI
            </button>
          </div>
        </div>

        <div className="bg-white border border-gray-200 rounded-2xl p-4 mb-6">
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
            <div className="lg:col-span-2">
              <label className="text-xs text-gray-500 block mb-1">Search</label>
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="AC-2, account management, objective text, guidance..."
                  className="w-full border border-gray-200 rounded-xl pl-9 pr-3 py-2 text-sm"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Family</label>
              <select
                value={family}
                onChange={(event) => setFamily(event.target.value)}
                className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm bg-white"
              >
                <option value="">All families</option>
                {(familyData?.families || []).map((item) => (
                  <option key={item.id} value={item.id}>{item.id} - {item.title}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Baseline</label>
              <select
                value={baseline}
                onChange={(event) => setBaseline(event.target.value)}
                className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm bg-white"
              >
                <option value="">All baselines</option>
                <option value="low">Low</option>
                <option value="moderate">Moderate</option>
                <option value="high">High</option>
              </select>
            </div>
          </div>

          <div className="flex items-center justify-between mt-3">
            <label className="inline-flex items-center gap-2 text-sm text-gray-600">
              <input
                type="checkbox"
                checked={includeEnhancements}
                onChange={(event) => setIncludeEnhancements(event.target.checked)}
                className="rounded border-gray-300"
              />
              Include enhancements
            </label>
            <button
              type="button"
              onClick={() => {
                setSearch('')
                setFamily('')
                setBaseline('')
                setIncludeEnhancements(true)
              }}
              className="inline-flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-800"
            >
              <Filter size={14} />
              Reset filters
            </button>
          </div>
        </div>

        <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
          <div className="grid grid-cols-[140px_120px_minmax(0,1fr)_180px_240px] gap-3 px-5 py-3 bg-gray-50 border-b border-gray-200 text-xs font-semibold uppercase tracking-wide text-gray-500">
            <div>Control</div>
            <div>Family</div>
            <div>Title</div>
            <div>Criteria</div>
            <div>Reference / Chat</div>
          </div>

          {isLoading && <div className="px-5 py-10 text-center text-sm text-gray-400">Loading control catalog...</div>}

          {isError && (
            <div className="px-5 py-10 text-center text-sm text-red-600">
              Failed to load catalog: {error?.response?.data?.detail || error?.message || 'Unknown error'}
            </div>
          )}

          {!isLoading && !isError && items.length === 0 && (
            <div className="px-5 py-10 text-center text-sm text-gray-400">
              No controls matched your current filters.
            </div>
          )}

          {!isLoading && !isError && items.map((item) => (
            <div key={item.id} className="grid grid-cols-[140px_120px_minmax(0,1fr)_180px_240px] gap-3 px-5 py-3 border-t border-gray-100 items-center">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-bold text-blue-700">{item.id}</span>
                  {item.is_enhancement && (
                    <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200">
                      Enh
                    </span>
                  )}
                </div>
              </div>
              <div className="text-sm text-gray-600">{item.family_id}</div>
              <div className="min-w-0">
                <div className="text-sm text-gray-900 truncate">{item.title}</div>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {(item.baselines || []).map((tag) => (
                    <span key={tag} className="inline-flex items-center rounded-full bg-gray-50 border border-gray-200 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
              <div className="text-sm text-gray-600">
                {item.assessment_objective_count} objectives
                <div className="text-xs text-gray-400 mt-0.5">
                  {item.assessment_criteria_source === '800-53A' ? '800-53A' :
                    item.assessment_criteria_source === 'derived_from_statement' ? 'Derived' :
                      'Unavailable'}
                </div>
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <ControlReferenceButton controlId={item.id} label="Open reference" />
                  <button
                    type="button"
                    onClick={() => openCyberAssistant({
                      mode: 'control',
                      title: `${item.id} Assistant`,
                      attachments: [{
                        type: 'control',
                        resource_id: item.id,
                        context_json: {
                          control_id: item.id,
                          label: `Control: ${item.id}`,
                        },
                      }],
                    })}
                    className="inline-flex items-center gap-1 rounded-md border border-violet-200 bg-violet-50 px-2 py-1 text-xs font-medium text-violet-700 hover:bg-violet-100 transition-colors"
                  >
                    <MessageSquare size={12} />
                    Ask AI
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
