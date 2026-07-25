import { expect, test } from '@playwright/test'

import { createCard, openCard, uniqueMerchant } from './helpers'

test('till flow: open a card and write down what the receipt says is left', async ({
  page,
  request,
}) => {
  const merchant = uniqueMerchant('Rewe')
  await createCard(request, { merchant, value_amount: '50' })

  await openCard(page, merchant)
  await expect(page.locator('.balance-value')).toHaveText('50 EUR')

  await page.getByRole('button', { name: 'Обновить остаток' }).click()

  // "Осталось" is the default because that is the number printed on the receipt.
  await expect(page.locator('.segmented button.active')).toHaveText('Осталось')

  await page.locator('.balance-form input').first().fill('21.40')
  await page.getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.locator('.balance-value')).toHaveText('21.4 EUR')
  await expect(page.locator('.history')).toContainText('списал 28.6, осталось 21.4')
})

test('spending the last of it moves the card to the spent list', async ({ page, request }) => {
  const merchant = uniqueMerchant('Penny')
  await createCard(request, { merchant, value_amount: '15' })

  await openCard(page, merchant)
  await page.getByRole('button', { name: 'Обновить остаток' }).click()
  // Scoped to the pad: "Потратил полностью" is a different button on the page.
  await page.locator('.balance-form .segmented button', { hasText: 'Потратил' }).click()
  await page.locator('.balance-form input').first().fill('15')
  await page.getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.locator('.balance-value')).toHaveText('0 EUR')
  await expect(page.locator('.topbar .badge')).toHaveText('Использован')
})

test('a mistyped balance is refused with a readable reason', async ({ page, request }) => {
  const merchant = uniqueMerchant('Kaufland')
  await createCard(request, { merchant, value_amount: '20' })

  await openCard(page, merchant)
  await page.getByRole('button', { name: 'Обновить остаток' }).click()
  // More than the card ever held.
  await page.locator('.balance-form input').first().fill('999')
  await page.getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.locator('.balance-form .error')).toContainText('больше номинала')
  await expect(page.locator('.balance-value')).toHaveText('20 EUR')
})
