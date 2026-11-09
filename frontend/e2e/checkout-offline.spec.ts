import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'

import { createCard, uniqueMerchant } from './helpers'
import { cacheNames, cachedUrls, shownImage, signedInWithWorker } from './sw-helpers'

/**
 * Stage 1 acceptance: a barcode typed by hand, offline and then signed out.
 *
 * Real service worker, real Cache Storage, signed in by cookie as the installed PWA
 * is. The bars of a card without a picture come from an authenticated API answer
 * (GET /api/vouchers/{id}/barcode), so offline they are served from `gutschwein-api`
 * — and that cache has to go with the session, like the others.
 */

const SENSITIVE = ['gutschwein-api', 'gutschwein-cards', 'gutschwein-barcodes']
// Invented, valid EAN-13.
const CODE = '4006381333931'

async function openTill(page: Page, merchant: string) {
  await page.getByPlaceholder('Поиск').fill(merchant)
  const card = page.locator('.card', { hasText: merchant })
  await page.locator('.card-row', { has: card }).getByRole('button', { name: 'Показать на кассе' }).click()
  await shownImage(page)
  await expect(page.locator('.scan-image')).toHaveAttribute('src', /^data:image\/svg\+xml/)
  await expect(page.locator('.scan-code')).toHaveText(CODE)
}

async function closeTill(page: Page) {
  await page.getByRole('button', { name: 'Готово' }).click()
  await expect(page.locator('.scan')).toHaveCount(0)
}

test('a hand-typed barcode opens offline, and is gone from the device after signing out', async ({
  browser,
  request,
}) => {
  const merchant = uniqueMerchant('Offlinekasse')
  const card = await createCard(request, {
    merchant,
    value_amount: '35',
    code: CODE,
    barcode_format: 'EAN-13',
  })
  const barcodePath = `/api/vouchers/${card.id}/barcode`

  // 1. Online: open the barcode once.
  const { context, page } = await signedInWithWorker(browser, request)
  await openTill(page, merchant)
  await closeTill(page)
  const cached = (await cachedUrls(page, 'gutschwein-api')) ?? []
  expect(cached.some((url) => url.includes(barcodePath))).toBe(true)

  // 2–3. Offline: the same barcode opens again, from the device, and says so.
  await context.setOffline(true)
  await openTill(page, merchant)
  await expect(page.locator('.scan-offline')).toBeVisible()
  await closeTill(page)

  // …and after a cold start without network, too.
  await page.reload()
  await openTill(page, merchant)
  await closeTill(page)

  // 4. Connectivity back.
  await context.setOffline(false)
  await page.reload()
  await expect(page.locator('.card').first()).toBeVisible()

  // 5. Sign out.
  await page.locator('.burger').click()
  await page.locator('.sheet-item', { hasText: 'Доступ' }).hover()
  await page.locator('.sheet-item', { hasText: 'Доступ' }).click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Выйти на этом устройстве' }).click()
  await expect(page.locator('.empty')).toContainText('Нужен вход')

  // 6. Nothing of it is left on the device, or reachable through the app.
  const left = await cacheNames(page)
  for (const name of SENSITIVE) expect(left, name).not.toContain(name)
  const anyCopy = await page.evaluate(
    async (path) => (await caches.match(path, { ignoreSearch: true })) !== undefined,
    barcodePath,
  )
  expect(anyCopy).toBe(false)
  // Asking the server for it again is refused, as signed out.
  const again = await page.evaluate(async (path) => {
    const response = await fetch(path)
    return { status: response.status, reason: response.headers.get('X-Auth-Failure') }
  }, `${barcodePath}?v=${(await (await request.get(`/api/vouchers/${card.id}`)).json()).barcode_version}`)
  expect(again).toEqual({ status: 401, reason: 'signed-out' })

  // Offline again, a cold start shows the door — not the card, not its code.
  await context.setOffline(true)
  await page.reload()
  await expect(page.locator('.empty')).toBeVisible()
  await expect(page.getByText(merchant)).toHaveCount(0)
  await expect(page.getByText(CODE)).toHaveCount(0)
  await context.setOffline(false)
  await context.close()
})
