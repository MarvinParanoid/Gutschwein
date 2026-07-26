import { expect, test } from '@playwright/test'

import { createCard, uniqueMerchant } from './helpers'

/**
 * The language is never chosen by hand: it follows the client. In a browser that
 * is navigator.language, which Playwright sets from the context locale.
 */
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
