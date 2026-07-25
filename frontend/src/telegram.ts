/** Thin typed wrapper over window.Telegram.WebApp, safe to use in a browser too. */

interface TelegramWebApp {
  initData: string
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

export const tg = window.Telegram?.WebApp
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
 */
function applyColorScheme(): void {
  const scheme = tg?.colorScheme
  if (scheme) document.documentElement.dataset.tgTheme = scheme
}

export function haptic(kind: 'tap' | 'success' | 'error' = 'tap'): void {
  if (!tg) return
  if (kind === 'tap') tg.HapticFeedback.impactOccurred('light')
  else tg.HapticFeedback.notificationOccurred(kind)
}

/** Telegram's native confirm when available, the browser one otherwise. */
export function confirmAction(message: string): Promise<boolean> {
  if (!tg) return Promise.resolve(window.confirm(message))
  return new Promise((resolve) => tg.showConfirm(message, resolve))
}

export function alertMessage(message: string): void {
  if (tg) tg.showAlert(message)
  else window.alert(message)
}
