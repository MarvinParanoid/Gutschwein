/**
 * What the service worker keeps on this device, from the page's side.
 *
 * The caches themselves are configured in vite.config.ts; the names here must
 * match it. Every function is a no-op where Cache Storage does not exist — an
 * insecure origin, an old WebView, a unit test.
 */

/** Pictures; before barcodes were versioned, barcodes as well. */
export const IMAGES_CACHE = 'gutschwein-cards'
export const BARCODES_CACHE = 'gutschwein-barcodes'
export const API_CACHE = 'gutschwein-api'

function storage(): CacheStorage | undefined {
  return typeof caches === 'undefined' ? undefined : caches
}

/**
 * One cache operation at a time. `caches.open` creates the cache it opens, so the
 * startup housekeeping, interleaved with a purge, re-created a cache the purge had
 * just deleted. In a queue the purge always comes after and has the last word.
 */
let queue: Promise<unknown> = Promise.resolve()

function serially(operation: () => Promise<void>): Promise<void> {
  const run = queue.then(operation, operation)
  queue = run.catch(() => undefined)
  return run
}

/**
 * Removes barcodes cached by addresses without a version.
 *
 * Before T5 barcodes shared the pictures' cache under `/api/barcodes/<image>`, an
 * address that kept serving the old bars after a code was corrected. Nothing asks
 * for those addresses any more, so they would only sit there until they age out.
 * The pictures next to them stay: they are what makes the till work offline.
 */
export function dropUnversionedBarcodes(): Promise<void> {
  return serially(async () => {
    const cacheStorage = storage()
    if (!cacheStorage || !(await cacheStorage.has(IMAGES_CACHE))) return
    const cache = await cacheStorage.open(IMAGES_CACHE)
    for (const request of await cache.keys()) {
      if (new URL(request.url).pathname.startsWith('/api/barcodes/')) await cache.delete(request)
    }
  })
}

/** Every cache that holds the household's data: cards, codes, notes, pictures. */
export const SENSITIVE_CACHES = [API_CACHE, IMAGES_CACHE, BARCODES_CACHE]

/**
 * Deletes what this device kept of the household's data (T6).
 *
 * Called on an explicit sign-out and whenever the server says this device is no
 * longer let in (401, or 403 on a read), so a revoked or expired session does not
 * keep showing every card it once saw. The app shell stays: it holds no data, and
 * without it the sign-in screen could not open offline.
 *
 * What this cannot reach: the browser's HTTP cache (the server's
 * `Clear-Site-Data: "cache"` on sign-out asks for that), and anything already
 * copied off the device — see docs/internals.md.
 */
export function purgeSensitiveCaches(): Promise<void> {
  return serially(async () => {
    const cacheStorage = storage()
    if (!cacheStorage) return
    await Promise.all(SENSITIVE_CACHES.map((name) => cacheStorage.delete(name)))
  })
}
