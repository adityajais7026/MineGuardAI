/**
 * Offline-first inspection store (IndexedDB).
 *
 * Durable local persistence for field inspections:
 *  - survives page refresh and browser restart (IndexedDB, not memory);
 *  - keeps full inspection payloads (checklist results, GPS, notes, metadata);
 *  - keeps evidence METADATA (files themselves require storage access that is
 *    unavailable offline in this build — see the final report note);
 *  - tracks sync state per record: pending | syncing | synced | failed;
 *  - never deletes failed records (SYNC FAILED keeps the data).
 *
 * Idempotency: each inspection gets a client_guid (UUID) this is stable
 * across retries; the server's sync endpoint deduplicates on it.
 */
import { governanceApi } from '../api/endpoints'

const DB_NAME = 'mineguardai-offline'
const DB_VERSION = 1
const STORE_DRAFTS = 'drafts'
const STORE_META = 'meta'

export type SyncState = 'pending' | 'syncing' | 'synced' | 'failed'

export interface OfflineChecklistResult {
  itemId: string
  label: string
  position: number
  result: 'pass' | 'fail' | 'na' | 'unknown' | null
  comment?: string
}

export interface OfflineInspection {
  client_guid: string
  mine_id: string
  mine_name?: string
  template_id: string
  template_name?: string
  inspection_type: string
  inspection_id?: string // server id once started online
  checklist: OfflineChecklistResult[]
  results: Record<string, { result: string; comment?: string }> // by itemId
  gps?: { latitude: number; longitude: number } | null
  description?: string
  created_at: string
  updated_at: string
  sync_state: SyncState
  sync_error?: string
  server_inspection_id?: string
}

export interface OfflineEvidenceMeta {
  client_guid: string
  kind: string
  target_id: string
  media_type: 'image' | 'video' | 'audio' | 'document'
  original_filename: string
  size_bytes: number
  mime_type: string
  created_at: string
  sync_state: SyncState
}

let dbPromise: Promise<IDBDatabase> | null = null

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE_DRAFTS)) {
        const store = db.createObjectStore(STORE_DRAFTS, { keyPath: 'client_guid' })
        store.createIndex('sync_state', 'sync_state')
        store.createIndex('updated_at', 'updated_at')
      }
      if (!db.objectStoreNames.contains(STORE_META)) {
        db.createObjectStore(STORE_META, { keyPath: 'key' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
  return dbPromise
}

function tx<T>(storeName: string, mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const transaction = db.transaction(storeName, mode)
        const request = fn(transaction.objectStore(storeName))
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error)
      }),
  )
}

// ---------------------------------------------------------------------------
// Drafts
// ---------------------------------------------------------------------------

export const offlineStore = {
  async available(): Promise<boolean> {
    return typeof indexedDB !== 'undefined'
  },

  async putDraft(draft: OfflineInspection): Promise<void> {
    await tx(STORE_DRAFTS, 'readwrite', (s) => s.put(draft) as unknown as IDBRequest<void>)
  },

  async getDraft(clientGuid: string): Promise<OfflineInspection | null> {
    const row = await tx<OfflineInspection | undefined>(STORE_DRAFTS, 'readonly', (s) => s.get(clientGuid))
    return row ?? null
  },

  async listDrafts(): Promise<OfflineInspection[]> {
    const rows = await tx<OfflineInspection[]>(STORE_DRAFTS, 'readonly', (s) => s.getAll() as IDBRequest<OfflineInspection[]>)
    return (rows ?? []).sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  },

  async deleteDraft(clientGuid: string): Promise<void> {
    await tx(STORE_DRAFTS, 'readwrite', (s) => s.delete(clientGuid) as unknown as IDBRequest<void>)
  },

  async pendingCount(): Promise<number> {
    const rows = await this.listDrafts()
    return rows.filter((r) => r.sync_state === 'pending' || r.sync_state === 'failed').length
  },

  // -----------------------------------------------------------------------
  // GPS capture (never fakes: absent coords mean "unavailable")
  // -----------------------------------------------------------------------

  async captureGps(): Promise<{ latitude: number; longitude: number; accuracy: number } | null> {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return null
    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy }),
        () => resolve(null), // permission denied / unavailable -> null, NOT fake coords
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 },
      )
    })
  },
}

// ---------------------------------------------------------------------------
// Synchronisation: push every pending draft, idempotently.
// ---------------------------------------------------------------------------

export type ConnectionStatus = 'online' | 'offline'
export type SyncStatus = 'idle' | 'syncing' | 'synced' | 'sync_error'

let syncing = false

function buildSyncPayload(draft: OfflineInspection) {
  const resultsByPosition: Record<string, { result: string | null; comment?: string }> = {}
  for (const item of draft.checklist) {
    const r = draft.results[item.itemId]
    if (r) resultsByPosition[String(item.position)] = { result: r.result, comment: r.comment }
  }
  return {
    mine_id: draft.mine_id,
    template_id: draft.template_id,
    description: draft.description ?? null,
    gps: draft.gps ?? null,
    results: resultsByPosition,
  }
}

export const offlineSync = {
  isSyncing: () => syncing,

  async syncPending(): Promise<{ pushed: number; failed: number }> {
    if (syncing) return { pushed: 0, failed: 0 }
    syncing = true
    let pushed = 0
    let failed = 0
    try {
      const drafts = (await offlineStore.listDrafts()).filter(
        (d) => d.sync_state === 'pending' || d.sync_state === 'failed',
      )
      for (const draft of drafts) {
        draft.sync_state = 'syncing'
        await offlineStore.putDraft(draft)
        try {
          const res = await governanceApi.syncPush({
            client_guid: draft.client_guid,
            mine_id: draft.mine_id,
            entity_type: 'inspection',
            payload: buildSyncPayload(draft),
          })
          if (res.status === 'synced' || res.status === 'duplicate') {
            draft.sync_state = 'synced'
            draft.server_inspection_id = res.result_ref_id ?? draft.server_inspection_id
            pushed += 1
          } else {
            draft.sync_state = 'failed'
            draft.sync_error = res.error ?? 'unknown error'
            failed += 1
          }
        } catch (err) {
          draft.sync_state = 'failed'
          draft.sync_error = err instanceof Error ? err.message : String(err)
          failed += 1
        }
        await offlineStore.putDraft(draft)
      }
    } finally {
      syncing = false
    }
    return { pushed, failed }
  },

  /** Manual retry entry point used by the UI. */
  async retryFailed(): Promise<void> {
    const drafts = await offlineStore.listDrafts()
    for (const d of drafts) {
      if (d.sync_state === 'failed') {
        d.sync_state = 'pending'
        await offlineStore.putDraft(d)
      }
    }
  },
}

// ---------------------------------------------------------------------------
// Connectivity watcher (window events + first sync on reconnect)
// ---------------------------------------------------------------------------

const listeners = new Set<(status: ConnectionStatus, sync: SyncStatus) => void>()
let currentConnection: ConnectionStatus =
  typeof navigator !== 'undefined' ? (navigator.onLine ? 'online' : 'offline') : 'offline'

function notify(status: ConnectionStatus, sync: SyncStatus) {
  for (const fn of listeners) fn(status, sync)
}

export const connectivity = {
  current: () => currentConnection,
  subscribe(fn: (status: ConnectionStatus, sync: SyncStatus) => void): () => void {
    listeners.add(fn)
    fn(currentConnection, syncing ? 'syncing' : 'idle')
    return () => {
      listeners.delete(fn)
    }
  },
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => {
    currentConnection = 'online'
    notify('online', 'syncing')
    void offlineSync
      .syncPending()
      .then(({ failed }) => notify('online', failed > 0 ? 'sync_error' : 'synced'))
      .catch(() => notify('online', 'sync_error'))
  })
  window.addEventListener('offline', () => {
    currentConnection = 'offline'
    notify('offline', 'idle')
  })
}
