// Handing a file to the person using the app.
//
// A browser saves through an <a download>; a desktop shell shows a native
// "save as" dialog and writes the file itself. `saveFile` is the only way the
// rest of the application produces a file, so that difference lives here.

export type Saver = (name: string, blob: Blob) => Promise<void>

const browserSaver: Saver = async (name, blob) => {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  // The click has already started the save; releasing the URL after a tick
  // keeps browsers that read it lazily from losing the file.
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

let saver: Saver = browserSaver

export function setSaver(next: Saver): void {
  saver = next
}

export function saveFile(name: string, blob: Blob): Promise<void> {
  return saver(name, blob)
}

export function saveText(name: string, text: string, type = 'text/plain'): Promise<void> {
  return saveFile(name, new Blob([text], { type }))
}
