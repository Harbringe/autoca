import { describe, expect, it } from 'vitest'
import { applyMask, maskProblem } from './masks'

describe('masks', () => {
  it('uppercases, strips and limits as typed', () => {
    expect(applyMask('pan', 'aabca-1234f99')).toBe('AABCA1234F')
    expect(applyMask('gstin', '27aabca1234f1z5xyz')).toBe('27AABCA1234F1Z5')
  })
  it('checks the shape on blur, and says nothing about an empty field', () => {
    expect(maskProblem('pan', 'AABCA1234F')).toBeNull()
    expect(maskProblem('pan', 'AABCA123')).not.toBeNull()
    expect(maskProblem('gstin', '27AABCA1234F1Z5')).toBeNull()
    expect(maskProblem('gstin', '27AABCA1234F1A5')).not.toBeNull()
    expect(maskProblem('gstin', '')).toBeNull()
  })
})
