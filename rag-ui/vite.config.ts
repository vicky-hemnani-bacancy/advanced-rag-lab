import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The React dev server proxies /api to the FastAPI backend, so the app uses same-origin URLs in dev and in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8100' },
  },
})
