import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from './api'

/**
 * A device that is no longer let in forgets the household's data (T6). Only the
 * decision is tested here — which answers purge and which do not; that a real
 * browser then really has empty caches is checked by e2e/logout.spec.ts.
 */

let deleted: string[]

beforeEach(() => {
  deleted = []
  vi.stubGlobal('caches', {
    delete: async (name: string) => {
      deleted.push(name)
      return true
    },
  })
})

afterEach(() => vi.unstubAllGlobals())

function answer(status: number) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ detail: 'no' }), { status })),
  )
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('losing access purges the cached data', () => {
  it.each([
    ['an expired or revoked session', 401, () => api.me()],
    ['a membership that ended', 403, () => api.listVouchers('active')],
  ])('%s', async (_, status, call) => {
    answer(status)

    const error = await call().catch((e: unknown) => e)
    await settle()

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(status)
    expect(deleted.sort()).toEqual(['gutschwein-api', 'gutschwein-barcodes', 'gutschwein-cards'])
  })

  it('a 403 on a write is one refused request, not a lost device', async () => {
    // The CSRF check answers 403 to a single forged or misdirected write.
    answer(403)

    await api.transition(1, 'use').catch(() => undefined)
    await settle()

    expect(deleted).toEqual([])
  })

  it.each([404, 409, 422, 500])('an ordinary error (%i) keeps the offline data', async (status) => {
    answer(status)

    await api.getVoucher(1).catch(() => undefined)
    await settle()

    expect(deleted).toEqual([])
  })
})
