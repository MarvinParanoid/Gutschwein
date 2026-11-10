import { useState } from 'react'

import { t } from '../i18n'
import { currentTheme, nextTheme, setTheme, type ThemeChoice } from '../theme'

/** A half moon for "follow the system", sun and moon for the two it stands for. */
const ICON: Record<ThemeChoice, string> = { auto: '🌗', light: '☀️', dark: '🌙' }

/**
 * Light, dark, system — one tap each, beside the burger.
 *
 * Rendered outside Telegram only (see ListPage): in the Mini App the client's own
 * theme is the one to follow, and `theme.applyTheme` will not stamp anything there.
 */
export default function ThemeToggle() {
  const [choice, setChoice] = useState(currentTheme)

  return (
    <button
      className="theme-toggle"
      // Naming the *current* mode, not the next one: a cycling button that announces
      // an action it cannot describe ("switch to what?") is worse than the state.
      aria-label={t.theme.label(t.theme[choice])}
      onClick={() => setChoice(setTheme(nextTheme(choice)))}
    >
      {ICON[choice]}
    </button>
  )
}
