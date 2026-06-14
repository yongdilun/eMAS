import { isReplenishRecommendation } from '../../../services/normalizers'

const RecommendationCard = ({
    recommendation,
    value,
    onToggleSelected,
    onFieldChange,
    onFocusShortage,
}) => {
    const rec = recommendation || {}
    const selected = value?.selected !== false
    const canEditApplyFields =
        selected && isReplenishRecommendation(rec)

    return (
        <div className="rounded-lg border border-hairline bg-surface-1 p-3 space-y-2 hover:bg-surface-2 transition-colors">
            <div className="flex items-start justify-between gap-2">
                <div>
                    <p className="text-sm font-semibold text-ink">
                        {rec.entity_id || 'Unknown'}
                    </p>
                    <p className="text-xs text-amber-700 dark:text-amber-300">
                        {rec.option_type || 'unknown'} · source: {rec.source || 'unknown'}
                        {rec.dependency_product_id ? ` · for subproduct ${rec.dependency_product_id}` : ''}
                    </p>
                </div>
                <label className="inline-flex items-center gap-1.5 text-[11px] font-medium text-ink-subtle">
                    <input
                        type="checkbox"
                        checked={selected}
                        onChange={(e) => onToggleSelected?.(e.target.checked)}
                        className="h-3.5 w-3.5 rounded border-hairline text-primary focus:ring-primary"
                    />
                    Include
                </label>
            </div>

            <div className="grid grid-cols-2 gap-2">
                <label className="text-xs text-ink-subtle">
                    Qty
                    <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={value?.qty ?? ''}
                        onChange={(e) => onFieldChange?.('qty', e.target.value)}
                        className="mt-1 w-full h-8 rounded-md border border-hairline bg-surface-1 px-2 text-xs"
                        disabled={!selected || !canEditApplyFields}
                    />
                </label>
                <label className="text-xs text-ink-subtle">
                    Arrive at
                    <input
                        type="datetime-local"
                        value={value?.arriveAtLocal ?? ''}
                        onChange={(e) => onFieldChange?.('arriveAtLocal', e.target.value)}
                        className="mt-1 w-full h-8 rounded-md border border-hairline bg-surface-1 px-2 text-xs"
                        disabled={!selected || !canEditApplyFields}
                    />
                </label>
            </div>

            {rec.earliest_possible_arrival && (
                <p className="text-[11px] text-amber-700 dark:text-amber-300">
                    Earliest possible: {new Date(rec.earliest_possible_arrival).toLocaleString()}
                </p>
            )}
            {rec.rationale && (
                <p className="text-[11px] text-ink-subtle">{rec.rationale}</p>
            )}
            <button
                type="button"
                onClick={() => onFocusShortage?.(rec.entity_id)}
                className="text-[11px] text-primary hover:underline"
            >
                Locate in shortage table
            </button>
        </div>
    )
}

export default RecommendationCard
