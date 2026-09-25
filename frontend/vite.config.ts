import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend URL is configurable so the same build works in dev and production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Frontend calls /api/... which is proxied to the FastAPI backend.
      '/api': {
        target: process.env.VITE_BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
