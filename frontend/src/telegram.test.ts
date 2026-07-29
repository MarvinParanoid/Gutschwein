import { afterEach, describe, expect, it, vi } from 'vitest'

/**
 * These helpers are the only place that talks to the Telegram SDK, and the SDK is
 * loaded on every page — including the installed PWA, where there is no Telegram
 * behind it. That case is what the tests below are about: the object answers, the
 * host does not.
 */

/** What `window.Telegram.WebApp` looks like once telegram.org's script has run. */
function webApp({ initData, colorScheme = 'light', supported }: {
  initData: string
  colorScheme?: 'light' | 'dark'
  /** A client too old for showConfirm/showAlert throws, exactly as the SDK does. */
  supported: boolean
}) {
  const shown: string[] = []
  const unsupported = () => {
    throw new Error('WebAppMethodUnsupported')
  }
  return {
    shown,
    app: {
      initData,
      colorScheme,
      ready: () => undefined,
      expand: () => undefined,
      onEvent: () => undefined,
      HapticFeedback: {
        impactOccurred: supported ? () => undefined : unsupported,
        notificationOccurred: supported ? () => undefined : unsupported,
      },
      showConfirm: supported
        ? (message: string, cb: (confirmed: boolean) => void) => {
            shown.push(message)
            cb(true)
          }
        : unsupported,
      showAlert: supported
        ? (message: string) => {
            shown.push(message)
          }
        : unsupported,
    },
  }
}

async function load(app: unknown) {
  const browser = { confirm: [] as string[], alert: [] as string[] }
  const dataset: Record<string, string> = {}
  vi.stubGlobal('window', {
    Telegram: { WebApp: app },
    confirm: (message: string) => {
      browser.confirm.push(message)
      return true
    },
    alert: (message: string) => {
      browser.alert.push(message)
    },
  })
  vi.stubGlobal('document', { documentElement: { dataset } })
  vi.resetModules()
  // The module reads window at import time, so it has to be imported after.
  return { ...(await import('./telegram')), browser, dataset }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('outside Telegram, where the SDK is present but the host is not', () => {
  const sdk = () => webApp({ initData: '', supported: false })

  it('confirms through the browser instead of throwing past the caller', async () => {
    const { confirmAction, browser } = await load(sdk().app)
    // The bug: showConfirm threw inside the promise executor, and the rejection
    // escaped the click handler — nothing deleted, and no error on screen either.
    await expect(confirmAction('удалить?')).resolves.toBe(true)
    expect(browser.confirm).toEqual(['удалить?'])
  })

  it('shows errors through the browser', async () => {
    const { alertMessage, browser } = await load(sdk().app)
    alertMessage('boom')
    expect(browser.alert).toEqual(['boom'])
  })

  it('leaves the theme to the OS', async () => {
    const { initTelegram, dataset } = await load(sdk().app)
    initTelegram()
    // colorScheme is a flat 'light' here; stamping it would override dark mode.
    expect(dataset.tgTheme).toBeUndefined()
  })

  it('asks for no haptics', async () => {
    const { haptic } = await load(sdk().app)
    expect(() => haptic('success')).not.toThrow()
  })
})

describe('inside Telegram', () => {
  const sdk = webApp({ initData: 'query_id=1', colorScheme: 'dark', supported: true })

  it('uses the native dialogs', async () => {
    const { confirmAction, alertMessage, browser } = await load(sdk.app)
    await expect(confirmAction('удалить?')).resolves.toBe(true)
    alertMessage('boom')
    expect(sdk.shown).toEqual(['удалить?', 'boom'])
    expect([...browser.confirm, ...browser.alert]).toEqual([])
  })

  it("publishes the client's own theme", async () => {
    const { initTelegram, dataset } = await load(sdk.app)
    initTelegram()
    expect(dataset.tgTheme).toBe('dark')
  })
})

describe('inside an old Telegram client', () => {
  const sdk = () => webApp({ initData: 'query_id=1', supported: false })

  it('falls back to the browser dialogs rather than losing the answer', async () => {
    const { confirmAction, alertMessage, browser } = await load(sdk().app)
    await expect(confirmAction('удалить?')).resolves.toBe(true)
    alertMessage('boom')
    expect(browser.confirm).toEqual(['удалить?'])
    expect(browser.alert).toEqual(['boom'])
  })
})
