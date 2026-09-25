import { useEffect, useState } from 'react'

type BackendStatus = 'checking' | 'online' | 'offline'

// Phase 1 placeholder: pings the backend health endpoint through the Vite
// proxy so the frontend-backend wiring is proven before pages are built.
function App() {
  const [status, setStatus] = useState<BackendStatus>('checking')
  const [apiName, setApiName] = useState<string>('')

  useEffect(() => {
    fetch('/api/health')
      .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
      .then((data) => {
        setApiName(data.name ?? 'MineGuardAI API')
        setStatus('online')
      })
      .catch(() => setStatus('offline'))
  }, [])

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '3rem', textAlign: 'center' }}>
      <h1 style={{ color: '#f59e0b' }}>MineGuardAI</h1>
      <p>Mining safety, environmental monitoring &amp; compliance governance.</p>
      <p data-testid="backend-status">
        Backend: {status === 'online' ? '✅ online' : status === 'offline' ? '❌ offline' : '⏳ checking…'}
      </p>
      {apiName && <p><code>{apiName}</code> — dashboard UI coming in Phase 7-9.</p>}
    </main>
  )
}

export default App
