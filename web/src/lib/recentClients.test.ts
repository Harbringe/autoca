import { MAX_RECENT, parseIds, pushRecent, recordRecentClient, resetClientMemory, toggleClientPin, togglePin } from './recentClients'

describe('recent clients', () => {
  it('puts the newest first, once, and keeps five', () => {
    expect(pushRecent(['a', 'b'], 'c')).toEqual(['c', 'a', 'b'])
    expect(pushRecent(['a', 'b', 'c'], 'c')).toEqual(['c', 'a', 'b'])
    expect(pushRecent(['a', 'b', 'c', 'd', 'e'], 'f')).toEqual(['f', 'a', 'b', 'c', 'd'])
    expect(MAX_RECENT).toBe(5)
  })
  it('pins and unpins in the order chosen', () => {
    expect(togglePin(['a'], 'b')).toEqual(['a', 'b'])
    expect(togglePin(['a', 'b'], 'a')).toEqual(['b'])
  })
  it('reads only a list of text from storage', () => {
    expect(parseIds('["a","b","a",3,""]')).toEqual(['a', 'b'])
    expect(parseIds('{"a":1}')).toEqual([])
    expect(parseIds('not json')).toEqual([])
    expect(parseIds(null)).toEqual([])
  })
})

describe('the stored lists', () => {
  beforeEach(() => resetClientMemory())
  it('survive in localStorage', () => {
    recordRecentClient('a')
    recordRecentClient('b')
    toggleClientPin('a')
    expect(JSON.parse(localStorage.getItem('autoca.recentClients')!)).toEqual(['b', 'a'])
    expect(JSON.parse(localStorage.getItem('autoca.pinnedClients')!)).toEqual(['a'])
  })
  it('carry on when storage refuses', () => {
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => recordRecentClient('z')).not.toThrow()
    expect(() => toggleClientPin('z')).not.toThrow()
    set.mockRestore()
  })
})
