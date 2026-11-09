import { describe, expect, it } from 'vitest'

import { de } from './de'
import { en } from './en'
import { detectLanguage, parseChoice, resolveLanguage } from './index'
import { ru } from './ru'

describe('first launch and auto detection', () => {
  it('nothing stored means automatic', () => {
    expect(parseChoice(null)).toBe('auto')
    expect(parseChoice(undefined)).toBe('auto')
  })

  it.each([
    // Telegram's own setting wins over the browser's: it is what the user chose
    // in the app they opened this from.
    ['de', 'ru-RU', 'de'],
    [undefined, 'ru-RU', 'ru'],
    [undefined, 'de-AT', 'de'],
    [undefined, 'en-US', 'en'],
    // Anything else gets English, not the server's default.
    [undefined, 'fr-FR', 'en'],
    ['uk', 'ru-RU', 'en'],
    // Nothing at all to go by: the original audience.
    [undefined, '', 'ru'],
  ])('telegram %j, browser %j → %s', (telegram, browser, expected) => {
    expect(detectLanguage(telegram, browser)).toBe(expected)
    expect(resolveLanguage('auto', telegram, browser)).toBe(expected)
  })
})

describe('a language chosen by hand', () => {
  it.each(['ru', 'de', 'en'] as const)('%s overrides both Telegram and the browser', (choice) => {
    expect(resolveLanguage(choice, 'fr', 'fr-FR')).toBe(choice)
  })

  it.each(['ru', 'de', 'en', 'auto'])('%s is read back as stored', (stored) => {
    expect(parseChoice(stored)).toBe(stored)
  })

  it.each(['', 'fr', 'RU', 'ru-RU', '"de"', 'null', 'auto '])(
    'an invalid stored value (%j) falls back to automatic',
    (stored) => {
      expect(parseChoice(stored)).toBe('auto')
    },
  )
})

describe('dates follow the chosen language', () => {
  // The same options as formatDate in format.ts: numeric, so a badge stays short.
  const date = new Date(2029, 6, 25)
  const numeric = { day: '2-digit', month: '2-digit', year: 'numeric' } as const

  it.each([
    [ru.locale, '25.07.2029'],
    [de.locale, '25.07.2029'],
    [en.locale, '25/07/2029'],
  ])('%s → %s', (locale, expected) => {
    expect(date.toLocaleDateString(locale, numeric)).toBe(expected)
  })

  it('month names are in the chosen language', () => {
    // As the statistics chart labels its months.
    const month = (locale: string) => date.toLocaleDateString(locale, { month: 'short' })
    expect(month(ru.locale)).toContain('июл')
    expect(month(de.locale)).toMatch(/^Jul/)
    expect(month(en.locale)).toBe('Jul')
  })
})
