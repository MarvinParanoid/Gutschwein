import { expect, test } from './fixtures'

import { createCard, openCard, uniqueMerchant } from './helpers'

/**
 * Some shops hand out a coupon as an address rather than a number — Rossmann does
 * — and there the address is what has to be opened. It is shown as a link *because
 * it is one*; where it goes is the browser's business, so these tests check the
 * link, not the page behind it. Invented address, like the card numbers elsewhere.
 */

const COUPON = 'https://coupons.rossmann.de/appcoupon/xJ3-abc?src=app'

test('a code that is an address is a link, on the card and at the till', async ({
  page,
  request,
}) => {
  const merchant = uniqueMerchant('Rossmann')
  await createCard(request, { merchant, code: COUPON, value_amount: '10' })

  await openCard(page, merchant)
  const link = page.locator('.code a')
  await expect(link).toHaveAttribute('href', COUPON)
  await expect(link).toHaveText(COUPON)
  // Still copyable: opening it is not the only thing the code is good for.
  await expect(page.locator('.code').getByRole('button', { name: 'копировать' })).toBeVisible()

  // And the till screen shows it the same way — that is where a coupon is opened.
  await page.getByRole('button', { name: 'Показать на кассе' }).click()
  await expect(page.locator('.scan a.scan-code')).toHaveAttribute('href', COUPON)
})

test('a code that is not an address is left as plain text', async ({ page, request }) => {
  const merchant = uniqueMerchant('Handkasse')
  // No scheme: as likely a code typed off a card as a link, so not made one.
  const code = 'coupons.rossmann.de/xJ3-abc'
  await createCard(request, { merchant, code, value_amount: '25' })

  await openCard(page, merchant)
  await expect(page.locator('.code span')).toHaveText(code)
  await expect(page.locator('.code a')).toHaveCount(0)
})
