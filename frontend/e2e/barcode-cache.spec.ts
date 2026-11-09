import { expect, test } from '@playwright/test'

import {
  CARD_NUMBER,
  cachedUrls,
  cardWithBarcode,
  openFromList,
  shownImage,
  signedInWithWorker,
} from './sw-helpers'

/**
 * T5: a corrected code must reach the till.
 *
 * The barcode is drawn from the card's code, but its address used to be derived
 * from the picture alone, and the service worker answers that address from its
 * cache first — so after a misread code was fixed, the installed app kept showing
 * the old bars. These run with the real worker in Chromium; Telegram's WebView and
 * Safari keep their own caches and are not covered here.
 */

const CORRECTED = '4006381333931'

test('a corrected code replaces the cached barcode, online and offline', async ({
  browser,
  request,
}) => {
  const card = await cardWithBarcode(request, 'Barcode-T5')
  const { context, page } = await signedInWithWorker(browser, request)

  // A: the code as decoded from the picture, now cached for the till.
  await openFromList(page, card.merchant)
  await page.locator('.hero-button').click()
  const shown = await shownImage(page)
  const addressA = new URL((await shown.getAttribute('src'))!, page.url())
  expect(addressA.pathname).toBe(`/api/barcodes/${card.imageId}`)
  expect(addressA.searchParams.get('v')).toMatch(/^[0-9a-f]{8}$/)
  await expect(page.locator('.scan-code')).toHaveText(CARD_NUMBER)
  expect(await cachedUrls(page, 'gutschwein-barcodes')).toEqual([addressA.href])
  const barsA = await (await request.get(addressA.pathname + addressA.search)).text()

  // The code is corrected — here through the API, as another device would.
  const patched = await request.patch(`/api/vouchers/${card.id}`, { data: { code: CORRECTED } })
  expect(patched.ok()).toBeTruthy()

  // B: reopening the card shows the new code and new bars, from a new address.
  await page.getByRole('button', { name: 'Готово' }).click()
  await page.goBack()
  await openFromList(page, card.merchant)
  await page.locator('.hero-button').click()
  await shownImage(page)
  const addressB = new URL((await page.locator('.scan-image').getAttribute('src'))!, page.url())
  expect(addressB.pathname).toBe(addressA.pathname)
  expect(addressB.search).not.toBe(addressA.search)
  await expect(page.locator('.scan-code')).toHaveText(CORRECTED)

  // What the worker stored under B is B's bars, not A's.
  const cachedB = await page.evaluate(async (url) => {
    const response = await (await caches.open('gutschwein-barcodes')).match(url)
    return response ? response.text() : null
  }, addressB.href)
  expect(cachedB).not.toBeNull()
  expect(cachedB).not.toBe(barsA)
  expect(cachedB).toBe(await (await request.get(addressB.pathname + addressB.search)).text())

  // A is gone from the cache, and the server will not answer it with anything.
  expect(await cachedUrls(page, 'gutschwein-barcodes')).toEqual([addressB.href])
  expect((await request.get(addressA.pathname + addressA.search)).status()).toBe(404)

  // Offline, in the running app: the card and its barcode come from the device,
  // and the screen says the card is as last loaded.
  await page.getByRole('button', { name: 'Готово' }).click()
  await context.setOffline(true)
  await expect(page.locator('.offline')).toBeVisible()
  await page.goBack()
  await page.locator('.card', { hasText: card.merchant }).click()
  await expect(page.locator('.topbar h1')).toHaveText(card.merchant)
  await page.locator('.hero-button').click()
  await shownImage(page)
  expect(await page.locator('.scan-image').getAttribute('src')).toBe(
    addressB.pathname + addressB.search,
  )
  await expect(page.locator('.scan-code')).toHaveText(CORRECTED)
  await expect(page.locator('.scan-offline')).toBeVisible()

  // Offline, from a cold start: the shell, the list and the card still open.
  // (Playwright's emulation reports navigator.onLine as true in a document loaded
  // while offline, so the banner is not asserted here; the network really is off.)
  await page.reload()
  await page.locator('.card', { hasText: card.merchant }).click()
  await page.locator('.hero-button').click()
  await shownImage(page)
  await expect(page.locator('.scan-code')).toHaveText(CORRECTED)

  await context.setOffline(false)
  await context.close()
})

test('old-style barcode entries are cleared from the pictures cache, pictures stay', async ({
  browser,
  request,
}) => {
  const card = await cardWithBarcode(request, 'Barcode-Legacy')
  const { context, page } = await signedInWithWorker(browser, request)

  // What an installation from before T5 left behind: the picture and an
  // unversioned barcode side by side in the same cache.
  await page.evaluate(async (imageId) => {
    const cache = await caches.open('gutschwein-cards')
    await cache.add(`/api/images/${imageId}`)
    await cache.add(`/api/barcodes/${imageId}`)
  }, card.imageId)

  await page.reload()

  await expect
    .poll(() => cachedUrls(page, 'gutschwein-cards'))
    .toEqual([new URL(`/api/images/${card.imageId}`, page.url()).href])
  await context.close()
})
