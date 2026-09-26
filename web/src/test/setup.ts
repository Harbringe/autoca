import '@testing-library/jest-dom/vitest'

// A browser resolves "/api/..." against the page it is on; the test runtime's Request does not,
// so tests talk to an absolute base. Set before any module reads it.
vi.stubEnv('VITE_API_BASE', 'http://localhost')
