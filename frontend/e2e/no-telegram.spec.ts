import { expect, test } from '@playwright/test'

import { ru } from '../src/i18n/ru'
import { createCard, openCard, uniqueMerchant } from './helpers'

/**
 * The app outside Telegram: the browser, and the installed PWA.
 *
 * index.html loads the Telegram SDK from telegram.org on every page, so
 * `window.Telegram.WebApp` answers here too — reporting Bot API 6.0, with no host
 * behind it. Anything routed through it therefore has to be gated on `initData`,
 * not on the object being there. Both tests below are regressions: the SDK used to
 * be trusted, and it silently ate a confirm and the dark theme.
 */

/** Scoped: the card page has a delete button of its own. */
const removeComment = (page: import('@playwright/test').Page) =>
  page.locator('.comment').getByRole('button', { name: ru.comments.delete })

test('a comment can be deleted', async ({ page, request }) => {
  page.on('dialog', (dialog) => dialog.accept())
  const merchant = uniqueMerchant('Kommentar')
  const card = await createCard(request, { merchant, value_amount: '25' })
  await request.post(`/api/vouchers/${card.id}/comments`, { data: { text: 'в бардачке' } })

  await openCard(page, merchant)
  await expect(page.locator('.comment')).toHaveCount(1)
  await removeComment(page).click()

  await expect(page.locator('.comment')).toHaveCount(0)
  await expect(page.locator('.panel', { hasText: ru.comments.title })).toContainText(
    ru.comments.empty,
  )
  // Gone on the server, not just on the screen.
  const left = await request.get(`/api/vouchers/${card.id}/comments`)
  expect(await left.json()).toEqual([])
})

test("another member's comment cannot", async ({ page }) => {
  await page.goto('/demo')
  await page.locator('.card', { hasText: 'Jet' }).first().click()
  await expect(page.locator('.comment')).toHaveCount(1)
  await expect(removeComment(page)).toHaveCount(0)
})

test.describe('dark mode', () => {
  test.use({ colorScheme: 'dark' })

  test('follows the OS, not the SDK', async ({ page }) => {
    await page.goto('/demo')
    await expect(page.locator('.card').first()).toBeVisible()
    const theme = await page.evaluate(() => ({
      // A stamped 'light' here would pull the light status colours onto a dark
      // surface: --danger falls to 3.96:1 against --bg, under the 4.5 bar.
      stamped: document.documentElement.dataset.tgTheme ?? null,
      danger: getComputedStyle(document.documentElement).getPropertyValue('--danger').trim(),
    }))
    expect(theme).toEqual({ stamped: null, danger: '#ff7b7b' })
  })
})
