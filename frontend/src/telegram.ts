/** Thin typed wrapper over window.Telegram.WebApp, safe to use in a browser too. */

interface TelegramWebApp {
  initData: string
  // Unsigned copy of the same data; fine for choosing a language, never for auth.
  initDataUnsafe?: { user?: { language_code?: string } }
  colorScheme: 'light' | 'dark'
  ready(): void
  expand(): void
  BackButton: {
    show(): void
    hide(): void
    onClick(cb: () => void): void
    offClick(cb: () => void): void
  }
  MainButton: {
    setParams(params: { text?: string; is_visible?: boolean; is_active?: boolean }): void
    onClick(cb: () => void): void
    offClick(cb: () => void): void
    showProgress(leaveActive?: boolean): void
    hideProgress(): void
  }
  HapticFeedback: {
    impactOccurred(style: 'light' | 'medium' | 'heavy'): void
    notificationOccurred(type: 'error' | 'success' | 'warning'): void
  }
  showConfirm(message: string, cb: (confirmed: boolean) => void): void
  showAlert(message: string, cb?: () => void): void
  openTelegramLink(url: string): void
  onEvent(event: string, handler: () => void): void
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp }
  }
}

// Guarded like the navigator and document lookups in i18n: the module is also
// imported where there is no window at all, such as a unit test.
export const tg = typeof window === 'undefined' ? undefined : window.Telegram?.WebApp
/**
 * The object, not the host: index.html loads the SDK from telegram.org on every
 * page, so `tg` exists in an ordinary browser as well, where it reports Bot API
 * 6.0 and answers the interactive methods by throwing. Everything below therefore
 * asks whether Telegram is really on the other end, never whether `tg` is there.
 */
export const inTelegram = Boolean(tg?.initData)

export function initTelegram(): void {
  tg?.ready()
  tg?.expand()
  applyColorScheme()
  // Telegram's theme is its own setting, changeable while the app is open.
  tg?.onEvent('themeChanged', applyColorScheme)
}

/**
 * Publishes Telegram's light/dark choice as a data attribute.
 *
 * Inside Telegram the client's theme is what matters, and it need not match the
 * OS: a dark Telegram on a light system would otherwise get the light variants of
 * our own colours through `prefers-color-scheme`, on a dark background.
 *
 * Outside it there is nothing to publish. The SDK still answers `colorScheme`,
 * with a flat 'light', and stamping that let the light status colours win in a
 * dark PWA — the very inversion this attribute exists to prevent.
 */
function applyColorScheme(): void {
  const scheme = inTelegram ? tg?.colorScheme : undefined
  if (scheme) document.documentElement.dataset.tgTheme = scheme
}

export function haptic(kind: 'tap' | 'success' | 'error' = 'tap'): void {
  if (!inTelegram || !tg) return
  if (kind === 'tap') tg.HapticFeedback.impactOccurred('light')
  else tg.HapticFeedback.notificationOccurred(kind)
}

/**
 * Telegram's native confirm when Telegram is really there, the browser one otherwise.
 *
 * Both fallbacks matter. Outside Telegram `showConfirm` throws, which inside a
 * promise executor becomes a rejection — and the callers await it before their own
 * try/catch, so it escaped the click handler entirely: deleting a comment or a card
 * in the PWA did nothing and said nothing. A real client old enough to lack the
 * method fails the same way, hence the `catch` as well as the check.
 */
export function confirmAction(message: string): Promise<boolean> {
  if (!inTelegram || !tg) return Promise.resolve(window.confirm(message))
  const native = tg
  return new Promise<boolean>((resolve) => native.showConfirm(message, resolve)).catch(() =>
    window.confirm(message),
  )
}

export function alertMessage(message: string): void {
  if (inTelegram && tg) {
    try {
      tg.showAlert(message)
      return
    } catch {
      // An old client: better the browser's own dialog than a swallowed error.
    }
  }
  window.alert(message)
}
