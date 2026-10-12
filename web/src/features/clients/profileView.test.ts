import { describe, expect, it } from 'vitest'
import type { ClientProfile } from '@/api/queries/clients'
import { draftOf, patchOf, type FieldDef } from './profileView'

const profile = {
  id: 'c1',
  name: 'Acme',
  trade_name: 'Acme Traders',
  client_since: '2021-04-01',
  incorporated_on: null,
  pan: 'ABCDE1234F',
  contact_name: '',
} as unknown as ClientProfile

const fields: FieldDef[] = [
  { key: 'trade_name', label: 'Trade name', kind: 'text' },
  { key: 'client_since', label: 'Client since', kind: 'date' },
  { key: 'incorporated_on', label: 'Incorporated on', kind: 'date' },
  { key: 'pan', label: 'PAN', kind: 'id' },
  { key: 'contact_name', label: 'Contact', kind: 'text' },
]

describe('draftOf', () => {
  it('shows dates as DD-MM-YYYY and missing values as empty', () => {
    expect(draftOf(profile, fields)).toEqual({ trade_name: 'Acme Traders', client_since: '01-04-2021', incorporated_on: '', pan: 'ABCDE1234F', contact_name: '' })
  })
})

describe('patchOf', () => {
  it('sends nothing when nothing changed', () => {
    expect(patchOf(profile, fields, draftOf(profile, fields)).patch).toEqual({})
  })

  it('sends only what changed, with dates as ISO and ids in capitals', () => {
    const draft = { ...draftOf(profile, fields), contact_name: ' Meera ', incorporated_on: '15-06-2019', pan: 'abcde1234g' }
    expect(patchOf(profile, fields, draft).patch).toEqual({ contact_name: 'Meera', incorporated_on: '2019-06-15', pan: 'ABCDE1234G' })
  })

  it('clears a date with null and a text field with an empty string', () => {
    const draft = { ...draftOf(profile, fields), client_since: '', trade_name: '' }
    expect(patchOf(profile, fields, draft).patch).toEqual({ client_since: null, trade_name: '' })
  })

  it('names a date it cannot read', () => {
    const draft = { ...draftOf(profile, fields), incorporated_on: '31-02-2020x' }
    expect(patchOf(profile, fields, draft).problem).toMatch(/Incorporated on/)
  })
})
