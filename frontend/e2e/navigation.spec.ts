import { expect, test } from '@playwright/test'

import { createCard, findCard, openCard, uniqueMerchant } from './helpers'

test('adding a card through the form puts it in the list', async ({ page }) => {
  const merchant = uniqueMerchant('Ikea')

  await page.goto('/')
  await page.locator('.fab').click()
  await expect(page.locator('.topbar h1')).toHaveText('Новый купон')

  await page.getByLabel('Магазин').fill(merchant)
  await page.getByLabel('Номинал').fill('35')
  await page.getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.locator('.topbar h1')).toHaveText(merchant)
  await expect(page.locator('.balance-value')).toHaveText('35 EUR')

  const card = await findCard(page, merchant)
  await expect(card).toContainText('35 EUR')
})

test('browser back returns to the list and keeps the shop filter', async ({ page, request }) => {
  const merchant = uniqueMerchant('Rossmann')
  await createCard(request, { merchant, value_amount: '20' })

  await page.goto('/')
  await page.locator('.chip', { hasText: merchant }).click()
  await expect(page.locator('.chip-summary')).toContainText(merchant)

  await page.locator('.card', { hasText: merchant }).click()
  await expect(page.locator('.topbar h1')).toHaveText(merchant)

  // Telegram's back button and the Android gesture both go through history.
  await page.goBack()
  await expect(page.locator('.chip-summary')).toContainText(merchant)
})

test('the shop chip narrows the list down', async ({ page, request }) => {
  const mine = uniqueMerchant('Jet')
  const other = uniqueMerchant('Total')
  await createCard(request, { merchant: mine, value_amount: '60' })
  await createCard(request, { merchant: other, value_amount: '25' })

  await page.goto('/')
  await page.locator('.chip', { hasText: mine }).click()

  await expect(page.locator('.card', { hasText: mine })).toHaveCount(1)
  await expect(page.locator('.card', { hasText: other })).toHaveCount(0)
})

test('the burger opens the lists and the statistics screen', async ({ page, request }) => {
  await createCard(request, { merchant: uniqueMerchant('Lidl'), value_amount: '40' })

  await page.goto('/')
  await page.locator('.burger').click()
  await expect(page.locator('.sheet-item').first()).toContainText('Активные')

  await page.locator('.sheet-item', { hasText: 'Статистика' }).click()
  await expect(page.locator('.topbar h1')).toHaveText('Статистика')
  await expect(page.locator('.stat-hero')).toContainText('EUR')
})

test('the archive is reachable and separate from the active list', async ({ page, request }) => {
  const merchant = uniqueMerchant('Aldi')
  const card = await createCard(request, { merchant, value_amount: '10' })

  await openCard(page, merchant)
  await page.getByRole('button', { name: 'В архив' }).click()
  await expect(page.locator('.topbar .badge')).toHaveText('В архиве')

  await page.goto('/')
  await page.getByPlaceholder('Поиск').fill(merchant)
  await expect(page.locator('.card', { hasText: merchant })).toHaveCount(0)

  await page.locator('.burger').click()
  await page.locator('.sheet-item', { hasText: 'Архив' }).click()
  await expect(page.locator('.card', { hasText: merchant })).toHaveCount(1)
  expect(card.id).toBeGreaterThan(0)
})
