import { serverUrl } from './env'

export type Opener = (url: string) => void

let opener: Opener = (url) => {
  window.open(url, '_blank', 'noopener,noreferrer')
}

export function setOpener(next: Opener): void {
  opener = next
}

export function openExternal(url: string): void {
  opener(url)
}

/** The platform owner's panel lives on the server, outside this application. */
export function openPlatformAdmin(): void {
  opener(serverUrl('/admin/'))
}
