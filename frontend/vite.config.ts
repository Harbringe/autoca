import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Built: hashed assets land in dist/app/assets/ and are referenced as
// /static/app/assets/..., served by Django/WhiteNoise with frontend/dist as an
// *unprefixed* STATICFILES_DIRS entry. (A prefixed entry -- ("app", dist) --
// looks equivalent and is not: Django's FileSystemFinder compares the prefix
// with os.sep, so on Windows every /static/app/... lookup misses and the page
// loads with no script.) index.html is served for every /app/ route by
// core/spa.py, and the router's basename is /app.
//
// Dev: `npm run dev` serves the app at http://localhost:5173/app/ and proxies
// the API to the Django dev server, so the session cookie and CSRF flow are
// the real ones.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/static/' : '/app/',
  build: {
    outDir: 'dist',
    assetsDir: 'app/assets',
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
}))
