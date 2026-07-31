import { expect, test, type Page } from '@playwright/test'

import { ru } from '../src/i18n/ru'
import { createCard, uniqueMerchant } from './helpers'

/**
 * Several currencies at once.
 *
 * Every test brings its own cards in both currencies: the suite shares one
 * database, so "how many currencies exist" is not something a single spec can
 * assume — which is exactly why the switcher is driven by the data and not by a
 * setting.
 */
async function openStats(page: Page) {
  await page.goto('/')
  await page.locator('.burger').click()
  await page.locator('.sheet-item', { hasText: ru.stats.title }).click()
  await expect(page.locator('.stat-hero')).toBeVisible()
}

test('each currency is counted, and shown, on its own', async ({ page, request }) => {
  const merchant = uniqueMerchant('Biedronka')
  // Two euro cards against one złoty card, so the euro block is the busier one.
  await createCard(request, { merchant: uniqueMerchant('Rewe'), value_amount: '10' })
  await createCard(request, { merchant: uniqueMerchant('Penny'), value_amount: '20' })
  const card = await createCard(request, { merchant, value_amount: '200', currency: 'PLN' })
  await request.post(`/api/vouchers/${card.id}/balance`, { data: { spent: '115.73' } })

  await openStats(page)

  const tabs = page.locator('.segmented.currencies button')
  await expect(tabs.filter({ hasText: 'EUR' })).toHaveCount(1)
  await expect(tabs.filter({ hasText: 'PLN' })).toHaveCount(1)
  // The busier currency leads, and its own figures are what the page opens on.
  await expect(tabs.first()).toHaveText('EUR')
  const euroTotal = await page.locator('.stat-hero').innerText()
  expect(euroTotal).toContain('EUR')

  await tabs.filter({ hasText: 'PLN' }).click()
  await expect(page.locator('.stat-hero')).toHaveText('84.27 PLN')
  await expect(page.locator('.kpi-value').first()).toHaveText('115.73 PLN')
  // Only its own shop: the euro shops belong to the other block.
  const shops = page.locator('.panel', { hasText: ru.stats.whereItGoes }).locator('.bar-label')
  await expect(shops).toHaveText([merchant])

  // Back to the euro block, untouched by any of it.
  await tabs.first().click()
  await expect(page.locator('.stat-hero')).toHaveText(euroTotal)
})

test('one currency needs no switcher', async ({ page }) => {
  // The demo dataset is euro-only and lives in the browser, so it is the one place
  // the single-currency case can be checked without the shared database.
  await page.goto('/demo')
  await page.locator('.card').first().waitFor()
  await page.locator('.burger').click()
  await page.locator('.sheet-item', { hasText: ru.stats.title }).click()
  await expect(page.locator('.stat-hero')).toBeVisible()

  await expect(page.locator('.segmented.currencies')).toHaveCount(0)
})

test('the form only lets a currency code be typed', async ({ page }) => {
  await page.goto('/')
  await page.locator('.fab').click()
  await page.getByLabel(ru.form.merchant).fill(uniqueMerchant('Zabka'))
  await page.getByLabel(ru.form.faceValue).fill('50')

  const currency = page.getByLabel(ru.form.currency)
  await currency.fill('')
  // Lowercase would split one currency into two groups; a digit is not a code.
  await currency.pressSequentially('pln9')
  await expect(currency).toHaveValue('PLN')

  await page.getByRole('button', { name: ru.form.save }).click()
  await expect(page.locator('.balance-value')).toHaveText('50 PLN')
})
