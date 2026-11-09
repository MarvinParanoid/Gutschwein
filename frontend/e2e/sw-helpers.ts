import { readFileSync } from 'node:fs'

import { expect, type APIRequestContext, type Browser, type Page } from '@playwright/test'

import { createCard, uniqueMerchant } from './helpers'

/**
 * A real browser with the real service worker, signed in the way the PWA is: by
 * a login link and a cookie. The rest of the suite blocks the worker (see
 * playwright.config.ts) and authenticates with the dev header, which a worker's
 * own requests do not reliably carry.
 */
export async function signedInWithWorker(browser: Browser, request: APIRequestContext) {
  const { token } = await (await request.post('/api/auth/dev-token')).json()
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: 'ru-RU',
    serviceWorkers: 'allow',
    // The config's dev header would let this browser in whatever its cookie says.
    extraHTTPHeaders: {},
  })
  const page = await context.newPage()
  await page.goto(`/login#${token}`)
  await expect(page.locator('.topbar h1')).toBeVisible()
  // Installed, activated and in control of this page (skipWaiting + clientsClaim),
  // so every request from here on goes through it.
  await page.waitForFunction(() => navigator.serviceWorker?.controller !== null, null, {
    timeout: 15_000,
  })
  // The first load ran before the worker took over, so none of its answers were
  // cached; an installed app is opened again and again. One more load fills the
  // caches the way the second launch does.
  await page.reload()
  await expect(page.locator('.card').first()).toBeVisible()
  return { context, page }
}

/** The URLs a cache of the page's origin holds, or null if it does not exist. */
export function cachedUrls(page: Page, name: string): Promise<string[] | null> {
  return page.evaluate(async (cacheName) => {
    if (!(await caches.has(cacheName))) return null
    const cache = await caches.open(cacheName)
    return (await cache.keys()).map((request) => request.url)
  }, name)
}

export async function cacheNames(page: Page): Promise<string[]> {
  return page.evaluate(() => caches.keys())
}

// Invented, like the fixture drawn from it.
export const CARD_NUMBER = '9998887776665'
const FIXTURE = new URL('./fixtures/card-with-barcode.png', import.meta.url).pathname

/** A card whose picture carries a readable barcode, so it has a redrawn one. */
export async function cardWithBarcode(request: APIRequestContext, prefix: string) {
  const upload = await request.post('/api/uploads', {
    multipart: {
      file: { name: 'card.png', mimeType: 'image/png', buffer: readFileSync(FIXTURE) },
    },
  })
  expect(upload.ok()).toBeTruthy()
  const { image_id: imageId } = await upload.json()
  const merchant = uniqueMerchant(prefix)
  const card = await createCard(request, { merchant, value_amount: '25', image_id: imageId })
  expect(card).toMatchObject({ code: CARD_NUMBER, barcode_format: 'Code 128' })
  return { id: card.id, merchant, imageId: imageId as string }
}

/** The card's page reached through the list, the way a person gets there. */
export async function openFromList(page: Page, merchant: string) {
  await page.getByPlaceholder('Поиск').fill(merchant)
  await page.locator('.card', { hasText: merchant }).click()
  await expect(page.locator('.topbar h1')).toHaveText(merchant)
}

/** The scan screen's picture has actually been drawn, not merely requested. */
export async function shownImage(page: Page) {
  const shown = page.locator('.scan-image')
  await expect
    .poll(() => shown.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0))
    .toBe(true)
  return shown
}
