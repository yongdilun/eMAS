/**
 * RefSelect — a <select> that loads its options from a reference API endpoint.
 *
 * Props:
 *   value          current value (string)
 *   onChange       (value: string) => void
 *   fetcher        () => Promise<{data, error}>  — one of referenceApi.*.list
 *   toLabel        optional (item) => string
 *   placeholder    optional label for the blank first option
 *   className      tailwind classes for the <select>
 *   name           optional name attribute
 *   required       optional boolean
 *   allowCustom    if true, shows "Other (specify)…" option + text input below
 */
import { useState } from 'react'
import { useRefData } from '../../hooks/useRefData'

const CUSTOM_VAL = '__custom__'

export default function RefSelect({
  value,
  onChange,
  fetcher,
  toLabel,
  placeholder = 'Select…',
  className = '',
  name,
  required,
  allowCustom = false,
}) {
  const { options, loading, error } = useRefData(fetcher, toLabel)
  const [customMode, setCustomMode] = useState(false)
  const [customText, setCustomText] = useState('')

  // Sync: if an existing value isn't in the list, start in customMode
  const knownValues = options
  const showingCustom = allowCustom && (customMode || (value && !knownValues.includes(value) && value !== ''))

  const handleSelect = (e) => {
    if (e.target.value === CUSTOM_VAL) {
      setCustomMode(true)
      setCustomText('')
      onChange('')
    } else {
      setCustomMode(false)
      onChange(e.target.value)
    }
  }

  const selectValue = showingCustom ? CUSTOM_VAL : (value || '')

  const selectCls = `${className}${error ? ' border-red-400 dark:border-red-500' : ''}`

  return (
    <div>
      <select
        name={name}
        value={selectValue}
        onChange={handleSelect}
        className={selectCls}
        required={required}
        disabled={loading}
      >
        <option value="">{loading ? 'Loading…' : placeholder}</option>

        {options.map((opt) => (
          <option key={opt} value={opt} className="bg-white dark:bg-[#1b2528]">
            {opt}
          </option>
        ))}

        {/* If editing an existing value not in the list, surface it */}
        {!loading && value && !knownValues.includes(value) && !showingCustom && (
          <option value={value}>{value}</option>
        )}

        {allowCustom && (
          <option value={CUSTOM_VAL}>Other (specify below)…</option>
        )}
      </select>

      {/* Status messages below the select */}
      {error && (
        <p className="mt-1 text-xs text-red-500 dark:text-red-400 flex items-center gap-1">
          <span className="material-symbols-outlined text-sm">error</span>
          Failed to load options: {error}
        </p>
      )}
      {!loading && !error && options.length === 0 && (
        <p className="mt-1 text-xs text-amber-500 dark:text-amber-400">
          No options configured yet — contact admin or use &quot;Other&quot;.
        </p>
      )}

      {/* Custom text input shown when "Other" is selected */}
      {showingCustom && allowCustom && (
        <input
          type="text"
          className={`${className} mt-2`}
          placeholder="Enter custom value…"
          value={customText || (value || '')}
          autoFocus
          onChange={(e) => {
            setCustomText(e.target.value)
            onChange(e.target.value)
          }}
        />
      )}
    </div>
  )
}
