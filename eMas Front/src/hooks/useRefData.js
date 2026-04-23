/**
 * useRefData — fetch a reference/lookup list from the API once on mount.
 *
 * @param {() => Promise<{ data: any[], error: string|null }>} fetcher
 *   One of the referenceApi.*. list() calls.
 * @param {(item: any) => string} [toLabel]
 *   Optional transformer from API item → display string.
 *   Defaults to extracting .name or the string itself.
 *
 * @returns {{ options: string[], loading: boolean, error: string|null }}
 */
import { useState, useEffect } from 'react'

export function useRefData(fetcher, toLabel) {
  const [options, setOptions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetcher().then(({ data, error: err }) => {
      if (cancelled) return
      if (err) {
        setError(err)
        setOptions([])
      } else {
        const mapper = toLabel ?? ((item) => (typeof item === 'string' ? item : (item.display || item.name || String(item.id ?? ''))))
        setOptions(data.map(mapper).filter(Boolean))
      }
      setLoading(false)
    })

    return () => { cancelled = true }
  }, []) // intentionally empty — reference data is global, fetch once

  return { options, loading, error }
}

/**
 * useRefObjects — like useRefData but returns the full objects, not just labels.
 * Useful when you need more than just the display name (e.g. step-types with
 * default_machine_type).
 */
export function useRefObjects(fetcher) {
  const [objects, setObjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetcher().then(({ data, error: err }) => {
      if (cancelled) return
      if (err) {
        setError(err)
        setObjects([])
      } else {
        setObjects(data)
      }
      setLoading(false)
    })

    return () => { cancelled = true }
  }, [])

  return { objects, loading, error }
}
