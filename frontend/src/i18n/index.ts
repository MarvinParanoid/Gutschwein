import { tg } from '../telegram'
import { de } from './de'
import { en } from './en'
import { ru, type Dictionary } from './ru'

/**
 * Language is decided once, at load.
 *
 * By default it follows the client: inside Telegram the client tells us the user's
 * language, in a browser we ask the browser. A device can override that by hand
 * (GitHub issue #3) — a German phone used by someone who reads Russian, say. The
 * choice belongs to the device, not the member: it is kept in localStorage, never
 * sent to the server, and survives sign-out and updates.
 *
 * Changing it reloads the page rather than re-rendering: dictionaries are read at
 * module level in places (tab labels, the form's value kinds), and a reload is the
 * one way to be sure that no string, date or server error is left in the old one.
 */

export type Language = 'ru' | 'de' | 'en'
export type LanguageChoice = 'auto' | Language

export const LANGUAGE_CHOICES: readonly LanguageChoice[] = ['auto', 'ru', 'de', 'en']

/** Each language under its own name, so it can be found by someone who reads only it. */
export const LANGUAGE_NAMES: Record<Language, string> = {
  ru: 'Русский',
  de: 'Deutsch',
  en: 'English',
}

export const LANGUAGE_KEY = 'gutschwein-language'

const DICTIONARIES: Record<Language, Dictionary> = { ru, de, en }

/** What the client asks for — the behaviour before there was a choice. */
export function detectLanguage(telegramCode?: string, browserCode?: string): Language {
  const code = (telegramCode || browserCode || 'ru').toLowerCase()
  if (code.startsWith('ru')) return 'ru'
  if (code.startsWith('de')) return 'de'
  return 'en'
}

/** A stored value, read defensively: anything unknown means "follow the client". */
export function parseChoice(stored: string | null | undefined): LanguageChoice {
  return LANGUAGE_CHOICES.includes(stored as LanguageChoice) ? (stored as LanguageChoice) : 'auto'
}

export function resolveLanguage(
  choice: LanguageChoice,
  telegramCode?: string,
  browserCode?: string,
): Language {
  return choice === 'auto' ? detectLanguage(telegramCode, browserCode) : choice
}

// localStorage can be missing (a unit test) or throw (storage disabled, some
// embedded browsers); either way the app falls back to the client's language.
function readStoredChoice(): LanguageChoice {
  try {
    return parseChoice(globalThis.localStorage?.getItem(LANGUAGE_KEY))
  } catch {
    return 'auto'
  }
}

const telegramLanguage = tg?.initDataUnsafe?.user?.language_code
const browserLanguage = typeof navigator === 'undefined' ? '' : navigator.language

/** What this device has chosen; 'auto' unless someone picked a language by hand. */
export const languageChoice: LanguageChoice = readStoredChoice()

/** What 'auto' means on this device right now — shown next to the option. */
export const detectedLanguage: Language = detectLanguage(telegramLanguage, browserLanguage)

export const t: Dictionary =
  DICTIONARIES[resolveLanguage(languageChoice, telegramLanguage, browserLanguage)]

/** Locale for dates and numbers, taken from the same decision. */
export const locale = t.locale

/** The bare code the server understands: "de-DE" → "de". */
export const language = locale.slice(0, 2)

/** Stores the choice for this device and reloads into it. */
export function chooseLanguage(choice: LanguageChoice): void {
  try {
    if (choice === 'auto') localStorage.removeItem(LANGUAGE_KEY)
    else localStorage.setItem(LANGUAGE_KEY, choice)
  } catch {
    // Storage refused: nothing would survive the reload, so do not pretend.
    return
  }
  window.location.reload()
}

// index.html ships lang="ru"; correct it so hyphenation and screen readers
// follow the language the app actually settled on.
if (typeof document !== 'undefined') document.documentElement.lang = locale
