import { readFileSync } from 'node:fs'

import { expect, test } from '@playwright/test'

import { createCard, openCard, uniqueMerchant } from './helpers'

const CARD_NUMBER = '2094599346555'
const FIXTURE = new URL('./fixtures/card-with-barcode.png', import.meta.url).pathname

test('a screenshot with a barcode becomes a redrawn code at the till', async ({
  page,
  request,
}) => {
  const upload = await request.post('/api/uploads', {
    multipart: {
      file: {
        name: 'card.png',
        mimeType: 'image/png',
        buffer: readFileSync(FIXTURE),
      },
    },
  })
  expect(upload.ok()).toBeTruthy()
  const { image_id: imageId } = await upload.json()

  const merchant = uniqueMerchant('Penny')
  const card = await createCard(request, { merchant, value_amount: '25', image_id: imageId })
  // The server read the number out of the picture on the way in.
  expect(card).toMatchObject({ code: CARD_NUMBER, barcode_format: 'Code 128' })

  await openCard(page, merchant)
  await page.locator('.hero-button').click()

  // The scan screen shows the redrawn vector code, not the screenshot.
  const shown = page.locator('.scan-image')
  await expect(shown).toHaveAttribute('src', /\/api\/barcodes\//)
  await expect(page.locator('.scan-code')).toHaveText(CARD_NUMBER)

  // …with the original photo one tap away, in case a scanner disagrees.
  await page.getByRole('button', { name: 'Фото' }).click()
  await expect(shown).toHaveAttribute('src', /\/api\/images\//)
})

test('zoom and rotation keep the image inside the frame', async ({ page, request }) => {
  const upload = await request.post('/api/uploads', {
    multipart: {
      file: { name: 'card.png', mimeType: 'image/png', buffer: readFileSync(FIXTURE) },
    },
  })
  const { image_id: imageId } = await upload.json()
  const merchant = uniqueMerchant('Jet')
  await createCard(request, { merchant, value_amount: '60', image_id: imageId })

  await openCard(page, merchant)
  await page.locator('.hero-button').click()

  await expect(page.locator('.zoom-level')).toHaveText('100%')
  await page.getByRole('button', { name: 'Увеличить' }).click()
  await expect(page.locator('.zoom-level')).toHaveText('160%')

  await page.getByRole('button', { name: 'Повернуть' }).click()

  // Rotation used to widen the layout box and push the image off to the right.
  const frame = await page.locator('.zoom-frame').boundingBox()
  const image = await page.locator('.scan-image').boundingBox()
  expect(frame).not.toBeNull()
  expect(image).not.toBeNull()
  const frameCentre = frame!.x + frame!.width / 2
  const imageCentre = image!.x + image!.width / 2
  expect(Math.abs(frameCentre - imageCentre)).toBeLessThan(2)
})

test('a card without a readable barcode falls back to the photo', async ({ page, request }) => {
  // A flat picture: nothing to decode.
  const blank = Buffer.from(
    '89504e470d0a1a0a0000000d494844520000000100000001080600000' +
      '01f15c4890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082',
    'hex',
  )
  const upload = await request.post('/api/uploads', {
    multipart: { file: { name: 'blank.png', mimeType: 'image/png', buffer: blank } },
  })
  const { image_id: imageId } = await upload.json()

  const merchant = uniqueMerchant('Edeka')
  const card = await createCard(request, { merchant, value_amount: '30', image_id: imageId })
  expect(card).toMatchObject({ barcode_format: null })

  await openCard(page, merchant)
  await page.locator('.hero-button').click()

  await expect(page.locator('.scan-image')).toHaveAttribute('src', /\/api\/images\//)
  await expect(page.getByRole('button', { name: 'Фото' })).toHaveCount(0)
})
