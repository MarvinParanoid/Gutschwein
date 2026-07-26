/**
 * Demo mode: the app running against a made-up dataset that lives in this tab
 * and nowhere else.
 *
 * The whole point is that a stranger with the link can poke at everything —
 * spend, comment, delete — without any of it reaching the family's data. That
 * guarantee is structural rather than a matter of permissions: in demo mode the
 * HTTP client is swapped for one that never leaves the page (see `demo/api.ts`),
 * so there is no request to authorise in the first place.
 */

const FLAG = 'sparschwein-demo'

// A shared link lands on /demo. The flag is what everything else reads, so the
// path is turned into one immediately and the address bar goes back to normal —
// otherwise a reload of /demo would look like a route the app does not have.
if (typeof window !== 'undefined' && window.location.pathname === '/demo') {
  sessionStorage.setItem(FLAG, '1')
  window.history.replaceState({}, '', '/')
}

/** Session storage, not local: closing the tab ends the demo. */
export function isDemo(): boolean {
  return typeof window !== 'undefined' && sessionStorage.getItem(FLAG) === '1'
}

export function startDemo(): void {
  sessionStorage.setItem(FLAG, '1')
  // A full reload rather than a state update: the API client is chosen once at
  // module load, and this way no real request can still be in flight.
  window.location.replace('/')
}

export function stopDemo(): void {
  sessionStorage.removeItem(FLAG)
  window.location.replace('/')
}
