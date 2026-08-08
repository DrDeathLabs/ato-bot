/**
 * PipelineStageIndicator — shows 5-pip progress for the ingestion pipeline stages.
 * Used on any page where documents can be in "processing" state.
 *
 * Props:
 *   progress  — object from /processing-progress endpoint for this doc, or null
 */
const STAGES = ['parse', 'screen', 'expand', 'classify', 'embed']
const STAGE_LABELS = {
  parse:    'Parsing',
  screen:   'Screening',
  expand:   'Expanding',
  classify: 'Classifying',
  embed:    'Embedding',
}

export default function PipelineStageIndicator({ progress }) {
  const activeStage = progress?.stage || 'parse'
  const label = STAGE_LABELS[activeStage] || 'Processing'
  const detail = progress?.evidence_units > 0 && ['classify', 'embed'].includes(activeStage)
    ? ` · ${progress.evidence_units}U`
    : progress?.lines_parsed > 0 && activeStage === 'screen'
    ? ` · ${progress.lines_parsed}L`
    : ''

  return (
    <div className="flex items-center gap-1.5 flex-shrink-0">
      <div className="flex items-center gap-0.5">
        {STAGES.map(s => {
          const stageKey = `stage_${s}`
          const stageStatus = progress?.[stageKey]
          const isComplete = stageStatus === 'complete' || stageStatus === 'skipped'
          const isActive   = progress?.stage === s && stageStatus === 'running'
          return (
            <div
              key={s}
              title={STAGE_LABELS[s]}
              className={`w-2 h-2 rounded-full transition-all ${
                isComplete ? 'bg-yellow-500' :
                isActive   ? 'bg-yellow-400 animate-pulse ring-2 ring-yellow-300' :
                             'bg-gray-200'
              }`}
            />
          )
        })}
      </div>
      <span className="text-xs font-medium text-yellow-600 tabular-nums">
        {label}{detail}
      </span>
    </div>
  )
}
