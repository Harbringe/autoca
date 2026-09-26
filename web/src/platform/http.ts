// The one fetch the application uses.
//
// On the web this is the browser's fetch, and the session cookie travels with
// it. In a desktop shell the webview's own origin is not the server's, so the
// implementation swaps to the shell's HTTP client, which keeps the cookie jar on
// the native side. Callers never know which.

type Fetch = (input: Request) => Promise<Response>

let impl: Fetch = (request) => fetch(request)

/** Install a different transport (the desktop shell does this once at startup). */
export function setTransport(next: Fetch): void {
  impl = next
}

export function send(request: Request): Promise<Response> {
  return impl(request)
}
