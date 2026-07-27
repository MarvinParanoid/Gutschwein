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

/**
 * Presses the handle and returns where the finger now is.
 *
 * Through hover() on purpose: it waits for the element to stop moving, and the
 * sheet slides in over 0.18s. Measuring the box during that animation and
 * pressing at the number that comes out lands the press on the first menu item
 * instead, which closes the sheet through onSelect — and looks exactly like a
 * working dismiss gesture.
 */
async function grabHandle(page: import('@playwright/test').Page) {
  const handle = page.locator('.sheet-handle')
  await handle.hover()
  const box = (await handle.boundingBox())!
  const at = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
  await page.mouse.down()
  return at
}

test('the sheet can be dragged away by its handle', async ({ page }) => {
  await page.goto('/')
  await page.locator('.burger').click()
  const sheet = page.locator('.sheet')
  await expect(sheet).toBeVisible()

  const at = await grabHandle(page)
  await page.mouse.move(at.x, at.y + 40, { steps: 5 })
  // Short pull: the sheet follows the finger but survives. The entrance
  // animation is over by now, so a translation here is the drag and nothing else.
  await expect(sheet).toHaveCSS('transform', /matrix\(1, 0, 0, 1, 0, [1-9]/)
  await page.mouse.move(at.x, at.y + 160, { steps: 8 })
  await page.mouse.up()

  await expect(sheet).toHaveCount(0)
})

test('a short pull leaves the sheet open', async ({ page }) => {
  await page.goto('/')
  await page.locator('.burger').click()
  const sheet = page.locator('.sheet')
  await expect(sheet).toBeVisible()

  const at = await grabHandle(page)
  await page.mouse.move(at.x, at.y + 30, { steps: 4 })
  await page.mouse.up()

  await expect(sheet).toBeVisible()
  // Back where it started, rather than left hanging thirty pixels down.
  await expect(sheet).toHaveCSS('transform', 'none')
})
