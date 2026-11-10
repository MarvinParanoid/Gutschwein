import { afterEach, describe, expect, it, vi } from 'vitest'

/**
 * The theme switch is the language picker's twin: a per-device choice in
 * localStorage, with "follow the system" as the default and the only way back. What
 * is *not* here is the Mini App: inside Telegram the client's theme wins, so nothing
 * is stamped at all — the last test says so.
 */

interface Meta {
  attributes: Record<string, string>
  setAttribute(key: string, value: string): void
}

interface Storage {
  value: string | null
  getItem(): string | null
  setItem(key: string, value: string): void
  removeItem(): void
}

/** Just enough host for `applyTheme`: one root, the two chrome metas, and storage. */
function page({ stored }: { stored?: string } = {}) {
  const metas: Record<string, Meta> = {}
  for (const mode of ['light', 'dark']) {
    metas[`theme-color-${mode}`] = {
      attributes: {},
      setAttribute(key: string, value: string) {
        this.attributes[key] = value
      },
    }
  }
  const storage: Storage = {
    value: stored ?? null,
    getItem() {
      return this.value
    },
    setItem(_key: string, value: string) {
      this.value = value
    },
    removeItem() {
      this.value = null
    },
  }
  vi.stubGlobal('window', { Telegram: { WebApp: { initData: '' } } })
  vi.stubGlobal('localStorage', storage)
  vi.stubGlobal('document', {
    documentElement: { dataset: {} as Record<string, string> },
    getElementById: (id: string) => metas[id] ?? null,
  })
  return { document, metas, storage }
}

async function load(options: { stored?: string } = {}) {
  const host = page(options)
  vi.resetModules()
  // The module reads the host at import time (inTelegram, the stored choice), so it
  // has to be imported after the stubs.
  return { ...(await import('./theme')), ...host }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the stored choice', () => {
  it.each(['auto', 'light', 'dark'] as const)('%s is read back as stored', async (stored) => {
    const { currentTheme } = await load({ stored })
    expect(currentTheme()).toBe(stored)
  })

  it.each(['', 'Light', 'system', 'dark ', 'null', '{"theme":"dark"}'])(
    'an unknown stored value (%j) falls back to the system',
    async (stored) => {
      const { currentTheme, parseThemeChoice } = await load({ stored })
      expect(parseThemeChoice(stored)).toBe('auto')
      expect(currentTheme()).toBe('auto')
    },
  )

  it('has nothing to go by on a first visit', async () => {
    const { currentTheme } = await load()
    expect(currentTheme()).toBe('auto')
  })
})

describe('one tap at a time', () => {
  it('walks the system, light, dark and back', async () => {
    const { nextTheme } = await load()
    expect(nextTheme('auto')).toBe('light')
    expect(nextTheme('light')).toBe('dark')
    expect(nextTheme('dark')).toBe('auto')
  })
})

describe('what a choice paints', () => {
  it('stamps the attribute the stylesheet keys on', async () => {
    const { applyTheme, document } = await load()

    applyTheme('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')

    // Back to the system: the media queries take over again from an empty root.
    applyTheme('auto')
    expect(document.documentElement.dataset.theme).toBeUndefined()
  })

  it('moves the browser chrome with it, and puts it back', async () => {
    const { applyTheme, metas } = await load()

    applyTheme('dark')
    expect(metas['theme-color-dark'].attributes).toEqual({ media: 'all', content: '#121a22' })
    expect(metas['theme-color-light'].attributes).toEqual({ media: 'all', content: '#121a22' })

    applyTheme('light')
    expect(metas['theme-color-light'].attributes).toEqual({ media: 'all', content: '#f1f2f6' })

    // auto: the two media queries again, one colour each — as index.html ships them.
    applyTheme('auto')
    expect(metas['theme-color-light'].attributes).toEqual({
      media: '(prefers-color-scheme: light)',
      content: '#f1f2f6',
    })
    expect(metas['theme-color-dark'].attributes).toEqual({
      media: '(prefers-color-scheme: dark)',
      content: '#121a22',
    })
  })

  it('remembers the choice, and "auto" is what forgetting looks like', async () => {
    const { setTheme, currentTheme, storage } = await load()

    expect(setTheme('dark')).toBe('dark')
    expect(currentTheme()).toBe('dark')
    expect(storage.value).toBe('dark')

    setTheme('auto')
    expect(storage.value).toBeNull()
  })

  it('keeps the mode when storage refuses to write', async () => {
    const { setTheme, document } = await load()
    vi.stubGlobal('localStorage', {
      getItem: () => null,
      setItem: () => {
        throw new Error('QuotaExceededError')
      },
      removeItem: () => undefined,
    })

    expect(() => setTheme('dark')).not.toThrow()
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})

describe('inside Telegram', () => {
  it("leaves the theme to the client, whatever this device stored", async () => {
    const { document } = page({ stored: 'dark' })
    vi.stubGlobal('window', { Telegram: { WebApp: { initData: 'query_id=1' } } })
    vi.resetModules()
    const { applyStoredTheme } = await import('./theme')

    applyStoredTheme()

    // Stamped here, a dark choice would overrule a light Telegram — the app is a guest.
    expect(document.documentElement.dataset.theme).toBeUndefined()
  })
})
