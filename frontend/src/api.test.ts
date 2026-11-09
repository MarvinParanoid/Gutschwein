import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, onAccessLost } from './api'

/**
 * When the device forgets the household's data, and when it must not (T6).
 *
 * The server names the reason in `X-Auth-Failure` (app/auth.py); the status code
 * alone cannot tell an expired Telegram session, which reopening fixes, from a
 * revoked one. Only the decision is tested here; that a real browser then really
 * has empty caches is e2e/logout.spec.ts.
 */

let deleted: string[]
let shownLocked: string[]
let unsubscribe: () => void

beforeEach(() => {
  deleted = []
  shownLocked = []
  vi.stubGlobal('caches', {
    delete: async (name: string) => {
      deleted.push(name)
      return true
    },
  })
  unsubscribe = onAccessLost((message) => shownLocked.push(message))
})

afterEach(() => {
  unsubscribe()
  vi.unstubAllGlobals()
})

function answer(status: number, reason?: string) {
  const headers: Record<string, string> = reason ? { 'X-Auth-Failure': reason } : {}
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ detail: 'refused' }), { status, headers })),
  )
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))
const ALL = ['gutschwein-api', 'gutschwein-barcodes', 'gutschwein-cards']

describe('the device is out: forget the data, leave the screen', () => {
  it.each([
    // Signed out here or from another device, revoked with the member, or expired:
    // the cookie came, no session answers to it. Only a new link lets it back in.
    ['a revoked or expired browser session', 401, 'session-ended', () => api.me()],
    // No credentials at all: the browser dropped the cookie at max-age, or it was
    // cleared.
    ['a browser with no session left', 401, 'signed-out', () => api.listVouchers('active')],
    // Off the allowlist, invitation chain broken, revoked — on a read…
    ['a membership that ended', 403, 'membership', () => api.getVoucher(1)],
    // …and on a write, which is checked the same way.
    ['a membership that ended, met on a write', 403, 'membership', () => api.transition(1, 'use')],
  ])('%s', async (_, status, reason, call) => {
    answer(status, reason)

    const error = await call().catch((e: unknown) => e)
    await settle()

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(status)
    expect(deleted.sort()).toEqual(ALL)
    expect(shownLocked).toEqual(['refused'])
  })
})

describe('the device is not out: keep the offline copy', () => {
  it.each([
    // Expired initData: the member still is one, reopening the Mini App fixes it.
    ['expired Telegram data', 401, 'telegram-auth'],
    // A 401 the server did not explain — a proxy in front of it, a server from
    // before the header. Not a confirmed revocation, so not acted on as one.
    ['an unexplained 401', 401, undefined],
    // The CSRF check refusing one request says nothing about the device.
    ['a refused cross-origin write', 403, undefined],
    ['an ordinary not-found', 404, undefined],
    ['a conflict', 409, undefined],
    ['a server error', 500, undefined],
    ['a gateway timeout', 504, undefined],
  ])('%s (%i)', async (_, status, reason) => {
    answer(status, reason)

    await api.getVoucher(1).catch(() => undefined)
    await api.transition(1, 'use').catch(() => undefined)
    await settle()

    expect(deleted).toEqual([])
    expect(shownLocked).toEqual([])
  })

  it('another member\'s comment cannot be deleted: a 403 about the comment', async () => {
    answer(403)

    await api.deleteComment(1, 2).catch(() => undefined)
    await settle()

    expect(deleted).toEqual([])
  })

  it('no network at all', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))

    await api.me().catch(() => undefined)
    await settle()

    expect(deleted).toEqual([])
    expect(shownLocked).toEqual([])
  })
})
