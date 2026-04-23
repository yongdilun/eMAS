import { useState } from 'react'

const CalendarPicker = ({ onDateRangeChange }) => {
  const [currentMonth, setCurrentMonth] = useState(new Date(2023, 9, 1)) // October 2023
  const [selectedStart, setSelectedStart] = useState(5)
  const [selectedEnd, setSelectedEnd] = useState(9)

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

  const daysInMonth = new Date(
    currentMonth.getFullYear(),
    currentMonth.getMonth() + 1,
    0
  ).getDate()

  const firstDayOfMonth = new Date(
    currentMonth.getFullYear(),
    currentMonth.getMonth(),
    1
  ).getDay()

  const handlePrevMonth = () => {
    setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1))
  }

  const handleNextMonth = () => {
    setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1))
  }

  const handleDateClick = (day) => {
    if (!selectedStart || (selectedStart && selectedEnd && day < selectedStart)) {
      setSelectedStart(day)
      setSelectedEnd(null)
    } else if (selectedStart && !selectedEnd) {
      if (day >= selectedStart) {
        setSelectedEnd(day)
      } else {
        setSelectedStart(day)
        setSelectedEnd(null)
      }
    } else {
      setSelectedStart(day)
      setSelectedEnd(null)
    }
  }

  const isInRange = (day) => {
    if (!selectedStart) return false
    if (!selectedEnd) return day === selectedStart
    return day >= selectedStart && day <= selectedEnd
  }

  const isStart = (day) => day === selectedStart
  const isEnd = (day) => day === selectedEnd

  const weekDays = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
  const days = Array.from({ length: daysInMonth }, (_, i) => i + 1)

  // Get the correct first day (0 = Sunday, 1 = Monday, etc.)
  const adjustedFirstDay = firstDayOfMonth === 0 ? 0 : firstDayOfMonth

  return (
    <div className="flex flex-col w-full p-4 bg-white dark:bg-[#101718] border border-gray-300 dark:border-[#27363a] rounded-xl">
      <p className="text-gray-900 dark:text-white text-base font-medium leading-normal pb-2">Date Range</p>
      <div className="flex min-w-72 flex-1 flex-col gap-0.5">
        <div className="flex items-center p-1 justify-between">
          <button
            onClick={handlePrevMonth}
            className="text-gray-900 dark:text-white flex size-10 items-center justify-center rounded-full hover:bg-gray-100 dark:hover:bg-[#27363a]"
          >
            <span className="material-symbols-outlined text-lg">chevron_left</span>
          </button>
          <p className="text-gray-900 dark:text-white text-base font-bold leading-tight flex-1 text-center">
            {monthNames[currentMonth.getMonth()]} {currentMonth.getFullYear()}
          </p>
          <button
            onClick={handleNextMonth}
            className="text-gray-900 dark:text-white flex size-10 items-center justify-center rounded-full hover:bg-gray-100 dark:hover:bg-[#27363a]"
          >
            <span className="material-symbols-outlined text-lg">chevron_right</span>
          </button>
        </div>

        <div className="grid grid-cols-7">
          {weekDays.map((day, index) => (
            <p
              key={index}
              className="text-gray-700 dark:text-white text-[13px] font-bold leading-normal tracking-[0.015em] flex h-10 w-full items-center justify-center pb-0.5"
            >
              {day}
            </p>
          ))}

          {/* Empty cells for days before the first day of the month */}
          {Array.from({ length: adjustedFirstDay }, (_, i) => (
            <div key={`empty-${i}`} className="h-10 w-full"></div>
          ))}

          {/* Calendar days */}
          {days.map((day) => {
            const inRange = isInRange(day)
            const start = isStart(day)
            const end = isEnd(day)

            return (
              <button
                key={day}
                onClick={() => handleDateClick(day)}
                className={`h-10 w-full text-sm font-medium leading-normal ${
                  start
                    ? 'text-black rounded-l-full bg-primary/20'
                    : end
                    ? 'text-black rounded-r-full bg-primary/20'
                    : inRange
                    ? 'bg-primary/20 text-gray-900 dark:text-white'
                    : 'text-gray-900 dark:text-white'
                }`}
              >
                <div
                  className={`flex size-full items-center justify-center rounded-full ${
                    start || end ? 'bg-primary text-white' : ''
                  }`}
                >
                  {day}
                </div>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default CalendarPicker

