import { expect, test } from '@playwright/test'

// A visitor following the demo link has no account and no dev header. Dropping
// it here is the point of the spec: whatever the demo does, it does alone.
test.use({ extraHTTPHeaders: {} })

/** Every request the page makes to the backend API, in order. */
function watchApi(page: import('@playwright/test').Page): string[] {
  const calls: string[] = []
  page.on('request', (request) => {
    const { pathname } = new URL(request.url())
    if (pathname.startsWith('/api')) calls.push(pathname)
  })
  return calls
}

test('the demo link opens a working app without an account', async ({ page }) => {
  const apiCalls = watchApi(page)

  await page.goto('/demo')
  await expect(page.locator('.demo-bar')).toBeVisible()
  // The shared path is swapped for the flag, so a reload is an ordinary visit.
  expect(new URL(page.url()).pathname).toBe('/')

  await expect(page.locator('.card', { hasText: 'Rewe' })).toBeVisible()

  await page.locator('.card', { hasText: 'Rossmann' }).click()
  await page.getByRole('button', { name: 'Обновить остаток' }).click()
  await page.locator('.balance-form input').first().fill('2.10')
  await page.getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.locator('.balance-value')).toHaveText('2.1 EUR')
  await expect(page.locator('.history')).toContainText('списал 6, осталось 2.1')

  // The whole session, and not one request left the page.
  expect(apiCalls).toEqual([])
})

test('the statistics add up from the made-up event log', async ({ page }) => {
  const apiCalls = watchApi(page)

  await page.goto('/demo')
  await page.locator('.burger').click()
  await page.locator('.sheet-item', { hasText: 'Статистика' }).click()

  await expect(page.locator('.topbar h1')).toHaveText('Статистика')
  await expect(page.locator('.stat-hero')).toContainText('EUR')
  await expect(page.locator('.columns .column')).toHaveCount(6)
  expect(apiCalls).toEqual([])
})

test('leaving the demo goes back to the locked app', async ({ page }) => {
  await page.goto('/demo')
  await page.locator('.demo-bar .btn').click()

  // No account, so the real app can only offer the way back in.
  await expect(page.locator('.empty')).toContainText('Нужен вход')
  await expect(page.getByRole('button', { name: 'Посмотреть демо' })).toBeVisible()

  await page.getByRole('button', { name: 'Посмотреть демо' }).click()
  await expect(page.locator('.demo-bar')).toBeVisible()
})

test('the demo refuses a mistyped balance the way the server would', async ({ page }) => {
  await page.goto('/demo')
  await page.locator('.card', { hasText: 'Kaufland' }).click()
  await page.getByRole('button', { name: 'Обновить остаток' }).click()
  // The card only ever held 20.
  await page.locator('.balance-form input').first().fill('999')
  await page.getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.locator('.balance-form .error')).toContainText('больше номинала (20 EUR)')
  await expect(page.locator('.balance-value')).toHaveText('20 EUR')
})
