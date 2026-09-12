import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The built bundle is served by Django/WhiteNoise under STATIC_URL, so asset
// URLs are absolute under /static/app/. The application itself lives at /app/
// (see config/urls.py); the router's basename is set there, not here.
//
// In development `npm run dev` proxies the API to the Django dev server so
// the session cookie and CSRF flow are the real ones.
export default defineConfig({
  plugins: [react()],
  base: '/static/app/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
      '/healthz': 'http://127.0.0.1:8000',
    },
  },
})
