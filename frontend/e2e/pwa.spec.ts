import { expect, test } from './fixtures'

test('the app is installable: manifest, icons and service worker are served', async ({
  page,
  request,
}) => {
  await page.goto('/')
  const href = await page.locator('link[rel="manifest"]').getAttribute('href')
  expect(href).toBeTruthy()

  const manifest = await (await request.get(href!)).json()
  expect(manifest).toMatchObject({ display: 'standalone', start_url: '/' })
  expect(manifest.icons.length).toBeGreaterThanOrEqual(2)
  // Android crops icons to its own shape; without a maskable one it crops badly.
  expect(manifest.icons.some((i: { purpose?: string }) => i.purpose === 'maskable')).toBe(true)

  for (const icon of manifest.icons) {
    const response = await request.get(icon.src)
    expect(response.status(), icon.src).toBe(200)
  }

  const sw = await request.get('/sw.js')
  expect(sw.status()).toBe(200)
})

test('a browser context opened by hand carries no credentials', async ({ browser, page }) => {
  // The guard for every test below that opens a "plain browser": if the dev
  // member's header leaked into it, a sign-in test would pass without its cookie
  // doing anything (see e2e/fixtures.ts).
  const plain = await browser.newContext()
  const probe = await plain.newPage()
  await probe.goto('/')
  const answer = await probe.evaluate(async () => {
    const response = await fetch('/api/me')
    return { status: response.status, reason: response.headers.get('X-Auth-Failure') }
  })
  expect(answer).toEqual({ status: 401, reason: 'signed-out' })
  expect((await plain.request.get('/api/me')).status()).toBe(401)
  await plain.close()

  // …while the test's own page is the dev member, as the rest of the suite needs.
  await page.goto('/')
  expect(await page.evaluate(async () => (await fetch('/api/me')).status)).toBe(200)
})

test('the login link from the bot opens a working session in a plain browser', async ({
  browser,
  request,
}) => {
  const { token } = await (await request.post('/api/auth/dev-token')).json()

  // A context with no dev header and no Telegram: a browser off the home screen.
  const context = await browser.newContext({ viewport: { width: 420, height: 900 } })
  const page = await context.newPage()

  await page.goto(`/login#${token}`)

  // The list loads, which means /api/me answered — the cookie is doing the work,
  // since this context has no dev header (checked above).
  await expect(page.locator('.topbar h1')).toBeVisible()
  // And the one-time token is gone from the address bar.
  expect(new URL(page.url()).pathname).toBe('/')
  expect(page.url()).not.toContain(token)

  const cookies = await context.cookies()
  const session = cookies.find((c) => c.name === 'gutschwein_session')
  expect(session).toBeTruthy()
  expect(session!.httpOnly).toBe(true)

  await context.close()
})

test('a used or bogus link explains itself instead of showing an empty app', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 420, height: 900 } })
  const page = await context.newPage()

  await page.goto('/login#definitely-not-a-token')

  await expect(page.locator('.empty')).toContainText('Ссылка недействительна')
  await expect(page.locator('.empty')).toContainText('/login')
  await context.close()
})
