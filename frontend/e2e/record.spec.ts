import { test } from '@playwright/test'

/**
 * Records the README walkthrough. Not part of the suite: `make demo-gif` sets
 * RECORD and converts the video ffmpeg leaves behind.
 *
 * It drives the demo dataset, so the recording can never contain real cards.
 */
test.skip(!process.env.RECORD, 'recording only: RECORD=1 make demo-gif')

test.use({
  extraHTTPHeaders: {},
  locale: 'en-GB',
  video: { mode: 'on', size: { width: 420, height: 900 } },
})

/** Long enough to read what just changed, short enough to keep the file small. */
const BEAT = 900

test('walkthrough', async ({ page }) => {
  await page.goto('/demo')
  await page.locator('.card').first().waitFor()
  await page.waitForTimeout(BEAT * 2)

  // The till flow: find the card, show it to the scanner, write down what is left.
  await page.locator('.card', { hasText: 'Rewe' }).click()
  await page.locator('.balance-value').waitFor()
  await page.waitForTimeout(BEAT)

  await page.locator('.hero-button').click()
  await page.locator('.scan').waitFor()
  await page.waitForTimeout(BEAT * 2)
  await page.locator('.scan-actions button').last().click()
  await page.waitForTimeout(BEAT / 2)

  await page.getByRole('button', { name: 'Update balance' }).click()
  await page.waitForTimeout(BEAT / 2)
  await page.locator('.balance-form input').first().pressSequentially('21.40', { delay: 120 })
  await page.waitForTimeout(BEAT / 2)
  await page.getByRole('button', { name: 'Save' }).click()
  await page.waitForTimeout(BEAT * 2)

  // Back to the list, where the new balance is already showing.
  await page.goBack()
  await page.waitForTimeout(BEAT * 1.5)

  await page.locator('.burger').click()
  await page.waitForTimeout(BEAT / 2)
  await page.locator('.sheet-item', { hasText: 'Statistics' }).click()
  await page.locator('.stat-hero').waitFor()
  await page.waitForTimeout(BEAT)
  await page.mouse.wheel(0, 700)
  await page.waitForTimeout(BEAT * 1.5)
})
