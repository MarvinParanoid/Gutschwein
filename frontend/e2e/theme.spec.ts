import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'

/**
 * The light/dark switch (src/theme.ts): outside Telegram only, one tap per mode,
 * remembered per device. Inside the Mini App the client's own theme rules and the
 * button is not there at all — a second opinion the app could not win.
 */

const KEY = 'gutschwein-theme'

const stored = (page: Page) => page.evaluate((key) => localStorage.getItem(key), KEY)

/** The palette the app actually painted, not just the attribute that asked for it. */
const background = (page: Page) =>
  page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim())

test('the switch sits left of the burger and walks system → light → dark', async ({ page }) => {
  // The suite's default colour scheme is light, so "system" is the light palette.
  await page.goto('/')
  await expect(page.locator('.topbar h1')).toBeVisible()

  const toggle = page.locator('.theme-toggle')
  await expect(toggle).toBeVisible()
  await expect(toggle).toHaveText('🌗')
  const [switchBox, burgerBox] = [
    await toggle.boundingBox(),
    await page.locator('.burger').boundingBox(),
  ]
  expect(switchBox!.x + switchBox!.width).toBeLessThanOrEqual(burgerBox!.x)
  expect(Math.abs(switchBox!.y - burgerBox!.y)).toBeLessThan(2)

  // System → light: the same palette the OS was already giving, now by choice.
  await toggle.click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await expect(toggle).toHaveText('☀️')
  expect(await background(page)).toBe('#ffffff')

  // Light → dark.
  await toggle.click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(toggle).toHaveText('🌙')
  expect(await background(page)).toBe('#1c2733')
  expect(await stored(page)).toBe('dark')

  // Dark → system: the attribute goes, the media query decides again.
  await toggle.click()
  await expect(page.locator('html')).not.toHaveAttribute('data-theme')
  await expect(toggle).toHaveText('🌗')
  expect(await background(page)).toBe('#ffffff')
  expect(await stored(page)).toBeNull()
})

test('the choice survives a reload', async ({ page }) => {
  await page.goto('/')
  const toggle = page.locator('.theme-toggle')
  await toggle.click() // light
  await toggle.click() // dark

  await page.reload()

  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.locator('.theme-toggle')).toHaveText('🌙')
  expect(await background(page)).toBe('#1c2733')
})

test('a hand-picked mode beats a dark system setting too', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto('/')
  await expect(page.locator('.topbar h1')).toBeVisible()
  // The OS says dark, and the app agrees until someone says otherwise.
  expect(await background(page)).toBe('#1c2733')

  await page.locator('.theme-toggle').click() // light

  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  expect(await background(page)).toBe('#ffffff')
})

/**
 * Inside Telegram. The stand-in SDK is the one locale.spec.ts uses, trimmed to what
 * this test needs: a client, its theme, and initData, which is what tells the app a
 * host is really there.
 */
test('inside Telegram the client’s theme rules and there is no switch', async ({ page }) => {
  await page.addInitScript((key) => localStorage.setItem(key, 'dark'), KEY)
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
          HapticFeedback: { impactOccurred: noop, notificationOccurred: noop },
          showConfirm: (m, cb) => cb(true), showAlert: noop, openTelegramLink: noop,
        } }
      `,
    }),
  )

  await page.goto('/')
  await expect(page.locator('.topbar h1')).toBeVisible()

  // No button, and the stored 'dark' is not stamped over the client's light theme.
  await expect(page.locator('.theme-toggle')).toHaveCount(0)
  await expect(page.locator('html')).not.toHaveAttribute('data-theme')
  expect(await background(page)).toBe('#ffffff')
})
