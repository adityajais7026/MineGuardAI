import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

// Phase 1 placeholder screen. Routers, auth context and pages arrive in
// later phases; this verifies the toolchain end-to-end.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
