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
