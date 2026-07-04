const unwrapArr = (d) => {
  if (!d) return []
  if (Array.isArray(d)) return d
  if (Array.isArray(d.data)) return d.data
  if (d.data && Array.isArray(d.data.data)) return d.data.data
  return []
}

const datePartsFor = (row) => {
  const raw = row.date || row.start_time || ''
  const rawText = String(raw)
  const datePrefix = rawText.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (datePrefix) {
    const [, year, month, day] = datePrefix
    const date = new Date(Number(year), Number(month) - 1, Number(day))
    return {
      key: `${year}-${month}-${day}`,
      label: date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    }
  }

  if (raw) {
    const date = new Date(raw)
    if (!Number.isNaN(date.getTime())) {
      const key = [
        date.getFullYear(),
        String(date.getMonth() + 1).padStart(2, '0'),
        String(date.getDate()).padStart(2, '0'),
      ].join('-')
      return {
        key,
        label: date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
      }
    }
  }

  const fallback = row.slot_id || row.machine_id || 'Data'
  return { key: String(fallback), label: String(fallback) }
}

export const aggregateProductionOutputRows = (data) => {
  const byDate = new Map()
  unwrapArr(data).forEach((row) => {
    const date = datePartsFor(row)
    const value = Number(row.quantity_produced ?? row.produced ?? row.total_output ?? row.units ?? 0)
    if (!Number.isFinite(value) || value <= 0) return
    const existing = byDate.get(date.key) || { label: date.label, value: 0 }
    existing.value += value
    byDate.set(date.key, existing)
  })
  return Array.from(byDate.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, row]) => row)
}

const ProductionOutputChart = ({ data }) => {
  const rows = aggregateProductionOutputRows(data).slice(-8)

  if (rows.length === 0) {
    return (
      <div className="flex min-h-[150px] items-center justify-center rounded-lg border border-dashed border-hairline text-sm text-ink-muted">
        No production data
      </div>
    )
  }

  const max = Math.max(...rows.map(row => row.value), 1)
  return (
    <div className="flex min-h-[150px] flex-1 flex-col justify-end py-2" role="img" aria-label="Production output chart">
      <div className="grid h-36 items-end gap-3" style={{ gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))` }}>
        {rows.map((row) => {
          const barHeight = Math.max(10, Math.round((96 * row.value) / max))
          return (
            <div key={row.label} className="flex h-full min-w-0 flex-col justify-end gap-1.5">
              <span className="text-center text-[11px] font-semibold leading-none text-ink">
                {row.value.toLocaleString()}
              </span>
              <div className="flex h-24 items-end">
                <div
                  className="w-full rounded-t bg-primary transition-all duration-700"
                  style={{ height: `${barHeight}px` }}
                  title={`${row.label}: ${row.value.toLocaleString()} units`}
                />
              </div>
              <p className="truncate text-center text-ink-muted text-caption">
                {row.label}
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default ProductionOutputChart
