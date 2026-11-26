/**
 * Global mine selection (spec section 12).
 *
 * One selected coal mine for the whole app, kept in localStorage so it
 * survives navigation and reloads. The LIST of selectable mines is always
 * fetched through the backend mine-list endpoint, which applies the user's
 * scope: admins see every mine, Mine Managers only managed mines, Safety
 * Officers / Government Officers only their permitted mines. The frontend
 * never invents or trusts its own mine_id — it only remembers which of the
 * backend-visible mines is active, and only admins may choose "All mines".
 *
 * Selection resets when the signed-in user changes (login/logout).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { minesApi } from '../api/endpoints'
import { useAuth } from './AuthContext'
import type { Mine } from '../api/types'

interface MineSelectionValue {
  /** Selected mine id, or null = "All mines" (admins only). */
  mineId: string | null
  setMineId: (id: string | null) => void
  /** Backend-scoped mines (already authorized for this user). */
  mines: Mine[]
  /** True once the scoped mine list has loaded. */
  loaded: boolean
}

const STORAGE_KEY = 'mineguard.selected_mine_id'

const MineSelectionContext = createContext<MineSelectionValue | null>(null)

export function MineSelectionProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const [mineId, setMineIdState] = useState<string | null>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      return stored && stored !== '' ? stored : null
    } catch {
      return null
    }
  })
  const [mines, setMines] = useState<Mine[]>([])
  const [loaded, setLoaded] = useState(false)

  // Reset when the signed-in user changes.
  useEffect(() => {
    if (!user) {
      setMineIdState(null)
      setMines([])
      setLoaded(false)
    }
  }, [user?.id])

  // Lazy-load the backend-scoped mine list while signed in.
  useEffect(() => {
    if (!user) return
    let cancelled = false
    minesApi.list({ limit: 200 })
      .then((r) => {
        if (cancelled) return
        setMines(r.items)
        setLoaded(true)
      })
      .catch(() => {
        if (!cancelled) setLoaded(true)
      })
    return () => { cancelled = true }
  }, [user?.id])

  // After the scoped list loads, drop a stored selection that is out of scope.
  useEffect(() => {
    if (!loaded || user?.role !== 'admin') return
    // Admins may pick any listed mine or none.
    if (mineId && mines.length > 0 && !mines.some((m) => m.id === mineId)) {
      setMineIdState(null)
    }
  }, [loaded, user?.role, mineId, mines])

  useEffect(() => {
    // Non-admins: their scope is authoritative — if the stored selection is
    // not in the scoped list, clear it once the list is loaded.
    if (!loaded || user?.role === 'admin') return
    if (mineId && mines.length > 0 && !mines.some((m) => m.id === mineId)) {
      setMineIdState(null)
    }
  }, [loaded, user, mineId, mines])

  const setMineId = useCallback((id: string | null) => {
    setMineIdState(id)
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id)
      else localStorage.removeItem(STORAGE_KEY)
    } catch {
      /* private browsing: selection lives for this session only */
    }
  }, [])

  const value = useMemo(() => ({ mineId, setMineId, mines, loaded }), [mineId, setMineId, mines, loaded])
  return <MineSelectionContext.Provider value={value}>{children}</MineSelectionContext.Provider>
}

export function useMineSelection(): MineSelectionValue {
  const ctx = useContext(MineSelectionContext)
  if (!ctx) throw new Error('useMineSelection must be used inside MineSelectionProvider')
  return ctx
}
