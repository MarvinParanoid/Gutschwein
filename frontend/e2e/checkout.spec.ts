import { readFileSync } from 'node:fs'

import { expect, test } from './fixtures'

import { createCard, findCard, openCard, uniqueMerchant } from './helpers'

/**
 * Stage 1, checkout: a code typed by hand becomes a barcode, the till screen is
 * one tap from the list, and it shows the shop, the balance and a large code that
 * copies. Codes here are invented — a real card number in a public repository is
 * a real card number.
 */

const EAN13 = '4006381333931'
const EAN13_WRONG = '4006381333932'
const FIXTURE = new URL('./fixtures/card-with-barcode.png', import.meta.url).pathname

test.use({ permissions: ['clipboard-read', 'clipboard-write'] })

test('a code typed in the form becomes a barcode at the till, with no picture', async ({
  page,
}) => {
  const merchant = uniqueMerchant('Handkasse')
  await page.goto('/')
  await page.getByRole('button', { name: 'Добавить' }).click()

  await page.locator('#merchant').fill(merchant)
  await page.locator('#amount').fill('25')
  await page.getByRole('button', { name: 'Дополнительно ▾' }).click()
  await page.locator('#barcode-format').selectOption('EAN-13')

  // The form says what is wrong while the code is typed, before anything is sent.
  await page.locator('#code').fill(EAN13_WRONG)
  await expect(page.locator('.field-error')).toHaveText(
    'EAN-13: неверная контрольная цифра — последней должна быть 1. Проверьте код',
  )
  await expect(page.locator('#code')).toHaveAttribute('aria-invalid', 'true')

  await page.locator('#code').fill(EAN13)
  await expect(page.locator('.field-error')).toHaveCount(0)
  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.locator('.topbar h1')).toHaveText(merchant)

  await page.getByRole('button', { name: '▮▮ Показать на кассе' }).click()

  const scan = page.locator('.scan')
  await expect(scan.locator('.scan-merchant')).toHaveText(merchant)
  await expect(scan.locator('.scan-amount')).toContainText('25 EUR')
  // Drawn by the server and fetched with credentials: shown inline, not by address.
  await expect(scan.locator('.scan-image')).toHaveAttribute('src', /^data:image\/svg\+xml/)
  await expect(scan.locator('.scan-code')).toHaveText(EAN13)
  // Nothing to switch to: there is no photo.
  await expect(scan.getByRole('button', { name: '🖼 Фото' })).toHaveCount(0)
})

test('the server refuses what the form would have flagged', async ({ page, request }) => {
  const merchant = uniqueMerchant('Prüfziffer')
  const refused = await request.post('/api/vouchers', {
    data: { merchant, code: EAN13_WRONG, barcode_format: 'EAN-13' },
  })
  expect(refused.status()).toBe(422)

  // And in the form, a refusal from the server is shown, not swallowed.
  const card = await createCard(request, { merchant, code: EAN13, barcode_format: 'EAN-13' })
  await page.goto('/')
  await openCard(page, merchant)
  await page.getByRole('button', { name: '✏️ Изменить' }).click()
  await page.locator('#code').fill('12345')
  await expect(page.locator('.field-error')).toContainText('нужно ровно 13 цифр')
  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.locator('.error')).toContainText('нужно ровно 13 цифр')

  const stored = await (await request.get(`/api/vouchers/${card.id}`)).json()
  expect(stored.code).toBe(EAN13)
})

test('the till is one tap from the list, and closing it stays on the list', async ({
  page,
  request,
}) => {
  const merchant = uniqueMerchant('Listkasse')
  const code = 'GIFT-2031-0042'
  await createCard(request, {
    merchant,
    value_amount: '40',
    code,
    barcode_format: 'Code 128',
  })

  const card = await findCard(page, merchant)
  const row = page.locator('.card-row', { has: card })
  await row.getByRole('button', { name: 'Показать на кассе' }).click()

  const scan = page.locator('.scan')
  await expect(scan.locator('.scan-merchant')).toHaveText(merchant)
  await expect(scan.locator('.scan-amount')).toContainText('Остаток')
  await expect(scan.locator('.scan-amount')).toContainText('40 EUR')
  await expect(scan.locator('.scan-image')).toHaveAttribute('src', /^data:image\/svg\+xml/)

  // The number copies as it is, without the spacing it is shown with.
  await scan.getByRole('button', { name: 'Копировать' }).click()
  await expect(scan.getByRole('button', { name: 'Скопировано ✓' })).toBeVisible()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(code)

  await scan.getByRole('button', { name: 'Готово' }).click()
  await expect(scan).toHaveCount(0)
  // Still the list: the card was never opened.
  await expect(page.getByPlaceholder('Поиск')).toHaveValue(merchant)
  await expect(page.locator('.topbar h1')).not.toHaveText(merchant)
})

test('a card with a picture keeps its capability address at the till', async ({
  page,
  request,
}) => {
  const upload = await request.post('/api/uploads', {
    multipart: {
      file: { name: 'card.png', mimeType: 'image/png', buffer: readFileSync(FIXTURE) },
    },
  })
  const { image_id: imageId } = await upload.json()
  const merchant = uniqueMerchant('Bildkasse')
  await createCard(request, { merchant, value_amount: '15', image_id: imageId })

  const card = await findCard(page, merchant)
  await page.locator('.card-row', { has: card }).getByRole('button', { name: 'Показать на кассе' }).click()

  // The recognised barcode's path is unchanged: versioned, cache-first, by address.
  await expect(page.locator('.scan-image')).toHaveAttribute('src', /^\/api\/barcodes\/.+\?v=[0-9a-f]{64}$/)
  await page.getByRole('button', { name: '🖼 Фото' }).click()
  await expect(page.locator('.scan-image')).toHaveAttribute('src', /\/api\/images\//)
})

test('a code without a barcode type is shown large, as text to read out', async ({
  page,
  request,
}) => {
  const merchant = uniqueMerchant('Nurnummer')
  const code = '6036001234567890123'
  await createCard(request, { merchant, value_amount: '10', code })

  const card = await findCard(page, merchant)
  await page.locator('.card-row', { has: card }).getByRole('button', { name: 'Показать на кассе' }).click()

  const scan = page.locator('.scan')
  await expect(scan.locator('.scan-image')).toHaveCount(0)
  await expect(scan.locator('.scan-code.large')).toHaveText(code)
  await expect(scan.locator('.scan-code span')).toHaveCount(5) // groups of four
  await expect(scan.getByText('Штрихкода нет')).toBeVisible()
  // Nothing to rotate.
  await expect(scan.getByRole('button', { name: '↻ Повернуть' })).toHaveCount(0)
})

test('a card with neither a picture nor a code gets no till button', async ({
  page,
  request,
}) => {
  const merchant = uniqueMerchant('Ohnecode')
  await createCard(request, { merchant, value_amount: '5' })

  const card = await findCard(page, merchant)
  await expect(page.locator('.card-row', { has: card }).locator('.card-till')).toHaveCount(0)
})

test.describe('narrow phone', () => {
  test.use({ viewport: { width: 360, height: 740 } })

  test('the list and the till fit a 360 px screen without sideways scrolling', async ({
    page,
    request,
  }) => {
    const merchant = uniqueMerchant('Ein sehr langer Ladenname')
    await createCard(request, {
      merchant,
      value_amount: '123.45',
      code: '6036001234567890123',
      barcode_format: 'Code 128',
    })

    const card = await findCard(page, merchant)
    const overflow = () =>
      page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(await overflow()).toBe(0)

    const till = page.locator('.card-row', { has: card }).locator('.card-till')
    const box = await till.boundingBox()
    expect(box!.x + box!.width).toBeLessThanOrEqual(360)
    // Big enough for a thumb.
    expect(box!.width).toBeGreaterThanOrEqual(44)

    await till.click()
    await expect(page.locator('.scan-image')).toBeVisible()
    expect(await overflow()).toBe(0)
    for (const selector of ['.scan-code', '.scan-actions', '.scan-merchant']) {
      const element = await page.locator(selector).boundingBox()
      expect(element!.x).toBeGreaterThanOrEqual(0)
      expect(element!.x + element!.width).toBeLessThanOrEqual(360)
    }
  })
})

test.describe('english', () => {
  test.use({ locale: 'en-GB' })

  test('the till speaks the device language', async ({ page, request }) => {
    const merchant = uniqueMerchant('Englishtill')
    await createCard(request, { merchant, value_amount: '7', code: EAN13, barcode_format: 'EAN-13' })

    await page.goto('/')
    await page.getByPlaceholder('Search').fill(merchant)
    const card = page.locator('.card', { hasText: merchant })
    await page.locator('.card-row', { has: card }).getByRole('button', { name: 'Show at the till' }).click()
    await expect(page.locator('.scan-amount')).toContainText('Balance')
    await expect(page.getByRole('button', { name: 'Copy' })).toBeVisible()
  })
})

test('the till works from the keyboard: in, around, out, and back to where it was', async ({
  page,
  request,
}) => {
  const merchant = uniqueMerchant('Tastatur')
  await createCard(request, { merchant, value_amount: '12', code: EAN13, barcode_format: 'EAN-13' })
  const card = await findCard(page, merchant)
  const till = page.locator('.card-row', { has: card }).locator('.card-till')

  await till.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: merchant })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Готово' })).toBeFocused()

  // Tab cycles inside the dialog, never to the list behind it.
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('.scan')))).toBe(true)
  }
  for (let i = 0; i < 3; i++) {
    await page.keyboard.press('Shift+Tab')
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('.scan')))).toBe(true)
  }

  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(till).toBeFocused()
})

test('the last card’s till button is not hidden under the add button', async ({
  page,
  request,
}) => {
  // Enough cards to scroll, and the one under test sorted last (latest expiry).
  const prefix = uniqueMerchant('Unten')
  for (let i = 0; i < 6; i++) {
    await createCard(request, {
      merchant: `${prefix}-${i}`,
      value_amount: '5',
      code: `BOTTOM-${i}`,
      valid_until: `2040-01-0${i + 1}`,
    })
  }
  await page.setViewportSize({ width: 360, height: 640 })
  await page.goto('/')
  await page.getByPlaceholder('Поиск').fill(prefix)
  await expect(page.locator('.card-row')).toHaveCount(6)

  const last = page.locator('.card-row').last()
  await expect(last).toContainText(`${prefix}-5`)
  // Scrolled all the way down, as a thumb does: what is under the button's centre?
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  // The whole button, not just its middle: the "+" used to cover its lower half.
  const hits = await last.locator('.card-till').evaluate((button) => {
    const r = button.getBoundingClientRect()
    return [0.2, 0.5, 0.9].map((share) => {
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height * share)
      return top === button || button.contains(top)
    })
  })
  expect(hits).toEqual([true, true, true])
  await last.locator('.card-till').click()
  await expect(page.locator('.scan-merchant')).toHaveText(`${prefix}-5`)
})
