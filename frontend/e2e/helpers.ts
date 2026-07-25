import { expect, type APIRequestContext, type Page } from '@playwright/test'

/** Unique per test, so tests never see each other's cards in a shared database. */
export function uniqueMerchant(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`
}

export async function createCard(
  request: APIRequestContext,
  fields: Record<string, unknown>,
): Promise<{ id: number; merchant: string }> {
  const response = await request.post('/api/vouchers', {
    data: { value_kind: 'amount', currency: 'EUR', ...fields },
  })
  expect(response.status()).toBe(201)
  return response.json()
}

/** Narrow the list down to one card by searching for its unique name. */
export async function findCard(page: Page, merchant: string) {
  await page.goto('/')
  await page.getByPlaceholder('Поиск').fill(merchant)
  const card = page.locator('.card', { hasText: merchant })
  await expect(card).toHaveCount(1)
  return card
}

export async function openCard(page: Page, merchant: string) {
  const card = await findCard(page, merchant)
  await card.click()
  await expect(page.locator('.topbar h1')).toHaveText(merchant)
}
