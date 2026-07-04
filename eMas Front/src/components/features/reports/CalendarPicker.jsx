import { useEffect, useMemo, useState } from 'react'

const monthNames = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
]

const shortMonthNames = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
]

const weekDays = ['S', 'M', 'T', 'W', 'T', 'F', 'S']

function pad2(value) {
    return String(value).padStart(2, '0')
}

export function formatDateInput(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return ''
    return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

export function parseDateInput(value) {
    const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/)
    if (!match) return null
    const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    return Number.isNaN(date.getTime()) ? null : date
}

function addDays(date, days) {
    const next = new Date(date)
    next.setDate(next.getDate() + days)
    return next
}

function todayInput() {
    return formatDateInput(new Date())
}

export function defaultReportDateRange() {
    const end = new Date()
    const start = addDays(end, -29)
    return {
        startDate: formatDateInput(start),
        endDate: formatDateInput(end),
    }
}

function sortRange(startDate, endDate) {
    if (!startDate || !endDate) return { startDate, endDate }
    return startDate <= endDate
        ? { startDate, endDate }
        : { startDate: endDate, endDate: startDate }
}

function monthInputValue(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return ''
    return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}`
}

function monthBounds(monthValue) {
    const match = String(monthValue || '').match(/^(\d{4})-(\d{2})$/)
    if (!match) return null
    const year = Number(match[1])
    const month = Number(match[2]) - 1
    const start = new Date(year, month, 1)
    const end = new Date(year, month + 1, 0)
    return {
        start,
        end,
        startDate: formatDateInput(start),
        endDate: formatDateInput(end),
    }
}

function selectedMonthValue(startDate, endDate) {
    const start = parseDateInput(startDate)
    const end = parseDateInput(endDate)
    if (!start || !end) return ''
    if (start.getDate() !== 1) return ''
    const lastDay = new Date(start.getFullYear(), start.getMonth() + 1, 0).getDate()
    if (
        end.getFullYear() !== start.getFullYear() ||
        end.getMonth() !== start.getMonth() ||
        end.getDate() !== lastDay
    ) return ''
    return monthInputValue(start)
}

function buildMonthOptions(anchor = new Date()) {
    const options = []
    const end = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
    const start = new Date(anchor.getFullYear() - 1, 0, 1)
    for (
        let cursor = new Date(end);
        cursor >= start;
        cursor = new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1)
    ) {
        options.push({
            value: monthInputValue(cursor),
            label: `${shortMonthNames[cursor.getMonth()]} ${cursor.getFullYear()}`,
        })
    }
    return options
}

const dateInputCls = 'w-full rounded-lg border border-hairline bg-surface-1 text-ink h-10 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary'
const compactSelectCls = 'w-full rounded-lg border border-hairline bg-surface-1 text-ink h-10 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary'
const rangeFillStyle = {
    backgroundColor: 'color-mix(in srgb, var(--color-primary) 18%, transparent)',
}

const CalendarPicker = ({ startDate, endDate, onDateRangeChange }) => {
    const initialMonth = parseDateInput(startDate) || new Date()
    const [currentMonth, setCurrentMonth] = useState(new Date(initialMonth.getFullYear(), initialMonth.getMonth(), 1))
    const [selectingEnd, setSelectingEnd] = useState(false)
    const [calendarExpanded, setCalendarExpanded] = useState(false)
    const monthOptions = useMemo(() => buildMonthOptions(), [])

    useEffect(() => {
        const parsed = parseDateInput(startDate)
        if (parsed) setCurrentMonth(new Date(parsed.getFullYear(), parsed.getMonth(), 1))
    }, [startDate])

    const daysInMonth = new Date(
        currentMonth.getFullYear(),
        currentMonth.getMonth() + 1,
        0,
    ).getDate()

    const firstDayOfMonth = new Date(
        currentMonth.getFullYear(),
        currentMonth.getMonth(),
        1,
    ).getDay()

    const selectedRange = useMemo(
        () => sortRange(startDate, endDate),
        [startDate, endDate],
    )

    const emitRange = (nextStartDate, nextEndDate) => {
        const sorted = sortRange(nextStartDate, nextEndDate)
        onDateRangeChange?.({
            startDate: sorted.startDate,
            endDate: sorted.endDate,
            start: parseDateInput(sorted.startDate),
            end: parseDateInput(sorted.endDate),
        })
    }

    const handlePreset = (days) => {
        const end = new Date()
        const start = addDays(end, -(days - 1))
        setSelectingEnd(false)
        emitRange(formatDateInput(start), formatDateInput(end))
    }

    const handleMonthSelect = (monthValue) => {
        const bounds = monthBounds(monthValue)
        if (!bounds) return
        setCurrentMonth(new Date(bounds.start.getFullYear(), bounds.start.getMonth(), 1))
        setSelectingEnd(false)
        emitRange(bounds.startDate, bounds.endDate)
    }

    const handlePrevMonth = () => {
        setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1))
    }

    const handleNextMonth = () => {
        setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1))
    }

    const handleDateClick = (day) => {
        const clicked = formatDateInput(new Date(currentMonth.getFullYear(), currentMonth.getMonth(), day))
        if (!selectingEnd || !startDate) {
            emitRange(clicked, clicked)
            setSelectingEnd(true)
            return
        }
        emitRange(startDate, clicked)
        setSelectingEnd(false)
    }

    const handleStartInput = (value) => {
        const nextStart = value || todayInput()
        const nextEnd = endDate && endDate >= nextStart ? endDate : nextStart
        setSelectingEnd(false)
        emitRange(nextStart, nextEnd)
    }

    const handleEndInput = (value) => {
        const nextEnd = value || todayInput()
        const nextStart = startDate && startDate <= nextEnd ? startDate : nextEnd
        setSelectingEnd(false)
        emitRange(nextStart, nextEnd)
    }

    const isInRange = (dateValue) => (
        selectedRange.startDate &&
        selectedRange.endDate &&
        dateValue >= selectedRange.startDate &&
        dateValue <= selectedRange.endDate
    )
    const isStart = (dateValue) => dateValue === selectedRange.startDate
    const isEnd = (dateValue) => dateValue === selectedRange.endDate
    const days = Array.from({ length: daysInMonth }, (_, i) => i + 1)
    const selectedMonth = selectedMonthValue(selectedRange.startDate, selectedRange.endDate)

    const presets = [
        { label: 'Today', days: 1 },
        { label: 'Last 7 Days', days: 7 },
        { label: 'Last 30 Days', days: 30 },
    ]

    return (
        <div className="flex flex-col w-full p-4 bg-surface-1 border border-hairline rounded-xl">
            <div className="flex items-start justify-between gap-3 pb-3">
                <div className="min-w-0">
                    <p className="text-ink text-base font-medium leading-normal">Date Range</p>
                    <p className="text-xs text-ink-subtle truncate">{selectedRange.startDate} - {selectedRange.endDate}</p>
                </div>
                <span className="shrink-0 rounded-md border border-hairline bg-surface-2 px-2 py-1 text-xs font-semibold text-ink-muted">
                    PDF period
                </span>
            </div>

            <p className="pb-2 text-xs font-semibold text-ink-subtle">Latest periods</p>
            <div className="grid grid-cols-3 gap-2 pb-3">
                {presets.map((preset) => {
                    const end = new Date()
                    const start = addDays(end, -(preset.days - 1))
                    const active =
                        selectedRange.startDate === formatDateInput(start) &&
                        selectedRange.endDate === formatDateInput(end)
                    return (
                        <button
                            key={preset.days}
                            type="button"
                            onClick={() => handlePreset(preset.days)}
                            className={`min-h-9 rounded-lg border px-2 text-xs font-semibold leading-tight transition-colors ${active
                                ? 'border-primary bg-primary text-white'
                                : 'border-hairline bg-surface-2 text-ink-muted hover:bg-surface-3'
                                }`}
                        >
                            {preset.label}
                        </button>
                    )
                })}
            </div>

            <label className="block pb-4">
                <span className="block pb-1 text-xs font-semibold text-ink-subtle">Monthly report</span>
                <select
                    aria-label="Monthly report month"
                    value={selectedMonth}
                    onChange={(e) => handleMonthSelect(e.target.value)}
                    className={compactSelectCls}
                >
                    <option value="">Select month</option>
                    {monthOptions.map((month) => (
                        <option key={month.value} value={month.value} className="bg-surface-1">
                            {month.label}
                        </option>
                    ))}
                </select>
            </label>

            <div className="grid grid-cols-1 gap-3 pb-4">
                <label className="min-w-0">
                    <span className="block pb-1 text-xs font-semibold text-ink-subtle">Start date</span>
                    <input
                        aria-label="Report start date"
                        type="date"
                        value={selectedRange.startDate || ''}
                        onChange={(e) => handleStartInput(e.target.value)}
                        className={dateInputCls}
                    />
                </label>
                <label className="min-w-0">
                    <span className="block pb-1 text-xs font-semibold text-ink-subtle">End date</span>
                    <input
                        aria-label="Report end date"
                        type="date"
                        value={selectedRange.endDate || ''}
                        onChange={(e) => handleEndInput(e.target.value)}
                        className={dateInputCls}
                    />
                </label>
            </div>

            <div className="overflow-hidden rounded-lg border border-hairline bg-surface-2">
                <button
                    type="button"
                    aria-expanded={calendarExpanded}
                    onClick={() => setCalendarExpanded((open) => !open)}
                    className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors hover:bg-surface-3"
                >
                    <span className="flex min-w-0 items-center gap-2">
                        <span className="material-symbols-outlined text-base text-ink-muted">calendar_month</span>
                        <span className="text-sm font-semibold text-ink">Custom calendar</span>
                    </span>
                    <span className={`material-symbols-outlined text-lg text-ink-muted transition-transform ${calendarExpanded ? 'rotate-180' : ''}`}>
                        expand_more
                    </span>
                </button>

                {calendarExpanded && (
                    <div className="flex min-w-72 flex-1 flex-col gap-0.5 border-t border-hairline bg-surface-1 p-1">
                        <div className="flex items-center justify-between">
                            <button
                                type="button"
                                onClick={handlePrevMonth}
                                className="text-ink flex size-10 items-center justify-center rounded-full hover:bg-surface-2 dark:hover:bg-[#27363a]"
                                aria-label="Previous month"
                            >
                                <span className="material-symbols-outlined text-lg">chevron_left</span>
                            </button>
                            <p className="text-ink text-base font-bold leading-tight flex-1 text-center">
                                {monthNames[currentMonth.getMonth()]} {currentMonth.getFullYear()}
                            </p>
                            <button
                                type="button"
                                onClick={handleNextMonth}
                                className="text-ink flex size-10 items-center justify-center rounded-full hover:bg-surface-2 dark:hover:bg-[#27363a]"
                                aria-label="Next month"
                            >
                                <span className="material-symbols-outlined text-lg">chevron_right</span>
                            </button>
                        </div>

                        <div className="grid grid-cols-7">
                            {weekDays.map((day, index) => (
                                <p
                                    key={`${day}-${index}`}
                                    className="text-ink-muted text-[13px] font-bold leading-normal flex h-10 w-full items-center justify-center pb-0.5"
                                >
                                    {day}
                                </p>
                            ))}

                            {Array.from({ length: firstDayOfMonth }, (_, i) => (
                                <div key={`empty-${i}`} className="h-10 w-full" />
                            ))}

                            {days.map((day) => {
                                const dateValue = formatDateInput(new Date(currentMonth.getFullYear(), currentMonth.getMonth(), day))
                                const inRange = isInRange(dateValue)
                                const start = isStart(dateValue)
                                const end = isEnd(dateValue)
                                const single = start && end

                                return (
                                    <button
                                        key={day}
                                        type="button"
                                        aria-label={`Select ${dateValue}`}
                                        data-report-day={dateValue}
                                        data-in-range={inRange ? 'true' : undefined}
                                        data-range-start={start ? 'true' : undefined}
                                        data-range-end={end ? 'true' : undefined}
                                        onClick={() => handleDateClick(day)}
                                        style={inRange && !single ? rangeFillStyle : undefined}
                                        className={`relative h-10 w-full text-sm font-medium leading-normal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-focus ${inRange ? 'text-ink' : 'text-ink'
                                            } ${single ? 'rounded-full' : start ? 'rounded-l-full' : end ? 'rounded-r-full' : ''}`}
                                    >
                                        <div
                                            className={`relative z-10 mx-auto flex size-9 items-center justify-center rounded-full ${start || end ? 'bg-primary text-white shadow-sm' : ''
                                                }`}
                                        >
                                            {day}
                                        </div>
                                    </button>
                                )
                            })}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export default CalendarPicker
