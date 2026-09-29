import { request } from '@playwright/test'
import { PASSWORD, PEOPLE } from '../lib/session.mjs'
const API = 'http://127.0.0.1:8000'
const PL = 'fixatedfixatedfixatedfixated0000'
// Planted id set via a real cookie jar, as an attacker-controlled sibling/subdomain or XSS would.
const fx = await request.newContext({ baseURL: API, storageState: { cookies: [{ name:'sessionid', value: PL, domain:'127.0.0.1', path:'/', httpOnly:true, secure:false, sameSite:'Lax', expires:-1 }], origins: [] } })
const ft = (await (await fx.get('/auth/csrf/')).json()).csrfToken
const fl = await fx.post('/auth/login/', { headers: { 'X-CSRFToken': ft }, data: { email: PEOPLE.reader, password: PASSWORD } })
console.log('login', fl.status(), (await fl.text()).slice(0,150))
const fs = (await fx.storageState()).cookies.find(c=>c.name==='sessionid')?.value
console.log('session id after login differs from planted:', fs !== PL)
const c3 = await request.newContext({ baseURL: API, storageState: { cookies: [{ name:'sessionid', value: PL, domain:'127.0.0.1', path:'/', expires:-1, httpOnly:true, secure:false, sameSite:'Lax' }], origins: [] } })
console.log('attacker with planted id /me:', (await c3.get('/api/v1/me/')).status())
console.log('victim /me:', (await fx.get('/api/v1/me/')).status())
