import { afterEach, describe, expect, it, vi } from 'vitest'

import { dropUnversionedBarcodes } from './pwaCache'

/** Just enough of Cache Storage: these tests check which entries are deleted, not
    how a browser stores them — that is for the e2e suite with a real worker. */
function fakeCaches(contents: Record<string, string[]>) {
  const stores = new Map(Object.entries(contents).map(([name, urls]) => [name, new Set(urls)]))
  return {
    stores,
    has: async (name: string) => stores.has(name),
    delete: async (name: string) => stores.delete(name),
    keys: async () => [...stores.keys()],
    open: async (name: string) => {
      if (!stores.has(name)) stores.set(name, new Set())
      const urls = stores.get(name)!
      return {
        keys: async () => [...urls].map((url) => new Request(url)),
        delete: async (request: Request) => urls.delete(request.url),
      }
    },
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('dropUnversionedBarcodes', () => {
  it('removes old-style barcodes and keeps the pictures', async () => {
    const fake = fakeCaches({
      'gutschwein-cards': [
        'https://app.test/api/images/ab/one.webp',
        'https://app.test/api/barcodes/ab/one.webp',
        'https://app.test/api/barcodes/cd/two.webp',
      ],
    })
    vi.stubGlobal('caches', fake)

    await dropUnversionedBarcodes()

    expect([...fake.stores.get('gutschwein-cards')!]).toEqual([
      'https://app.test/api/images/ab/one.webp',
    ])
  })

  it('creates nothing on a device that never cached anything', async () => {
    const fake = fakeCaches({})
    vi.stubGlobal('caches', fake)

    await dropUnversionedBarcodes()

    expect(fake.stores.size).toBe(0)
  })

  it('does nothing where Cache Storage does not exist', async () => {
    await expect(dropUnversionedBarcodes()).resolves.toBeUndefined()
  })
})
