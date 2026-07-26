import { tg } from '../telegram'
import { en } from './en'
import { ru, type Dictionary } from './ru'

/**
 * Language is decided once, at load, and never changes in-session.
 *
 * Inside Telegram the client tells us the user's language; in a browser we ask the
 * browser. There is no in-app switch on purpose: the phone already has one, and a
 * second place to set the same thing is a second place to get it wrong.
 */
function resolve(): Dictionary {
  const telegramLanguage = tg?.initDataUnsafe?.user?.language_code
  const browserLanguage = typeof navigator === 'undefined' ? '' : navigator.language
  const code = (telegramLanguage || browserLanguage || 'ru').toLowerCase()
  return code.startsWith('ru') ? ru : en
}

export const t: Dictionary = resolve()

/** Locale for dates and numbers, taken from the same decision. */
export const locale = t.locale

// index.html ships lang="ru"; correct it so hyphenation and screen readers
// follow the language the app actually settled on.
if (typeof document !== 'undefined') document.documentElement.lang = locale
