const unwrapArr = (data) => {
  if (!data) return []
  if (Array.isArray(data)) return data
  if (Array.isArray(data.data)) return data.data
  if (data.data && Array.isArray(data.data.data)) return data.data.data
  return []
}

const labelFor = (row) => {
  const raw = row.label ?? row.date ?? row.slot_id ?? ''
  const date = new Date(raw)
  if (!Number.isNaN(date.getTime())) {
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }
  return String(raw || 'Data')
}

const ProductionChart = ({ data }) => {
  const pts = unwrapArr(data)
    .map(d => ({
      label: labelFor(d),
      units: Number(d.units ?? d.qty_produced ?? d.quantity_produced ?? d.total_output ?? 0),
    }))
    .filter(p => p.units > 0)
    .slice(-12)

  if (pts.length === 0) {
    return (
      <div className="flex min-h-[180px] items-center justify-center rounded-lg border border-dashed border-hairline text-sm text-ink-muted">
        No production data
      </div>
    )
  }

  const maxVal = Math.max(...pts.map(p => p.units), 1)
  const W = 540
  const H = 200
  const pad = 20
  const xStep = (W - pad * 2) / (pts.length - 1 || 1)

  const coords = pts.map((p, i) => ({
    x: pad + i * xStep,
    y: pad + (1 - p.units / maxVal) * (H - pad * 2),
    ...p,
  }))

  const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')
  const fill = `${path} L${coords[coords.length - 1].x},${H} L${coords[0].x},${H} Z`

  return (
    <div className="flex min-h-[180px] flex-1 flex-col justify-end gap-3 pt-4">
      <svg fill="none" height="100%" preserveAspectRatio="none" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Production output">
        <path d={fill} fill="url(#dashboardProductionGradient)" />
        <path d={path} stroke="#00c3ff" strokeLinecap="round" strokeWidth="3" />
        {coords.map((c, i) => (
          <circle key={i} cx={c.x} cy={c.y} r="4" fill="#00c3ff" />
        ))}
        <defs>
          <linearGradient id="dashboardProductionGradient" gradientUnits="userSpaceOnUse" x1="275" x2="275" y1="0" y2={H}>
            <stop stopColor="#00c3ff" stopOpacity="0.2" />
            <stop offset="1" stopColor="#00c3ff" stopOpacity="0" />
          </linearGradient>
        </defs>
      </svg>
      <div className="grid gap-2 border-t border-hairline pt-2" style={{ gridTemplateColumns: `repeat(${pts.length}, minmax(0, 1fr))` }}>
        {pts.map((p, idx) => (
          <p key={`${p.label}-${idx}`} className="truncate text-center text-ink-subtle text-xs font-medium">{p.label}</p>
        ))}
      </div>
    </div>
  )
}

export default ProductionChart
