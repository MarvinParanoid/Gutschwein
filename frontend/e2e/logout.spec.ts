import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'

import {
  cacheNames,
  cachedUrls,
  cardWithBarcode,
  openFromList,
  shownImage,
  signedInWithWorker,
} from './sw-helpers'

/**
 * T6: signing out of the PWA, and what the device keeps afterwards.
 *
 * Real service worker, real Cache Storage, in Chromium. Telegram's WebView and
 * Safari are not covered: there is no sign-out inside Telegram (the account is the
 * way in), and Safari's handling of Clear-Site-Data is its own.
 */

const SENSITIVE = ['gutschwein-api', 'gutschwein-cards', 'gutschwein-barcodes']

/** Opens a card and its scan screen, so every sensitive cache holds something. */
async function useTheTill(page: Page, merchant: string) {
  await openFromList(page, merchant)
  await page.locator('.hero-button').click()
  await shownImage(page)
  await page.getByRole('button', { name: 'Готово' }).click()
  await page.goBack()
  for (const name of SENSITIVE) {
    expect((await cachedUrls(page, name))?.length ?? 0, name).toBeGreaterThan(0)
  }
}

async function openAccess(page: Page) {
  await page.locator('.burger').click()
  await page.locator('.sheet-item', { hasText: 'Доступ' }).hover()
  await page.locator('.sheet-item', { hasText: 'Доступ' }).click()
  await expect(page.locator('.topbar h1')).toHaveText('Доступ')
}

test('signing out ends the session and leaves no card data on the device', async ({
  browser,
  request,
}) => {
  const card = await cardWithBarcode(request, 'Logout')
  const { context, page } = await signedInWithWorker(browser, request)
  await useTheTill(page, card.merchant)

  await openAccess(page)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Выйти на этом устройстве' }).click()

  // Back at the door, with nothing of the household's on screen.
  await expect(page.locator('.empty')).toContainText('Нужен вход')
  await expect(page.getByText(card.merchant)).toHaveCount(0)

  // The caches are gone; the app shell stays, so the sign-in screen opens offline.
  const left = await cacheNames(page)
  for (const name of SENSITIVE) expect(left).not.toContain(name)
  expect(left.some((name) => name.startsWith('workbox-precache'))).toBe(true)

  // The cookie is gone, and the server would not take a copy of it either.
  expect((await context.cookies()).some((c) => c.name === 'gutschwein_session')).toBe(false)
  expect(await page.evaluate(async () => (await fetch('/api/me')).status)).toBe(401)

  // Offline, a cold start shows the door — not the last list it had seen.
  await context.setOffline(true)
  await page.reload()
  await expect(page.locator('.empty')).toBeVisible()
  await expect(page.getByText(card.merchant)).toHaveCount(0)
  await context.setOffline(false)

  // What a browser cannot take back: the picture's address is a capability, not
  // a session. Whoever kept the URL can still open it — deleting caches does not
  // revoke it (docs/internals.md, "What signing out does not do").
  const anonymous = await browser.newContext()
  expect((await anonymous.request.get(`/api/images/${card.imageId}`)).status()).toBe(200)
  await anonymous.close()

  await context.close()
})

test('offline, signing out is refused rather than half done', async ({ browser, request }) => {
  const card = await cardWithBarcode(request, 'Logout-Offline')
  const { context, page } = await signedInWithWorker(browser, request)
  await useTheTill(page, card.merchant)
  await openAccess(page)

  await context.setOffline(true)

  // The session would survive on the server and be back with the network, so the
  // device does not pretend; it says how to do it instead.
  await expect(page.getByRole('button', { name: 'Выйти на этом устройстве' })).toBeDisabled()
  await expect(page.getByText('Выйти можно только онлайн')).toBeVisible()
  for (const name of SENSITIVE) expect(await cachedUrls(page, name), name).not.toBeNull()

  await context.setOffline(false)
  await expect(page.getByRole('button', { name: 'Выйти на этом устройстве' })).toBeEnabled()
  await context.close()
})

test('a device signed out from elsewhere stops showing cards at its next request', async ({
  browser,
  request,
}) => {
  const card = await cardWithBarcode(request, 'Logout-Remote')
  const { context, page } = await signedInWithWorker(browser, request)
  await useTheTill(page, card.merchant)
  // The list is on screen, from a session that is about to end.
  await expect(page.locator('.card', { hasText: card.merchant })).toBeVisible()

  // Another member signs this browser out from their Access screen.
  const sessions: { id: number }[] = await (await request.get('/api/auth/sessions')).json()
  const newest = Math.max(...sessions.map((s) => s.id))
  expect((await request.delete(`/api/auth/sessions/${newest}`)).status()).toBe(204)

  // No reload: the very next request is refused as "session-ended", and the
  // screen goes to the door instead of keeping the list it already had.
  await page.locator('.card', { hasText: card.merchant }).click()

  await expect(page.locator('.empty')).toContainText('Нужен вход')
  await expect(page.getByText(card.merchant)).toHaveCount(0)
  await expect
    .poll(async () => (await cacheNames(page)).filter((name) => SENSITIVE.includes(name)))
    .toEqual([])
  await context.close()
})

test('signing out also clears the HTTP cache that holds the pictures', async ({
  browser,
  request,
}) => {
  // No worker here: this is about the browser's own HTTP cache, where pictures
  // live for a year (Cache-Control: max-age=31536000) and no script can reach.
  const card = await cardWithBarcode(request, 'Logout-Http')
  const { token } = await (await request.post('/api/auth/dev-token')).json()
  const context = await browser.newContext({
    serviceWorkers: 'block',
    locale: 'ru-RU',
  })
  const page = await context.newPage()
  await page.goto(`/login#${token}`)
  await expect(page.locator('.topbar h1')).toBeVisible()

  const inHttpCache = () =>
    page.evaluate(async (url) => {
      try {
        const response = await fetch(url, { cache: 'only-if-cached', mode: 'same-origin' })
        return response.ok
      } catch {
        return false
      }
    }, `/api/images/${card.imageId}`)

  await page.evaluate((url) => fetch(url).then((r) => r.blob()), `/api/images/${card.imageId}`)
  expect(await inHttpCache()).toBe(true)

  await openAccess(page)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Выйти на этом устройстве' }).click()
  await expect(page.locator('.empty')).toContainText('Нужен вход')

  // Clear-Site-Data: "cache" on the sign-out response. Honoured by Chromium;
  // other browsers may ignore it, which docs/internals.md says.
  expect(await inHttpCache()).toBe(false)
  await context.close()
})
