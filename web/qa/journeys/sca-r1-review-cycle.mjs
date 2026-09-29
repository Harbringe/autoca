import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const senior = await login('senior')

const books0 = await staff.get(`api/v1/clients/${cid}/books/`)
console.log('books before request', books0.status, JSON.stringify(books0.body).slice(0,400))

const req = await staff.post(`api/v1/clients/${cid}/books/request/`, { note: 'April books ready for review' })
console.log('request', req.status, JSON.stringify(req.body).slice(0,400))

// staff try sign-off / return (must be 403)
const staffSignoff = await staff.post(`api/v1/clients/${cid}/books/sign-off/`, {})
console.log('staff sign-off (expect 403)', staffSignoff.status, JSON.stringify(staffSignoff.body).slice(0,200))
const staffReturn = await staff.post(`api/v1/clients/${cid}/books/return/`, { note: 'x' })
console.log('staff return (expect 403)', staffReturn.status, JSON.stringify(staffReturn.body).slice(0,200))

const ret = await senior.post(`api/v1/clients/${cid}/books/return/`, { note: 'Please add narration to the salary entry' })
console.log('senior return', ret.status, JSON.stringify(ret.body).slice(0,400))

const booksAfterReturn = await staff.get(`api/v1/clients/${cid}/books/`)
console.log('staff sees after return', JSON.stringify(booksAfterReturn.body).slice(0,500))

console.log('serverErrors', [staff, senior].flatMap(s=>s.serverErrors()))
