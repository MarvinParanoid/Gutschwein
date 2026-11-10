/**
 * Light, dark, or the system's own choice — and which of the three this device picked.
 *
 * Only ever a browser/PWA decision. Inside Telegram the client's theme *is* the app's
 * theme (`--tg-theme-*`, stamped by `telegram.ts`), so a switch that argued with it
 * would be a second opinion the Mini App cannot win — hence `applyTheme` refuses to
 * stamp anything while inside Telegram, and the button itself only exists outside it.
 *
 * The choice belongs to the device, not the member: localStorage, never sent to the
 * server, no migration, no sync — the same rule as the language (`i18n/index.ts`).
 * Unlike the language nothing here is read at module level that a re-render cannot
 * fix, so changing it needs no reload.
 */

import { inTelegram } from './telegram'

export type ThemeChoice = 'auto' | 'light' | 'dark'

export const THEME_KEY = 'gutschwein-theme'

/** The order one tap of the button walks: the system, then the two it stands for. */
const ORDER: readonly ThemeChoice[] = ['auto', 'light', 'dark']

/** The browser's own chrome, matching the two metas in index.html. */
const CHROME: Record<'light' | 'dark', string> = { light: '#f1f2f6', dark: '#121a22' }
const CHROME_MEDIA: Record<'light' | 'dark', string> = {
  light: '(prefers-color-scheme: light)',
  dark: '(prefers-color-scheme: dark)',
}

/** A stored value, read defensively: anything unknown means "follow the system". */
export function parseThemeChoice(stored: string | null | undefined): ThemeChoice {
  return ORDER.includes(stored as ThemeChoice) ? (stored as ThemeChoice) : 'auto'
}

/** The choice one tap further round. */
export function nextTheme(choice: ThemeChoice): ThemeChoice {
  return ORDER[(ORDER.indexOf(choice) + 1) % ORDER.length]
}

// localStorage can be missing (a unit test) or throw (storage disabled, some embedded
// browsers); either way the app follows the system.
export function readStoredTheme(): ThemeChoice {
  try {
    return parseThemeChoice(globalThis.localStorage?.getItem(THEME_KEY))
  } catch {
    return 'auto'
  }
}

let current: ThemeChoice = readStoredTheme()

/** What this device has chosen; 'auto' unless someone picked a mode by hand. */
export function currentTheme(): ThemeChoice {
  return current
}

/**
 * Paints a choice: the attribute the stylesheet keys on, and the browser's own
 * chrome, so the window around the app matches it instead of the OS. `auto` puts
 * both back the way the markup left them — the media queries, which need no script.
 */
export function applyTheme(choice: ThemeChoice): void {
  if (inTelegram || typeof document === 'undefined') return
  const root = document.documentElement
  if (choice === 'auto') delete root.dataset.theme
  else root.dataset.theme = choice
  for (const mode of ['light', 'dark'] as const) {
    const meta = document.getElementById(`theme-color-${mode}`)
    if (!meta) continue
    meta.setAttribute('media', choice === 'auto' ? CHROME_MEDIA[mode] : 'all')
    meta.setAttribute('content', choice === 'auto' ? CHROME[mode] : CHROME[choice])
  }
}

/**
 * Stores a choice and paints it. A storage that refuses leaves the mode in place for
 * this visit — it just will not survive a reload, as the language does too.
 */
export function setTheme(choice: ThemeChoice): ThemeChoice {
  current = choice
  applyTheme(choice)
  try {
    if (choice === 'auto') globalThis.localStorage?.removeItem(THEME_KEY)
    else globalThis.localStorage?.setItem(THEME_KEY, choice)
  } catch {
    // Storage refused: the mode holds for this visit, and nothing is remembered.
  }
  return choice
}

/**
 * Puts the stored choice in place before React's first paint (called from `main.tsx`).
 *
 * Deliberately not a module-level side effect like the language: a hidden write to the
 * document at import time is the kind of thing a unit test has to stub around.
 */
export function applyStoredTheme(): void {
  applyTheme(current)
}
