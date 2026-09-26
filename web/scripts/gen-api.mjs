// Regenerates web/openapi.yaml from Django and the TypeScript types from it.
// The schema is the contract between the two projects; CI fails if the checked-in
// copy has drifted from what the backend now produces.
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const web = resolve(here, '..')
const root = resolve(web, '..')
const python = process.env.PYTHON ?? 'python'

execFileSync(python, ['manage.py', 'spectacular', '--file', resolve(web, 'openapi.yaml')], {
  cwd: root,
  stdio: 'inherit',
})
execFileSync(
  process.execPath,
  [resolve(web, 'node_modules/openapi-typescript/bin/cli.js'), 'openapi.yaml', '-o', 'src/api/schema.d.ts'],
  { cwd: web, stdio: 'inherit' },
)
