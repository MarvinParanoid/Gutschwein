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
 * Removes barcodes cached by addresses without a version.
 *
 * Before T5 barcodes shared the pictures' cache under `/api/barcodes/<image>`, an
 * address that kept serving the old bars after a code was corrected. Nothing asks
 * for those addresses any more, so they would only sit there until they age out.
 * The pictures next to them stay: they are what makes the till work offline.
 */
export async function dropUnversionedBarcodes(): Promise<void> {
  const cacheStorage = storage()
  if (!cacheStorage || !(await cacheStorage.has(IMAGES_CACHE))) return
  const cache = await cacheStorage.open(IMAGES_CACHE)
  for (const request of await cache.keys()) {
    if (new URL(request.url).pathname.startsWith('/api/barcodes/')) await cache.delete(request)
  }
}
