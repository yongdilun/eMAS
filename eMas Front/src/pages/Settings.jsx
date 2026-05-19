import { useState, useEffect, useCallback, useRef } from 'react'
import { useThemeContext } from '../context/ThemeContext'
import SettingRow from '../components/features/settings/SettingRow'
import ThemeToggle from '../components/features/settings/ThemeToggle'
import PageHeader from '../components/shared/PageHeader'
import { settingsApi, schedulingApi, toData, apiErrorMessage, apiErrorToastOptions } from '../services/api'
import logger from '../services/logger'
import { useToast } from '../context/ToastContext'

// Purple-accented toggle switch component (Linear Primary)
const Toggle = ({ checked, onChange }) => (
  <label className="relative inline-flex items-center cursor-pointer group">
    <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="sr-only peer" />
    <div className="w-11 h-6 bg-hairline-strong border border-hairline rounded-full transition-colors
      peer-checked:bg-primary peer-checked:border-primary-hover
      after:content-[''] after:absolute after:top-[3px] after:left-[3px] 
      after:bg-white after:rounded-full after:h-[18px] after:w-[18px] after:transition-all 
      after:shadow-sm peer-checked:after:translate-x-[20px]" />
  </label>
)

const ERP_SYSTEMS = ['SAP ERP', 'Oracle ERP Cloud', 'Microsoft Dynamics', 'Odoo', 'Custom MES API']
// API uses codes (en, zh); map to display labels per SETTINGS_FRONTEND.md
const LANG_OPTIONS = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Español' },
  { code: 'de', label: 'Deutsch' },
  { code: 'fr', label: 'Français' },
  { code: 'zh', label: '中文' },
  { code: 'ms', label: 'Bahasa Malaysia' },
]

const workDaysToCheckboxes = (str) => {
  const nums = (str || '1,2,3,4,5').split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n))
  return {
    mon: nums.includes(1), tue: nums.includes(2), wed: nums.includes(3), thu: nums.includes(4),
    fri: nums.includes(5), sat: nums.includes(6), sun: nums.includes(0),
  }
}

const checkboxesToWorkDays = (cb) => {
  const days = []
  if (cb.sun) days.push(0)
  if (cb.mon) days.push(1)
  if (cb.tue) days.push(2)
  if (cb.wed) days.push(3)
  if (cb.thu) days.push(4)
  if (cb.fri) days.push(5)
  if (cb.sat) days.push(6)
  return days.sort((a, b) => a - b).join(',')
}

const ALL_DAYS = { mon: true, tue: true, wed: true, thu: true, fri: true, sat: true, sun: true }
const is24x7Schedule = (start, end, days) =>
  start === '00:00' &&
  end === '23:59' &&
  !!days?.mon && !!days?.tue && !!days?.wed && !!days?.thu && !!days?.fri && !!days?.sat && !!days?.sun

const Settings = () => {
  const { theme, toggleTheme, setTheme } = useThemeContext()
  const toast = useToast()

  const [loading, setLoading] = useState(true)
  const [saveMsg, setSaveMsg] = useState('')
  const [saveErr, setSaveErr] = useState('')

  // User preferences (API: theme, language code, notifications, ai_enabled)
  const [language, setLanguage] = useState('en')
  const [aiEnabled, setAiEnabled] = useState(true)
  const [timezone, setTimezone] = useState('UTC+8')

  // Notification settings (UC-SS01)
  const [notifJobComplete, setNotifJobComplete] = useState(true)
  const [notifMaintAlert, setNotifMaintAlert] = useState(true)
  const [notifLowStock, setNotifLowStock] = useState(true)
  const [notifDowntime, setNotifDowntime] = useState(true)
  const [notifEmail, setNotifEmail] = useState(false)
  const [notifPushEnabled, setNotifPushEnabled] = useState(true)

  // System settings
  const [simulationMode, setSimulationMode] = useState(false)
  const [autoSaveInterval, setAutoSaveInterval] = useState(30)
  const [dataRetentionDays, setDataRetentionDays] = useState(90)

  // ERP / MES integration (UC-SS03)
  const [erpSystem, setErpSystem] = useState('')
  const [erpEndpoint, setErpEndpoint] = useState('')
  const [erpStatus, setErpStatus] = useState('disconnected') // 'connected'|'disconnected'|'testing'
  const [erpLastSync, setErpLastSync] = useState('')
  const [erpTesting, setErpTesting] = useState(false)

  // Scheduling (AI_SPLIT_STRATEGY, AI_OBJECTIVE, AI_AUTO_RESCHEDULE_ON_EVENT)
  const [schedulingSupported, setSchedulingSupported] = useState(false)
  const [lockInWindowMinutes, setLockInWindowMinutes] = useState(240)
  const [deviationPenaltyWeight, setDeviationPenaltyWeight] = useState(0.25)
  const [splitStrategy, setSplitStrategy] = useState('equal')
  const [schedulingObjective, setSchedulingObjective] = useState('minimize_tardiness')
  const [autoRescheduleOnEvent, setAutoRescheduleOnEvent] = useState(false)
  const [workStartTime, setWorkStartTime] = useState('08:00')
  const [workEndTime, setWorkEndTime] = useState('17:00')
  const [workDays, setWorkDays] = useState({ mon: true, tue: true, wed: true, thu: true, fri: true, sat: false, sun: false })
  const [wholeDayOperation, setWholeDayOperation] = useState(false)
  const [publicHolidays, setPublicHolidays] = useState([])
  const [newHolidayDate, setNewHolidayDate] = useState('')
  const [refreshCalendarsLoading, setRefreshCalendarsLoading] = useState(false)

  const saveTimerRef = useRef(null)

  // Load settings from API on mount (SETTINGS_FRONTEND.md)
  useEffect(() => {
    settingsApi.get()
      .then((res) => {
        const data = toData(res) ?? res
        if (!data) return
        // API fields: theme, language, notifications, ai_enabled, integrations
        if (data.theme === 'light' || data.theme === 'dark') setTheme(data.theme)
        if (data.language) setLanguage(data.language)
        if (data.ai_enabled !== undefined) setAiEnabled(data.ai_enabled)
        // Notifications: boolean or legacy { enabled: true }
        const n = data.notifications
        if (typeof n === 'boolean') {
          setNotifPushEnabled(n)
        } else if (n && typeof n === 'object') {
          if (n.enabled !== undefined) setNotifPushEnabled(n.enabled)
          if (n.job_complete !== undefined) setNotifJobComplete(n.job_complete)
          if (n.maintenance_alert !== undefined) setNotifMaintAlert(n.maintenance_alert)
          if (n.low_stock !== undefined) setNotifLowStock(n.low_stock)
          if (n.downtime !== undefined) setNotifDowntime(n.downtime)
          if (n.email_enabled !== undefined) setNotifEmail(n.email_enabled)
          if (n.push_enabled !== undefined) setNotifPushEnabled(n.push_enabled)
        }
        // Non-API fields: keep local defaults (timezone, simulation_mode, etc. not in PUT /settings)
      })
      .catch((err) => {
        logger.warn('Settings could not be loaded from server; using defaults', { message: err?.message })
      })
      .finally(() => setLoading(false))

    schedulingApi.getSettings()
      .then((r) => {
        const d = toData(r) ?? r
        if (d) {
          setSchedulingSupported(true)
          if (d.lock_in_window_minutes != null) setLockInWindowMinutes(Number(d.lock_in_window_minutes))
          if (d.deviation_penalty_weight != null) setDeviationPenaltyWeight(Number(d.deviation_penalty_weight))
          if (d.split_strategy != null) setSplitStrategy(d.split_strategy)
          if (d.objective != null) setSchedulingObjective(d.objective)
          if (d.auto_reschedule_on_event != null) setAutoRescheduleOnEvent(d.auto_reschedule_on_event)
          if (d.work_start_time != null) setWorkStartTime(d.work_start_time)
          if (d.work_end_time != null) setWorkEndTime(d.work_end_time)
          if (d.work_days != null) setWorkDays(workDaysToCheckboxes(d.work_days))
          if (Array.isArray(d.public_holidays)) setPublicHolidays([...d.public_holidays])
        }
      })
      .catch((err) => {
        if (err?.status !== 404) logger.warn('Scheduling settings unavailable', { message: err?.message })
      })
  }, [setTheme])

  useEffect(() => {
    setWholeDayOperation(is24x7Schedule(workStartTime, workEndTime, workDays))
  }, [workStartTime, workEndTime, workDays])

  // Debounced auto-save
  const scheduleSave = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      handleSaveRef.current({ quietAuthToast: true })
    }, 1200)
  }, [])

  const handleSave = useCallback(async (options = {}) => {
    setSaveMsg(''); setSaveErr('')
    // PUT /settings: theme, language, notifications (bool), ai_enabled — SETTINGS_FRONTEND.md
    const payload = {
      theme,
      language,
      notifications: notifPushEnabled,
      ai_enabled: aiEnabled,
    }
    try {
      await settingsApi.update(payload)
      if (schedulingSupported) {
        await schedulingApi.updateSettings({
          lock_in_window_minutes: lockInWindowMinutes,
          deviation_penalty_weight: deviationPenaltyWeight,
          split_strategy: splitStrategy,
          objective: schedulingObjective,
          auto_reschedule_on_event: autoRescheduleOnEvent,
          work_start_time: workStartTime,
          work_end_time: workEndTime,
          work_days: checkboxesToWorkDays(workDays),
          public_holidays: [...publicHolidays],
        })
      }
      logger.info('Settings saved')
      setSaveMsg('Settings saved ✓')
      setTimeout(() => setSaveMsg(''), 2500)
    } catch (err) {
      logger.error('Failed to save settings', err)
      const msg = apiErrorMessage(err, 'Failed to save settings.')
      setSaveErr(msg)
      if (!(options.quietAuthToast === true && err?.type === 'AUTH')) {
        toast.error(msg, apiErrorToastOptions(err))
      }
    }
  }, [
    aiEnabled,
    autoRescheduleOnEvent,
    deviationPenaltyWeight,
    language,
    lockInWindowMinutes,
    notifPushEnabled,
    publicHolidays,
    schedulingObjective,
    schedulingSupported,
    splitStrategy,
    theme,
    toast,
    workDays,
    workEndTime,
    workStartTime,
  ])

  const handleSaveRef = useRef(handleSave)
  useEffect(() => {
    handleSaveRef.current = handleSave
  }, [handleSave])

  const handleRefreshWorkCalendars = async () => {
    setRefreshCalendarsLoading(true)
    try {
      await schedulingApi.refreshWorkCalendars()
      toast.success('Work calendars refreshed.')
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Failed to refresh work calendars.'), apiErrorToastOptions(err))
    } finally {
      setRefreshCalendarsLoading(false)
    }
  }

  const testErpConnection = async () => {
    setErpTesting(true); setErpStatus('testing')
    await new Promise((r) => setTimeout(r, 2000)) // simulate test
    setErpTesting(false)
    // In real app: call a test endpoint; for now toggle based on whether endpoint is set
    const connected = erpEndpoint.startsWith('http')
    setErpStatus(connected ? 'connected' : 'disconnected')
    if (connected) setErpLastSync(new Date().toLocaleString())
  }

  const wrap = (setter) => (v) => { setter(v); scheduleSave() }

  if (loading) {
    return (
      <div className="flex-1 p-8 flex items-center justify-center text-ink-subtle gap-3">
        <span className="w-5 h-5 border-2 border-hairline border-t-primary rounded-full animate-spin" />
        Loading settings…
      </div>
    )
  }

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <PageHeader title="Settings" subtitle="Configure system preferences and integrations.">
        <div className="flex items-center gap-3">
          {saveMsg && (
            <span className="flex items-center gap-1.5 text-sm text-semantic-success">
              <span className="material-symbols-outlined text-base">check_circle</span>{saveMsg}
            </span>
          )}
          {saveErr && (
            <span className="text-sm text-red-500">{saveErr}</span>
          )}
          <button
            onClick={handleSave}
            className="flex items-center gap-2 h-9 px-4 bg-primary text-white text-sm font-semibold rounded-lg hover:bg-primary/90 transition-colors"
          >
            <span className="material-symbols-outlined text-base">save</span>Save Now
          </button>
        </div>
      </PageHeader>

      <div className="grid grid-cols-1 gap-12 mt-2">

        {/* ── User Preferences (UC-SS01) ──────────────────────────────────── */}
        <Section title="User Preferences">
          <SettingRow title="Theme" description="Choose between light and dark mode.">
            <ThemeToggle isDark={theme === 'dark'} onToggle={() => { toggleTheme(); scheduleSave() }} />
          </SettingRow>

          <SettingRow title="Language" description="Select your preferred interface language.">
            <select
              value={language}
              onChange={(e) => wrap(setLanguage)(e.target.value)}
              className="w-48 bg-surface-1 border border-hairline text-ink text-sm rounded-md py-2 px-3 focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {LANG_OPTIONS.map(({ code, label }) => (
                <option key={code} value={code}>{label}</option>
              ))}
            </select>
          </SettingRow>

          <SettingRow title="AI Features" description="Enable AI-assisted scheduling and analytics.">
            <Toggle checked={aiEnabled} onChange={wrap(setAiEnabled)} />
          </SettingRow>

          <SettingRow title="Timezone" description="Select the timezone for scheduling and reports.">
            <select
              value={timezone}
              onChange={(e) => wrap(setTimezone)(e.target.value)}
              className="w-48 bg-surface-1 border border-hairline text-ink text-sm rounded-md py-2 px-3 focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {['UTC-8', 'UTC-5', 'UTC+0', 'UTC+1', 'UTC+8', 'UTC+9'].map((tz) => <option key={tz}>{tz}</option>)}
            </select>
          </SettingRow>
        </Section>

        {/* ── Notifications (UC-SS01) ─────────────────────────────────────── */}
        <Section title="Notification Settings">
          <SettingRow title="Push Notifications" description="Enable in-app push notifications.">
            <Toggle checked={notifPushEnabled} onChange={wrap(setNotifPushEnabled)} />
          </SettingRow>
          <SettingRow title="Email Alerts" description="Receive critical alerts via email.">
            <Toggle checked={notifEmail} onChange={wrap(setNotifEmail)} />
          </SettingRow>

          <div className="pt-2 border-t border-hairline">
            <p className="text-xs font-semibold text-ink-subtle uppercase tracking-wider mb-4">
              Notify on
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {[
                { label: 'Job Completed', val: notifJobComplete, set: setNotifJobComplete },
                { label: 'Maintenance Alert', val: notifMaintAlert, set: setNotifMaintAlert },
                { label: 'Low Stock Warning', val: notifLowStock, set: setNotifLowStock },
                { label: 'Machine Downtime', val: notifDowntime, set: setNotifDowntime },
              ].map(({ label, val, set }) => (
                <label key={label} className="flex items-center justify-between gap-4 py-2 px-3 rounded-lg bg-surface-1 cursor-pointer hover:bg-surface-2 transition-colors">
                  <span className="text-sm text-ink-muted">{label}</span>
                  <Toggle checked={val} onChange={wrap(set)} />
                </label>
              ))}
            </div>
          </div>
        </Section>

        {/* ── System Settings ──────────────────────────────────────────────── */}
        <Section title="System Settings">
          <SettingRow title="Simulation Mode" description="Use simulated data for testing without affecting production records.">
            <Toggle checked={simulationMode} onChange={wrap(setSimulationMode)} />
          </SettingRow>

          <SettingRow title="Auto-Save Interval" description="How often to auto-save form drafts (seconds).">
            <div className="flex items-center gap-2">
              <input
                type="number" min={5} max={300} step={5}
                value={autoSaveInterval}
                onChange={(e) => wrap(setAutoSaveInterval)(Number(e.target.value))}
                className="w-20 px-3 py-2 rounded-lg border border-hairline bg-surface-1 text-ink text-sm focus:outline-none focus:ring-2 focus:ring-primary transition-colors"
              />
              <span className="text-sm text-ink-subtle">seconds</span>
            </div>
          </SettingRow>

          <SettingRow title="Data Retention" description="How many days to keep production logs and reports.">
            <div className="flex items-center gap-2">
              <input
                type="number" min={30} max={730} step={30}
                value={dataRetentionDays}
                onChange={(e) => wrap(setDataRetentionDays)(Number(e.target.value))}
                className="w-20 px-3 py-2 rounded-lg border border-hairline bg-surface-1 text-ink text-sm focus:outline-none focus:ring-2 focus:ring-primary transition-colors"
              />
              <span className="text-sm text-ink-subtle">days</span>
            </div>
          </SettingRow>
        </Section>

        {/* ── Scheduling ───────────────────────────────────────────────────── */}
        <Section title="Scheduling">
          {schedulingSupported ? (
            <>
              <SettingRow title="Lock-in window (minutes)" description="Time window within which slots are locked from rescheduling.">
                <input
                  type="number"
                  min={0}
                  max={1440}
                  value={lockInWindowMinutes}
                  onChange={(e) => wrap(setLockInWindowMinutes)(Number(e.target.value) || 240)}
                  className="w-24 px-3 py-2 rounded-lg border border-hairline bg-surface-1 text-ink text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </SettingRow>
              <SettingRow title="Deviation penalty weight" description="Weight for schedule deviation penalty in optimization.">
                <input
                  type="number"
                  min={0}
                  max={5}
                  step={0.05}
                  value={deviationPenaltyWeight}
                  onChange={(e) => wrap(setDeviationPenaltyWeight)(parseFloat(e.target.value) || 0.25)}
                  className="w-24 px-3 py-2 rounded-lg border border-hairline bg-surface-1 text-ink text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </SettingRow>
              <SettingRow title="Split Strategy" description="How to split parallel steps when scheduling.">
                <select
                  value={splitStrategy}
                  onChange={(e) => wrap(setSplitStrategy)(e.target.value)}
                  className="w-56 bg-surface-1 border border-hairline text-ink text-sm rounded-md py-2 px-3 focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="equal">Equal</option>
                  <option value="proportional">Proportional</option>
                  <option value="manual">Manual</option>
                  <option value="min_time">Min Time</option>
                  <option value="priority">Priority</option>
                </select>
              </SettingRow>
              <SettingRow title="Optimization Objective" description="Goal for the scheduling solver.">
                <select
                  value={schedulingObjective}
                  onChange={(e) => wrap(setSchedulingObjective)(e.target.value)}
                  className="w-56 bg-surface-1 border border-hairline text-ink text-sm rounded-md py-2 px-3 focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="minimize_tardiness">Minimize Tardiness</option>
                  <option value="minimize_makespan">Minimize Makespan</option>
                  <option value="balance_load">Balance Load</option>
                  <option value="maximize_utilization">Maximize Utilization</option>
                </select>
              </SettingRow>
              <SettingRow title="Auto-reschedule on Events" description="Automatically reschedule when machine down, job delay, or urgent insert events are emitted.">
                <Toggle checked={autoRescheduleOnEvent} onChange={wrap(setAutoRescheduleOnEvent)} />
              </SettingRow>
              <SettingRow title="24-hour non-stop operation" description="Enable full-day, all-week scheduling (00:00 to 23:59, Mon–Sun).">
                <Toggle
                  checked={wholeDayOperation}
                  onChange={(enabled) => {
                    setWholeDayOperation(enabled)
                    if (enabled) {
                      setWorkStartTime('00:00')
                      setWorkEndTime('23:59')
                      setWorkDays(ALL_DAYS)
                    }
                    scheduleSave()
                  }}
                />
              </SettingRow>
              <SettingRow title="Work start time" description="Daily shift start (24h).">
                <input
                  type="time"
                  value={workStartTime}
                  onChange={(e) => wrap(setWorkStartTime)(e.target.value)}
                  disabled={wholeDayOperation}
                  className="w-28 px-3 py-2 rounded-lg border border-hairline bg-surface-1 text-ink text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </SettingRow>
              <SettingRow title="Work end time" description="Daily shift end (24h). Must be after start.">
                <input
                  type="time"
                  value={workEndTime}
                  onChange={(e) => wrap(setWorkEndTime)(e.target.value)}
                  disabled={wholeDayOperation}
                  className="w-28 px-3 py-2 rounded-lg border border-hairline bg-surface-1 text-ink text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </SettingRow>
              <SettingRow title="Workdays" description="Days when work is scheduled (Mon–Sat typical).">
                <div className="flex flex-wrap gap-2">
                  {[
                    { key: 'mon', label: 'Mon' },
                    { key: 'tue', label: 'Tue' },
                    { key: 'wed', label: 'Wed' },
                    { key: 'thu', label: 'Thu' },
                    { key: 'fri', label: 'Fri' },
                    { key: 'sat', label: 'Sat' },
                    { key: 'sun', label: 'Sun' },
                  ].map(({ key, label }) => (
                    <label key={key} className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-surface-1 cursor-pointer hover:bg-surface-2 text-sm">
                      <input
                        type="checkbox"
                        checked={workDays[key]}
                        disabled={wholeDayOperation}
                        onChange={(e) => {
                          setWorkDays(prev => ({ ...prev, [key]: e.target.checked }))
                          scheduleSave()
                        }}
                        className="rounded border-hairline text-primary focus:ring-primary"
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </SettingRow>
              <SettingRow title="Public holidays" description="Dates when no work is scheduled.">
                <div className="space-y-2">
                  <div className="flex gap-2">
                    <input
                      type="date"
                      value={newHolidayDate}
                      onChange={(e) => setNewHolidayDate(e.target.value)}
                      className="w-36 px-3 py-2 rounded-lg border border-hairline bg-surface-1 text-ink text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        if (!newHolidayDate) return
                        const d = newHolidayDate
                        if (!publicHolidays.includes(d)) {
                          setPublicHolidays(prev => [...prev, d].sort())
                          scheduleSave()
                        }
                        setNewHolidayDate('')
                      }}
                      disabled={!newHolidayDate}
                      className="px-3 py-2 rounded-lg bg-surface-1 border border-hairline text-ink text-sm font-medium hover:bg-surface-2 disabled:opacity-50"
                    >
                      Add
                    </button>
                  </div>
                  {publicHolidays.length > 0 && (
                    <ul className="flex flex-wrap gap-1.5">
                      {publicHolidays.map((d) => (
                        <li key={d} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-surface-1 text-sm">
                          {d}
                          <button
                            type="button"
                            onClick={() => {
                              setPublicHolidays(prev => prev.filter(x => x !== d))
                              scheduleSave()
                            }}
                            className="p-0.5 rounded text-ink-subtle hover:text-ink-muted hover:bg-red-50 dark:hover:bg-red-900/20"
                            aria-label={`Remove ${d}`}
                          >
                            <span className="material-symbols-outlined text-base">close</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </SettingRow>
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleRefreshWorkCalendars}
                  disabled={refreshCalendarsLoading}
                  className="flex items-center gap-2 h-9 px-4 bg-surface-1 border border-hairline text-ink text-sm font-medium rounded-lg hover:bg-surface-2 transition-colors disabled:opacity-50"
                >
                  {refreshCalendarsLoading ? (
                    <><span className="w-4 h-4 border-2 border-gray-400/30 border-t-gray-600 rounded-full animate-spin" />Refreshing…</>
                  ) : (
                    <><span className="material-symbols-outlined text-base">update</span>Refresh work calendars</>
                  )}
                </button>
              </div>
            </>
          ) : (
            <div className="px-4 py-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg text-sm text-blue-800 dark:text-blue-300">
              <p className="font-medium mb-1">Configured via backend environment</p>
              <p className="text-xs text-primary">
                Scheduling options (AI_SPLIT_STRATEGY, AI_OBJECTIVE, AI_AUTO_RESCHEDULE_ON_EVENT) are set by the server admin. Contact your administrator to change these settings.
              </p>
            </div>
          )}
        </Section>

        {/* ── ERP / MES Integration (UC-SS03) ─────────────────────────────── */}
        <Section title="ERP / MES Integration">
          <div className="mb-4 flex items-center gap-3">
            <ErpStatusBadge status={erpStatus} />
            {erpLastSync && (
              <p className="text-xs text-ink-subtle">Last sync: {erpLastSync}</p>
            )}
          </div>

          <SettingRow title="ERP System" description="Select the ERP/MES system to integrate with.">
            <select
              value={erpSystem}
              onChange={(e) => wrap(setErpSystem)(e.target.value)}
              className="w-56 bg-surface-1 border border-hairline text-ink text-sm rounded-md py-2 px-3 focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">Select ERP…</option>
              {ERP_SYSTEMS.map((s) => <option key={s}>{s}</option>)}
            </select>
          </SettingRow>

          <SettingRow title="API Endpoint" description="URL for the ERP/MES synchronisation endpoint.">
            <input
              type="url"
              value={erpEndpoint}
              onChange={(e) => wrap(setErpEndpoint)(e.target.value)}
              placeholder="https://erp.company.com/api/sync"
              className="w-80 px-3 py-2 rounded-lg border border-hairline bg-surface-1 text-ink text-sm placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-primary transition-colors"
            />
          </SettingRow>

          <div className="pt-2">
            <button
              onClick={testErpConnection}
              disabled={erpTesting || !erpSystem}
              className="flex items-center gap-2 h-9 px-4 bg-surface-1 border border-hairline text-ink text-sm font-medium rounded-lg hover:bg-surface-2 transition-colors disabled:opacity-50"
            >
              {erpTesting
                ? <><span className="w-4 h-4 border-2 border-gray-400/30 border-t-gray-600 rounded-full animate-spin" />Testing…</>
                : <><span className="material-symbols-outlined text-base">sync</span>Test Connection</>
              }
            </button>
          </div>
        </Section>

        {/* ── About ───────────────────────────────────────────────────────── */}
        <Section title="About eMAS">
          <div className="flex items-center gap-6">
            <div>
              <p className="text-sm font-semibold text-ink">eMAS — Enterprise Manufacturing Automation System</p>
              <p className="text-xs text-ink-subtle mt-0.5">Version 1.0.0 · Build 2026.02</p>
            </div>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-semantic-success/20 text-green-700">
              <span className="w-1.5 h-1.5 bg-green-500 rounded-full" />API Connected
            </span>
            <span className="text-xs text-ink-subtle">Backend: http://localhost:8080/api/v1</span>
          </div>
        </Section>
      </div>
    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────
const Section = ({ title, children }) => (
  <div>
    <h2 className="text-xl font-semibold text-ink border-b border-hairline pb-3 mb-6">
      {title}
    </h2>
    <div className="space-y-6">{children}</div>
  </div>
)

const ErpStatusBadge = ({ status }) => {
  const cfg = {
    connected: { bg: 'bg-semantic-success/20 ', text: 'text-green-700 ', dot: 'bg-green-500', label: 'Connected' },
    disconnected: { bg: 'bg-surface-1', text: 'text-ink-subtle', dot: 'bg-gray-400', label: 'Disconnected' },
    testing: { bg: 'bg-blue-100 dark:bg-blue-900/20', text: 'text-blue-700 ', dot: 'bg-blue-500', label: 'Testing…' },
  }
  const c = cfg[status] || cfg.disconnected
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${c.bg} ${c.text}`}>
      <span className={`w-2 h-2 rounded-full ${c.dot} ${status === 'testing' ? 'animate-pulse' : ''}`} />
      {c.label}
    </span>
  )
}

export default Settings
