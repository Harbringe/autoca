import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The browser only ever talks to one origin. In development that is this dev
// server, which forwards the API and the auth endpoints to Django; in
// production the static host does the same with a rewrite. That keeps the
// session cookie first-party and CSRF the ordinary same-site flow, with no CORS.
const backend = process.env.VITE_DEV_API ?? 'http://127.0.0.1:8000'
const forwarded = { target: backend, changeOrigin: true }

export default defineConfig({
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    strictPort: true,
    // /admin and /static are the platform owner's panel, which is not part of this app.
    proxy: { '/api': forwarded, '/auth': forwarded, '/healthz': forwarded, '/admin': forwarded, '/static': forwarded },
  },
  build: { target: 'es2022', sourcemap: true },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
