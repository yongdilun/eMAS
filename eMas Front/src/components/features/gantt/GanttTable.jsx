import { useState, useRef, useEffect, useMemo } from 'react'

const SLOTS_PER_DAY = 48 // half-hour slots, 24-hour day (0:00–24:00)
const ROW_HEIGHT = 80

/** Convert ISO start/end to position using continuous time (no slot snapping). Prevents overlap for adjacent slots (e.g. 10:57–12:57, 12:57–14:57). */
function slotToPosition(scheduled_start, scheduled_end, baseDate, totalSpanMs) {
  const baseMs = baseDate.getTime()
  const startDate = scheduled_start ? new Date(scheduled_start) : baseDate
  const endDate = scheduled_end ? new Date(scheduled_end) : startDate

  const startMs = startDate.getTime()
  const endMs = Math.max(endDate.getTime(), startMs + 60000)

  const span = Math.max(totalSpanMs, 86400000)
  const leftPct = Math.max(0, Math.min(100, ((startMs - baseMs) / span) * 100))
  const widthPct = Math.max(0, Math.min(100 - leftPct, ((endMs - startMs) / span) * 100))

  const startDayOffset = Math.floor((startMs - baseMs) / 86400000)
  const endDayOffset = Math.floor((endMs - baseMs) / 86400000)
  const startHour = startDate.getHours()
  const startMin = startDate.getMinutes()
  const startSlotInDay = Math.max(0, Math.min(47, startHour * 2 + Math.floor(startMin / 30)))
  const endHour = endDate.getHours()
  const endMin = endDate.getMinutes()
  const endSlotInDay = Math.min(SLOTS_PER_DAY, endHour * 2 + Math.ceil(endMin / 30))
  const absStartSlot = startDayOffset * SLOTS_PER_DAY + startSlotInDay
  const absEndSlot = endDayOffset * SLOTS_PER_DAY + endSlotInDay

  return {
    dayOffset: startDayOffset,
    startSlot: startSlotInDay,
    endSlot: absEndSlot - startDayOffset * SLOTS_PER_DAY,
    absStartSlot,
    absEndSlot,
    leftPct,
    widthPct,
  }
}

const GanttTable = ({ jobs = [], machines: machinesProp = [], selectedJobId: selectedJobIdProp, onJobClick, isPreview = false }) => {
  const [internalSelected, setInternalSelected] = useState(null)
  const selectedJobId = selectedJobIdProp !== undefined ? selectedJobIdProp : internalSelected
  const setSelectedJobId = (id) => {
    setInternalSelected(id)
  }
  const [zoomLevel, setZoomLevel] = useState(1)
  const headerScrollRef = useRef(null)
  const bodyScrollRef = useRef(null)
  const canvasRef = useRef(null)

  const now = new Date()
  const zoomLevels = [
    { label: '4 Hour', hours: 4, width: 400 },
    { label: '2 Hour', hours: 2, width: 600 },
    { label: '1 Hour', hours: 1, width: 1200 },
  ]
  const currentZoom = zoomLevels[zoomLevel]

  const jobColorMap = useMemo(() => {
    const map = new Map()
    const HUE_STEP = 47 // ~360/8 for good spacing; cycles through distinct hues
    let hueIndex = 0

    jobs.forEach((job) => {
      const jobId = job.job_id || job.jobId || job.id
      if (!jobId || map.has(jobId)) return
      const hue = (hueIndex * HUE_STEP) % 360
      hueIndex += 1

      const bg = `hsl(${hue}, 85%, 60%)`
      const light = `hsla(${hue}, 85%, 88%, 0.4)`
      const border = `hsl(${hue}, 85%, 45%)`
      map.set(jobId, { bg, light, border })
    })

    return map
  }, [jobs])

  const { machineRows, displaySlots, totalDays, startDate, baseDate } = useMemo(() => {
    const allSlots = []
    jobs.forEach((job, jobIdx) => {
      (job.slots || []).forEach((slot) => {
        const mid = slot.machine_id || slot.machineId || '—'
        allSlots.push({
          ...slot,
          job,
          jobIdx,
          machineId: mid,
        })
      })
    })

    const machineIds = [...new Set(allSlots.map((s) => s.machineId).filter(Boolean))]
    const machineMap = new Map()
    ;(machinesProp.length ? machinesProp : machineIds.map((id) => ({ machine_id: id, machine_name: id }))).forEach((m, i) => {
      const mid = m.machine_id || m.machineId || m.id || String(i)
      if (!machineMap.has(mid)) machineMap.set(mid, m.machine_name || m.machineName || mid)
    })
    machineIds.forEach((id) => { if (!machineMap.has(id)) machineMap.set(id, id) })

    const machineRows = machineIds.length ? machineIds : [...machineMap.keys()]
    const machineLabel = (id) => machineMap.get(id) || id

    let minDate = null
    let maxDate = null
    allSlots.forEach((s) => {
      const start = s.scheduled_start ? new Date(s.scheduled_start) : null
      const end = s.scheduled_end ? new Date(s.scheduled_end) : null
      if (start) { if (!minDate || start < minDate) minDate = new Date(start) }
      if (end) { if (!maxDate || end > maxDate) maxDate = new Date(end) }
    })

    const refDate = minDate || now
    const baseDate = new Date(refDate)
    baseDate.setHours(0, 0, 0, 0)

    const maxEnd = maxDate || new Date(refDate.getTime() + 7 * 86400000)
    const daysSpan = Math.max(1, Math.ceil((maxEnd.getTime() - baseDate.getTime()) / 86400000))
    const totalDays = Math.max(7, daysSpan + 2)
    const startDate = baseDate
    const totalSpanMs = totalDays * 86400000

    const displaySlots = allSlots.map((s) => {
      const pos = slotToPosition(s.scheduled_start, s.scheduled_end, baseDate, totalSpanMs)
      const actualPos = (s.actual_start && s.actual_end)
        ? slotToPosition(s.actual_start, s.actual_end, baseDate, totalSpanMs)
        : null
      return {
        ...s,
        ...pos,
        actualLeftPct: actualPos?.leftPct,
        actualWidthPct: actualPos?.widthPct,
        machineLabel: machineLabel(s.machineId),
      }
    })

    return { machineRows, displaySlots, totalDays, startDate, baseDate }
  }, [jobs, machinesProp])

  const dayWidth = currentZoom.width
  const totalSlots = totalDays * SLOTS_PER_DAY

  const formatDate = (date) => {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    return `${months[date.getMonth()]} ${date.getDate()}`
  }

  const generateTimeSlots = () => {
    const slots = []
    const slotsPerZoom = Math.max(1, currentZoom.hours * 2)
    for (let day = 0; day < totalDays; day++) {
      const currentDate = new Date(startDate)
      currentDate.setDate(currentDate.getDate() + day)
      for (let slot = 0; slot < SLOTS_PER_DAY; slot += slotsPerZoom) {
        if (slot >= SLOTS_PER_DAY) break
        const hour = slot * 0.5
        const h = Math.floor(hour)
        const m = (slot % 2) * 30
        const label = m === 0 ? `${h.toString().padStart(2, '0')}:00` : `${h.toString().padStart(2, '0')}:30`
        slots.push({ day, slot, date: currentDate, label })
      }
    }
    return slots
  }

  const timeSlots = useMemo(() => generateTimeSlots(), [totalDays, currentZoom])

  const getCurrentSlot = () => {
    const baseMs = baseDate.getTime()
    const dayMs = 86400000
    const daysDiff = Math.floor((now.getTime() - baseMs) / dayMs)
    const hours = now.getHours()
    const minutes = now.getMinutes()
    const slotInDay = hours * 2 + Math.floor(minutes / 30)
    return Math.max(0, daysDiff * SLOTS_PER_DAY + slotInDay)
  }

  const currentSlot = getCurrentSlot()
  const currentSlotPosition = (currentSlot / totalSlots) * 100

  const calculateSlotPosition = (dayOffset, startSlot) => {
    const absSlot = dayOffset * SLOTS_PER_DAY + startSlot
    return (absSlot / totalSlots) * 100
  }

  const calculateSlotWidth = (dayOffset, startSlot, endSlot) => {
    const absStart = dayOffset * SLOTS_PER_DAY + startSlot
    const absEnd = dayOffset * SLOTS_PER_DAY + (endSlot || startSlot + 1)
    return ((absEnd - absStart) / totalSlots) * 100
  }

  const isStepPast = (dayOffset, endSlot) => {
    const absEnd = dayOffset * SLOTS_PER_DAY + (endSlot || 0)
    return absEnd <= currentSlot
  }

  const handleSlotClick = (displaySlot) => {
    const job = displaySlot.job
    const jobId = job.job_id || job.jobId || job.id
    const next = selectedJobId === jobId ? null : jobId
    setSelectedJobId(next)
    onJobClick?.(next ? { job, clickedSlot: displaySlot } : null)
  }

  useEffect(() => {
    const headerEl = headerScrollRef.current
    const bodyEl = bodyScrollRef.current
    if (!headerEl || !bodyEl) return
    let isHeaderScrolling = false
    let isBodyScrolling = false
    const syncHeader = () => {
      if (!isBodyScrolling) {
        isHeaderScrolling = true
        headerEl.scrollLeft = bodyEl.scrollLeft
        setTimeout(() => { isHeaderScrolling = false }, 10)
      }
    }
    const syncBody = () => {
      if (!isHeaderScrolling) {
        isBodyScrolling = true
        bodyEl.scrollLeft = headerEl.scrollLeft
        setTimeout(() => { isBodyScrolling = false }, 10)
      }
    }
    bodyEl.addEventListener('scroll', syncHeader)
    headerEl.addEventListener('scroll', syncBody)
    return () => {
      bodyEl.removeEventListener('scroll', syncHeader)
      headerEl.removeEventListener('scroll', syncBody)
    }
  }, [zoomLevel])

  const getDateForDay = (dayOffset) => {
    const d = new Date(startDate)
    d.setDate(d.getDate() + dayOffset)
    return d
  }

  const isToday = (date) =>
    date.getDate() === now.getDate() && date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear()

  const getMachineLabel = (machineId) => {
    const m = machinesProp.find((x) => (x.machine_id || x.machineId || x.id) === machineId)
    return m?.machine_name || m?.machineName || machineId || '—'
  }

  return (
    <div className="relative flex flex-col h-full">
      <div className="flex-shrink-0 mb-4 px-4 py-3 bg-gradient-to-r from-gray-50 to-gray-100 dark:from-gray-900 dark:to-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">
            <span className="material-symbols-outlined text-base align-middle mr-1">zoom_in</span>
            Zoom Level:
          </span>
          {zoomLevels.map((level, idx) => (
            <button
              key={idx}
              onClick={() => setZoomLevel(idx)}
              className={`px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
                zoomLevel === idx ? 'bg-primary text-white shadow-lg scale-105' : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 border border-gray-300 dark:border-gray-600'
              }`}
            >
              {level.label}
            </button>
          ))}
        </div>
      </div>

        <div className={`flex-1 border rounded-lg overflow-hidden bg-white dark:bg-[#111618] flex flex-col ${isPreview ? 'border-amber-400/40 dark:border-amber-600/40 border-dashed' : 'border-gray-200 dark:border-gray-700'}`}>
        <div className="flex-shrink-0 sticky top-0 z-50 bg-white dark:bg-[#111618] border-b-2 border-gray-300 dark:border-gray-700 shadow-md">
          <div className="flex">
            <div className="w-60 flex-shrink-0 px-4 py-3 font-bold text-sm text-gray-800 dark:text-white border-r-2 border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-50">
              Machine / Resource
            </div>
            <div className="flex-1 overflow-hidden" ref={headerScrollRef}>
              <div className="flex" style={{ minWidth: `${totalDays * dayWidth}px` }}>
                {Array.from({ length: totalDays }).map((_, dayIndex) => {
                  const dayDate = getDateForDay(dayIndex)
                  const isTodayDate = isToday(dayDate)
                  return (
                    <div key={dayIndex} className="flex-1 border-r-2 border-gray-300 dark:border-gray-700">
                      <div className={`text-center py-2 font-bold text-sm border-b border-gray-200 dark:border-gray-700 ${
                        isTodayDate ? 'bg-gradient-to-r from-red-500 to-red-600 text-white' : 'bg-gradient-to-r from-primary to-blue-600 text-white'
                      }`}>
                        {formatDate(dayDate)} {isTodayDate && '(Today)'}
                      </div>
                      <div className="flex">
                        {timeSlots.filter((s) => s.day === dayIndex).map((slot, idx) => (
                          <div
                            key={idx}
                            className="flex-1 px-2 py-2 text-center text-xs font-medium text-gray-600 dark:text-gray-400 border-r border-gray-100 dark:border-gray-800 whitespace-nowrap"
                          >
                            {slot.label}
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-x-auto overflow-y-auto max-h-[600px]" ref={bodyScrollRef}>
          <div className="relative" style={{ minHeight: `${machineRows.length * ROW_HEIGHT}px`, minWidth: `${totalDays * dayWidth + 240}px` }}>
            <div className="flex">
              <div className="w-60 flex-shrink-0 bg-gray-50 dark:bg-gray-900 border-r-2 border-gray-300 dark:border-gray-700 sticky left-0 z-40">
                {machineRows.map((machineId) => (
                  <div
                    key={machineId}
                    className="h-20 px-4 py-4 font-medium text-sm text-gray-800 dark:text-white border-b border-gray-200 dark:border-gray-700 flex items-center bg-gray-50 dark:bg-gray-900"
                  >
                    <span className="material-symbols-outlined text-primary mr-2 text-base">precision_manufacturing</span>
                    <span className="truncate">{getMachineLabel(machineId)}</span>
                  </div>
                ))}
              </div>

              <div className="flex-1 relative" style={{ width: `${totalDays * dayWidth}px` }}>
                <canvas ref={canvasRef} className="absolute top-0 left-0 pointer-events-none z-20" style={{ width: totalDays * dayWidth, height: machineRows.length * ROW_HEIGHT }} />

                {machineRows.map((machineId, machineIndex) => {
                  const slotsOnMachine = displaySlots.filter((s) => s.machineId === machineId)
                  return (
                    <div
                      key={machineId}
                      className="relative h-20 border-b border-gray-200 dark:border-gray-700 hover:bg-gray-50/50 dark:hover:bg-gray-900/30 transition-colors"
                    >
                      <div className="absolute inset-0 flex">
                        {Array.from({ length: totalDays }).map((_, dayIdx) => (
                          <div key={dayIdx} className="relative flex-1 border-r-2 border-gray-300 dark:border-gray-700">
                            {Array.from({ length: SLOTS_PER_DAY }).map((_, slotIdx) => (
                              <div
                                key={slotIdx}
                                className="absolute top-0 bottom-0 border-r border-gray-200/50 dark:border-gray-700/50"
                                style={{ left: `${(slotIdx / SLOTS_PER_DAY) * 100}%` }}
                              />
                            ))}
                          </div>
                        ))}
                      </div>

                      {machineIndex === 0 && currentSlotPosition > 0 && currentSlotPosition < 100 && (
                        <div className="absolute top-0 z-15" style={{ left: `${currentSlotPosition}%`, height: `${machineRows.length * ROW_HEIGHT}px` }}>
                          <div className="w-0.5 bg-gradient-to-b from-red-600 via-red-500 to-red-600 h-full" />
                        </div>
                      )}

                      <div
                        className="absolute top-0 bottom-0 bg-gradient-to-r from-gray-300/20 to-gray-400/20 dark:from-gray-900/40 dark:to-gray-800/40 pointer-events-none z-1"
                        style={{ left: 0, width: `${currentSlotPosition}%` }}
                      />

                      {slotsOnMachine.map((displaySlot, slotIdx) => {
                        const job = displaySlot.job
                        const jobId = job.job_id || job.jobId || job.id
                        const colors =
                          (jobId && jobColorMap.get(jobId)) ||
                          { bg: 'rgb(59, 130, 246)', light: 'rgba(59, 130, 246, 0.15)', border: 'rgb(37, 99, 235)' }
                        const isSelected = selectedJobId === jobId
                        const completed = displaySlot.status === 'completed'
                        const running = displaySlot.status === 'running' || displaySlot.status === 'in-progress'
                        const paused = displaySlot.status === 'paused'
                        const stepIsPast = isStepPast(displaySlot.dayOffset, displaySlot.endSlot)
                        const textStyle = { color: '#111', textShadow: '0 0 1px white, 0 0 2px white, 0 1px 2px rgba(255,255,255,0.9)' }

                        const leftPct = displaySlot.leftPct ?? calculateSlotPosition(displaySlot.dayOffset, displaySlot.startSlot)
                        const widthPct = displaySlot.widthPct ?? calculateSlotWidth(displaySlot.dayOffset, displaySlot.startSlot, displaySlot.endSlot)
                        const stepWidth = (widthPct / 100) * totalDays * dayWidth
                        const hasActualOverlay = (running || completed) && displaySlot.actualLeftPct != null && displaySlot.actualWidthPct != null

                        const slotLeft = hasActualOverlay ? Math.min(leftPct, displaySlot.actualLeftPct) : leftPct
                        const slotRight = hasActualOverlay ? Math.max(leftPct + widthPct, displaySlot.actualLeftPct + displaySlot.actualWidthPct) : leftPct + widthPct
                        const slotWidth = slotRight - slotLeft

                        const showFullContent = stepWidth > 120
                        const showMinimal = stepWidth > 80 && stepWidth <= 120
                        const showNothing = stepWidth <= 50

                        return (
                          <div
                            key={`${jobId}-${displaySlot.slot_id || slotIdx}`}
                            className={`absolute top-2 h-16 left-0 rounded-xl cursor-pointer transition-all duration-300 shadow-md hover:shadow-xl hover:ring-2 hover:ring-gray-800/25 hover:ring-offset-1 hover:ring-offset-white dark:hover:ring-gray-200/25 dark:hover:ring-offset-[#111618] overflow-visible ${
                              isSelected ? 'z-30 shadow-xl ring-2 ring-offset-2 ring-offset-white dark:ring-offset-[#111618]' : 'z-10'
                            }`}
                            style={{
                              left: `${slotLeft}%`,
                              width: `max(4px, ${slotWidth}%)`,
                              ...(isSelected && { '--tw-ring-color': colors.border }),
                            }}
                            onClick={() => handleSlotClick(displaySlot)}
                          >
                            {/* Planned bar (dashed when actual overlay present) */}
                            <div
                              className="absolute inset-0 rounded-xl"
                              style={{
                                left: hasActualOverlay ? `${((leftPct - slotLeft) / slotWidth) * 100}%` : 0,
                                width: hasActualOverlay ? `${(widthPct / slotWidth) * 100}%` : '100%',
                                backgroundColor: stepIsPast && !completed ? colors.light
                                  : paused ? `color-mix(in srgb, ${colors.bg} 70%, #92400e)`
                                  : running ? `color-mix(in srgb, ${colors.bg} 90%, #f59e0b)`
                                  : colors.bg,
                                borderLeft: `4px ${hasActualOverlay || paused ? 'dashed' : 'solid'} ${paused ? '#d97706' : running ? '#f59e0b' : colors.border}`,
                                opacity: hasActualOverlay ? 0.5 : 1,
                                filter: stepIsPast && !completed ? 'grayscale(0.3) brightness(0.9)' : 'none',
                              }}
                            />
                            {/* Actual bar overlay (solid) */}
                            {hasActualOverlay && (
                              <div
                                className="absolute top-0 bottom-0 rounded-xl z-[1]"
                                style={{
                                  left: `${((displaySlot.actualLeftPct - slotLeft) / slotWidth) * 100}%`,
                                  width: `${(displaySlot.actualWidthPct / slotWidth) * 100}%`,
                                  backgroundColor: completed ? colors.bg : `color-mix(in srgb, ${colors.bg} 95%, #f59e0b)`,
                                  borderLeft: `4px solid ${completed ? colors.border : '#f59e0b'}`,
                                }}
                              />
                            )}
                            {isSelected && (
                              <div className="absolute -inset-1 rounded-xl animate-pulse z-[2]" style={{ boxShadow: `0 0 12px ${colors.border}`, border: `2px solid ${colors.border}` }} />
                            )}
                            {(job.deadline_status?.is_late || job.deadline_status?.isLate) && (
                              <span
                                className="absolute top-1.5 right-1.5 z-20 text-[9px] font-semibold px-1.5 py-0.5 rounded-md bg-white/95 dark:bg-gray-900/95 text-red-600 dark:text-red-400 border border-red-400 dark:border-red-500 shadow-sm backdrop-blur-[1px]"
                                title={`Late by ${job.deadline_status?.late_by || job.deadline_status?.lateBy || ''}`}
                              >
                                Late
                              </span>
                            )}
                            {!showNothing && (
                              <div className="relative z-[2] h-full px-2 py-1.5 flex flex-col justify-center overflow-hidden">
                                <div className="flex items-center gap-1 min-w-0">
                                  <span className="font-bold text-xs truncate min-w-0" style={textStyle}>
                                    {jobId || job.product_id || '—'}
                                  </span>
                                  {showFullContent && (
                                    <span className="text-xs font-semibold truncate shrink-0" style={textStyle}>
                                      {completed && <span className="material-symbols-outlined text-sm mr-1 align-middle">check_circle</span>}
                                      {job.product_id || ''}
                                    </span>
                                  )}
                                </div>
                                {showFullContent && (
                                  <span className="text-xs truncate font-medium opacity-90" style={textStyle}>{job.product_id || jobId}</span>
                                )}
                                {showMinimal && !showFullContent && (
                                  <span className="text-xs truncate font-medium opacity-90" style={textStyle}>{job.product_id || jobId}</span>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            </div>
      </div>
      </div>
      </div>
    </div>
  )
}

export default GanttTable
