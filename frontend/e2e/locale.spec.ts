import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'

import { createCard, uniqueMerchant } from './helpers'

/**
 * The language follows the client unless this device has chosen one by hand
 * (GitHub issue #3). In a browser the client's language is navigator.language,
 * which Playwright sets from the context locale.
 */

const KEY = 'gutschwein-language'

const stored = (page: Page) => page.evaluate((key) => localStorage.getItem(key), KEY)

async function openMenu(page: Page) {
  await page.locator('.burger').click()
  // The sheet slides in; wait for it to settle before aiming at anything in it.
  await page.locator('.language-select').hover()
}

/** Picks a language in the menu and waits for the reload it causes. */
async function choose(page: Page, label: string) {
  await openMenu(page)
  await Promise.all([page.waitForEvent('load'), page.locator('.language-select').selectOption({ label })])
}

test.describe('english client', () => {
  test.use({ locale: 'en-GB' })

  test('the app speaks English end to end', async ({ page, request }) => {
    const merchant = uniqueMerchant('Rewe')
    await createCard(request, { merchant, value_amount: '50' })

    await page.goto('/')
    await expect(page.locator('.topbar h1')).toContainText('Active')
    await page.locator('.burger').click()
    await expect(page.locator('.sheet-item', { hasText: 'Statistics' })).toBeVisible()
    await page.keyboard.press('Escape')

    await page.getByPlaceholder('Search: shop, note…').fill(merchant)
    await page.locator('.card', { hasText: merchant }).click()
    await expect(page.getByRole('button', { name: 'Update balance' })).toBeVisible()

    // Errors come from the server, so they prove the Accept-Language plumbing.
    const failed = await request.post('/api/vouchers/999999/balance', {
      data: { spent: '1' },
      headers: { 'Accept-Language': 'en-GB,en;q=0.9' },
    })
    expect(failed.status()).toBe(404)
    expect((await failed.json()).detail).toBe('Card not found')
  })

  test('first launch follows the browser, and says so in the menu', async ({ page }) => {
    await page.goto('/')
    expect(await stored(page)).toBeNull()

    await openMenu(page)
    await expect(page.locator('.language-select')).toHaveValue('auto')
    await expect(page.locator('.language-select option:checked')).toHaveText('Auto (English)')
  })

  test('a chosen language applies at once, everywhere, and survives a reload', async ({
    page,
    request,
  }) => {
    const merchant = uniqueMerchant('Sprache')
    await createCard(request, { merchant, value_amount: '20', valid_until: '2029-07-25' })
    await page.goto('/')
    await page.getByPlaceholder('Search: shop, note…').fill(merchant)
    await expect(page.locator('.card', { hasText: merchant })).toContainText('until 25/07/2029')

    // The API is asked in the new language too, so server errors follow.
    const asked = page.waitForRequest((r) => r.url().endsWith('/api/me'))
    await choose(page, 'Deutsch')
    expect((await asked).headers()['accept-language']).toBe('de')

    await expect(page.locator('.topbar h1')).toHaveText('Aktiv')
    expect(await stored(page)).toBe('de')
    expect(await page.evaluate(() => document.documentElement.lang)).toBe('de-DE')
    await page.getByPlaceholder('Suche: Laden, Notiz…').fill(merchant)
    // Dates follow the language, not the browser.
    await expect(page.locator('.card', { hasText: merchant })).toContainText('bis 25.07.2029')

    await page.reload()
    await expect(page.locator('.topbar h1')).toHaveText('Aktiv')

    // Back to automatic: the browser's language again, and nothing left stored.
    await choose(page, 'Auto (English)')
    await expect(page.locator('.topbar h1')).toHaveText('Active')
    expect(await stored(page)).toBeNull()
  })

  test('an invalid stored value falls back to the browser language', async ({ page }) => {
    await page.addInitScript((key) => localStorage.setItem(key, 'klingon'), KEY)

    await page.goto('/')

    await expect(page.locator('.topbar h1')).toHaveText('Active')
    await openMenu(page)
    await expect(page.locator('.language-select')).toHaveValue('auto')
  })
})

test.describe('russian client', () => {
  test.use({ locale: 'ru-RU' })

  test('the same build stays Russian', async ({ page, request }) => {
    const merchant = uniqueMerchant('Penny')
    await createCard(request, { merchant, value_amount: '30' })

    await page.goto('/')
    await page.getByPlaceholder('Поиск').fill(merchant)
    await page.locator('.card', { hasText: merchant }).click()
    await expect(page.getByRole('button', { name: 'Обновить остаток' })).toBeVisible()
  })
})

test.describe('german client', () => {
  test.use({ locale: 'de-DE' })

  test('a German browser gets German, not the English fallback', async ({ page, request }) => {
    const merchant = uniqueMerchant('Kaufland')
    await createCard(request, { merchant, value_amount: '20' })

    await page.goto('/')
    await expect(page.locator('.topbar h1')).toContainText('Aktiv')
    await page.getByPlaceholder('Suche: Laden, Notiz…').fill(merchant)
    await page.locator('.card', { hasText: merchant }).click()
    await expect(page.getByRole('button', { name: 'Guthaben aktualisieren' })).toBeVisible()

    const failed = await request.get('/api/vouchers/999999', {
      headers: { 'Accept-Language': 'de-DE,de;q=0.9' },
    })
    expect((await failed.json()).detail).toBe('Karte nicht gefunden')
  })
})

test.describe('on a phone', () => {
  test.use({
    locale: 'de-DE',
    viewport: { width: 360, height: 640 },
    isMobile: true,
    hasTouch: true,
  })

  test('the language control is on screen and usable by touch', async ({ page }) => {
    await page.goto('/')
    await openMenu(page)

    const select = page.locator('.language-select')
    const box = await select.boundingBox()
    expect(box).not.toBeNull()
    // Inside the screen, and big enough for a finger.
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(360)
    expect(box!.y + box!.height).toBeLessThanOrEqual(640)
    expect(box!.height).toBeGreaterThanOrEqual(32)
    await expect(page.getByText('🌐 Sprache')).toBeVisible()

    await Promise.all([page.waitForEvent('load'), select.selectOption('ru')])
    await expect(page.locator('.topbar h1')).toHaveText('Активные')
  })
})

/**
 * Inside Telegram. The real SDK is replaced by a stand-in that reports a client
 * and its language; the dev header does the authenticating, as everywhere in the
 * suite. What this proves is the app's side — Telegram's language as the default,
 * a choice by hand above it, and that a reload keeps the Mini App working.
 */
test.describe('telegram mini app', () => {
  test.use({ locale: 'en-GB' })

  test.beforeEach(async ({ page }) => {
    await page.route('https://telegram.org/js/telegram-web-app.js', (route) =>
      route.fulfill({
        contentType: 'text/javascript',
        body: `
          const noop = () => {}
          window.Telegram = { WebApp: {
            initData: 'query_id=stub&user=%7B%22id%22%3A1000%7D',
            initDataUnsafe: { user: { id: 1000, language_code: 'de' } },
            colorScheme: 'light',
            ready: noop, expand: noop, onEvent: noop,
            BackButton: { show: noop, hide: noop, onClick: noop, offClick: noop },
            MainButton: { setParams: noop, onClick: noop, offClick: noop,
                          showProgress: noop, hideProgress: noop },
            HapticFeedback: { impactOccurred: noop, notificationOccurred: noop },
            showConfirm: (m, cb) => cb(true), showAlert: noop, openTelegramLink: noop,
          } }
        `,
      }),
    )
  })

  test("Telegram's language is the default, and a choice by hand wins", async ({ page }) => {
    await page.goto('/')
    // Telegram says German, the browser English: Telegram wins.
    await expect(page.locator('.topbar h1')).toHaveText('Aktiv')
    // Really inside the (stand-in) client: the app leaves the title to Telegram.
    await expect(page.locator('.topbar .mark')).toHaveCount(0)

    await openMenu(page)
    await expect(page.locator('.language-select option:checked')).toHaveText(
      'Auto (Deutsch)',
    )
    await Promise.all([page.waitForEvent('load'), page.locator('.language-select').selectOption('en')])

    await expect(page.locator('.topbar h1')).toHaveText('Active')
    await expect(page.locator('.topbar .mark')).toHaveCount(0)
    expect(await stored(page)).toBe('en')
  })
})
