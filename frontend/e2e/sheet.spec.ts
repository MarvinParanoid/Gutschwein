import { expect, test } from '@playwright/test'

import { createCard, uniqueMerchant } from './helpers'

test('the top bar stays put while the list scrolls', async ({ page, request }) => {
  // Enough cards that the page actually scrolls.
  for (let i = 0; i < 12; i++) {
    await createCard(request, { merchant: uniqueMerchant('Scroll'), value_amount: '10' })
  }
  await page.goto('/')
  await page.locator('.card').first().waitFor()

  const before = await page.locator('.topbar').boundingBox()
  await page.mouse.wheel(0, 600)
  await page.waitForFunction(() => window.scrollY > 200)
  const after = await page.locator('.topbar').boundingBox()

  expect(after!.y).toBeCloseTo(before!.y, 0)
  // And it still covers what slides under it, rather than letting cards show through.
  await expect(page.locator('.burger')).toBeInViewport()
})

test('the sheet can be dragged away by its handle', async ({ page }) => {
  await page.goto('/')
  await page.locator('.burger').click()
  const sheet = page.locator('.sheet')
  await expect(sheet).toBeVisible()

  const box = (await sheet.boundingBox())!
  const startX = box.x + box.width / 2
  const startY = box.y + 12

  await page.mouse.move(startX, startY)
  await page.mouse.down()
  await page.mouse.move(startX, startY + 40, { steps: 5 })
  // Short pull: the sheet follows the finger but survives.
  await expect(sheet).toHaveCSS('transform', /matrix/)
  await page.mouse.move(startX, startY + 160, { steps: 8 })
  await page.mouse.up()

  await expect(sheet).toHaveCount(0)
})

test('a short pull leaves the sheet open', async ({ page }) => {
  await page.goto('/')
  await page.locator('.burger').click()
  const sheet = page.locator('.sheet')
  const box = (await sheet.boundingBox())!
  const x = box.x + box.width / 2

  await page.mouse.move(x, box.y + 12)
  await page.mouse.down()
  await page.mouse.move(x, box.y + 12 + 30, { steps: 4 })
  await page.mouse.up()

  await expect(sheet).toBeVisible()
})
