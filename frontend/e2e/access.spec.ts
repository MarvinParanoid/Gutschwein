import { expect, test } from '@playwright/test'

test('the access screen lists devices and mints an invitation', async ({ page }) => {
  await page.goto('/')
  await page.locator('.burger').click()
  await page.locator('.sheet-item', { hasText: 'Доступ' }).click()
  await expect(page.locator('.topbar h1')).toHaveText('Доступ')

  // Signing in for the e2e run happens through the dev header, which creates no
  // session, so the list is empty and says so rather than showing a spinner.
  await expect(page.locator('.panel').last()).toContainText(/В браузере пока никто|это устройство/)

  await page.getByPlaceholder('Имя нового участника').fill('Бабушка')
  await page.getByRole('button', { name: 'Создать ссылку' }).click()

  const link = page.locator('.invite-link code')
  await expect(link).toContainText('/login#')
  // A one-time link is the whole credential: it must be shown in full.
  expect((await link.textContent())!.length).toBeGreaterThan(30)
})

test('a session can be signed out from the list', async ({ page, request }) => {
  // Redeem a dev token so there is a real session row to revoke.
  const { token } = await (await request.post('/api/auth/dev-token')).json()
  await page.goto(`/login#${token}`)
  await page.locator('.card, .empty').first().waitFor()

  await page.locator('.burger').click()
  await page.locator('.sheet-item', { hasText: 'Доступ' }).click()
  await expect(page.locator('.device').first()).toContainText('это устройство')
  // The current browser offers no way to sign itself out of the list.
  await expect(page.locator('.device', { hasText: 'это устройство' }).locator('.btn')).toHaveCount(0)
})
