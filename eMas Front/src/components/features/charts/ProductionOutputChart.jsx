const unwrapArr = (d) => {
  if (!d) return []
  if (Array.isArray(d)) return d
  if (Array.isArray(d.data)) return d.data
  if (d.data && Array.isArray(d.data.data)) return d.data.data
  return []
}

const labelFor = (row) => {
  const raw = row.date || row.start_time || row.slot_id || row.machine_id || ''
  if (!raw) return 'Data'
  const date = new Date(raw)
  if (!Number.isNaN(date.getTime())) {
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }
  return String(raw)
}

const ProductionOutputChart = ({ data }) => {
  const rows = unwrapArr(data)
    .map(row => ({
      label: labelFor(row),
      value: Number(row.quantity_produced ?? row.produced ?? row.total_output ?? row.units ?? 0),
    }))
    .filter(row => row.value > 0)
    .slice(-8)

  if (rows.length === 0) {
    return (
      <div className="flex min-h-[150px] items-center justify-center rounded-lg border border-dashed border-hairline text-sm text-ink-muted">
        No production data
      </div>
    )
  }

  const max = Math.max(...rows.map(row => row.value), 1)
  const width = 360
  const height = 150
  const padX = 18
  const padY = 14
  const gap = 10
  const barWidth = Math.max(12, (width - padX * 2 - gap * (rows.length - 1)) / rows.length)

  return (
    <div className="flex min-h-[150px] flex-1 flex-col gap-3 py-2">
      <svg
        fill="none"
        height="120"
        preserveAspectRatio="none"
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Production output chart"
      >
        <line x1={padX} x2={width - padX} y1={height - padY} y2={height - padY} stroke="currentColor" className="text-hairline" />
        {rows.map((row, idx) => {
          const x = padX + idx * (barWidth + gap)
          const barHeight = Math.max(4, ((height - padY * 2) * row.value) / max)
          const y = height - padY - barHeight
          return (
            <g key={`${row.label}-${idx}`}>
              <rect x={x} y={y} width={barWidth} height={barHeight} rx="3" fill="#5e6ad2" />
              <text x={x + barWidth / 2} y={Math.max(12, y - 5)} textAnchor="middle" className="fill-ink-muted text-[10px]">
                {row.value}
              </text>
            </g>
          )
        })}
      </svg>
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))` }}>
        {rows.map((row, idx) => (
          <p key={`${row.label}-label-${idx}`} className="truncate text-center text-ink-muted text-caption">
            {row.label}
          </p>
        ))}
      </div>
    </div>
  )
}

export default ProductionOutputChart
