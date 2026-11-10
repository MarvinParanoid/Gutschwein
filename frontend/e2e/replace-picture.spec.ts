import { expect, test } from './fixtures'

import { uniqueMerchant } from './helpers'

/**
 * Swapping a card's picture re-reads the card.
 *
 * The report: a gift card whose QR screenshot was replaced with a barcode picture
 * kept the QR's address as its code, so the till asked the server for that address
 * as an EAN-13, was refused, and showed a broken picture. The form sends every field
 * back — the format included, unchanged — which is exactly what the old server read
 * as "the member said nothing about the code".
 */

const COUPON = 'https://coupons.rossmann.de/appcoupon/xJ3-abc?src=app'
const EAN13 = '4006381333931'
const QR = new URL('./fixtures/coupon-qr.png', import.meta.url).pathname
const EAN13_PNG = new URL('./fixtures/card-ean13.png', import.meta.url).pathname
const PHOTO = '.photo-picker input[type=file]'

test('replacing the picture re-reads the code, and the till can draw it', async ({ page }) => {
  const merchant = uniqueMerchant('Rossmann')

  await page.goto('/')
  await page.getByRole('button', { name: 'Добавить' }).click()
  await page.locator('#merchant').fill(merchant)
  await page.locator('#amount').fill('10')
  await page.locator(PHOTO).setInputFiles(QR)
  await expect(page.locator('.photo-picker img')).toBeVisible()
  await page.getByRole('button', { name: 'Сохранить' }).click()

  // The QR is the coupon's address, and the card says so.
  await expect(page.locator('.topbar h1')).toHaveText(merchant)
  await expect(page.locator('.code a')).toHaveAttribute('href', COUPON)

  // The same card, a different picture: a barcode instead of the QR.
  await page.getByRole('button', { name: 'Изменить' }).click()
  await page.locator(PHOTO).setInputFiles(EAN13_PNG)
  await expect(page.locator('.photo-picker img')).toBeVisible()
  await page.getByRole('button', { name: 'Сохранить' }).click()

  // The code is the new picture's — the discarded one's address is not left behind.
  await expect(page.locator('.code span')).toHaveText(EAN13)

  // …so the till draws bars, rather than failing and showing a broken picture.
  await page.locator('.hero-button').click()
  const shown = page.locator('.scan-image')
  await expect(shown).toHaveAttribute('src', /\/api\/barcodes\//)
  const loaded = await shown.evaluate((image: HTMLImageElement) => image.naturalWidth)
  expect(loaded).toBeGreaterThan(0)
  await expect(page.locator('.scan-code')).toHaveText(EAN13)
})