/**
 * Reusable data-fetching hook: loading / error / refetch handling for any
 * async API call, so pages don't each reimplement request state.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

interface State<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useApiResource<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<State<T>>({ data: null, loading: true, error: null })
  // Keep the latest fetcher without making it a dependency (avoids loops).
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    fetcherRef
      .current()
      .then((data) => { if (!cancelled) setState({ data, loading: false, error: null }) })
      .catch((err: unknown) => {
        if (cancelled) return
        const message = err instanceof ApiError ? err.message : 'Unexpected error'
        setState({ data: null, loading: false, error: message })
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const refetch = useCallback(() => setTick((t) => t + 1), [])
  return { ...state, refetch }
}
