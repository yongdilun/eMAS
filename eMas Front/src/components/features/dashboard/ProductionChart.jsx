// Renders 24-hour production data from GET /reports/production-output
// data shape: { data: [{ label, units }] }   (falls back to static SVG when null)

const ProductionChart = ({ data }) => {
  const pts = (() => {
    const arr = Array.isArray(data) ? data : (data?.data ?? null)
    if (!arr || arr.length === 0) return null
    return arr.map(d => ({ label: d.label ?? d.date ?? '—', units: d.units ?? d.qty_produced ?? 0 }))
  })()

  if (!pts) {
    // Static fallback SVG (original design)
    return (
      <div className="flex min-h-[180px] flex-1 flex-col justify-end gap-4 pt-4">
        <svg fill="none" height="100%" preserveAspectRatio="none" viewBox="0 0 540 250" width="100%" xmlns="http://www.w3.org/2000/svg">
          <path d="M0 178C21.1765 178 21.1765 35 42.3529 35C63.5294 35 63.5294 67 84.7059 67C105.882 67 105.882 151 127.059 151C148.235 151 148.235 54 169.412 54C190.588 54 190.588 164 211.765 164C232.941 164 232.941 99 254.118 99C275.294 99 275.294 73 296.471 73C317.647 73 317.647 196 338.824 196C360 196 360 242 381.176 242C402.353 242 402.353 2 423.529 2C444.706 2 444.706 131 465.882 131C487.059 131 487.059 209 508.235 209C529.412 209 529.412 41 550 41" stroke="#00c3ff" strokeLinecap="round" strokeWidth="3"/>
          <path d="M0 178C21.1765 178 21.1765 35 42.3529 35C63.5294 35 63.5294 67 84.7059 67C105.882 67 105.882 151 127.059 151C148.235 151 148.235 54 169.412 54C190.588 54 190.588 164 211.765 164C232.941 164 232.941 99 254.118 99C275.294 99 275.294 73 296.471 73C317.647 73 317.647 196 338.824 196C360 196 360 242 381.176 242C402.353 242 402.353 2 423.529 2C444.706 2 444.706 131 465.882 131C487.059 131 487.059 209 508.235 209C529.412 209 529.412 41 550 41V250H0V178Z" fill="url(#cg)"/>
          <defs>
            <linearGradient gradientUnits="userSpaceOnUse" id="cg" x1="275" x2="275" y1="2" y2="250">
              <stop stopColor="#00c3ff" stopOpacity="0.2"/>
              <stop offset="1" stopColor="#00c3ff" stopOpacity="0"/>
            </linearGradient>
          </defs>
        </svg>
        <div className="flex justify-between border-t border-white/10 pt-2">
          {['12 AM','4 AM','8 AM','12 PM','4 PM','8 PM'].map(t => (
            <p key={t} className="text-white/60 text-xs font-medium">{t}</p>
          ))}
        </div>
      </div>
    )
  }

  // Dynamic line chart from real data
  const maxVal = Math.max(...pts.map(p => p.units)) || 1
  const W = 540, H = 200, pad = 20
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
      <svg fill="none" height="100%" preserveAspectRatio="none" viewBox={`0 0 ${W} ${H}`} width="100%">
        <path d={fill} fill="url(#dg)" />
        <path d={path} stroke="#00c3ff" strokeLinecap="round" strokeWidth="3" />
        {coords.map((c, i) => (
          <circle key={i} cx={c.x} cy={c.y} r="4" fill="#00c3ff" />
        ))}
        <defs>
          <linearGradient id="dg" gradientUnits="userSpaceOnUse" x1="275" x2="275" y1="0" y2={H}>
            <stop stopColor="#00c3ff" stopOpacity="0.2"/>
            <stop offset="1" stopColor="#00c3ff" stopOpacity="0"/>
          </linearGradient>
        </defs>
      </svg>
      <div className="flex justify-between border-t border-white/10 pt-2">
        {pts.map(p => (
          <p key={p.label} className="text-white/60 text-xs font-medium">{p.label}</p>
        ))}
      </div>
    </div>
  )
}

export default ProductionChart
