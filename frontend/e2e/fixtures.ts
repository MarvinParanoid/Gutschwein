import { test as base } from '@playwright/test'

export { expect } from '@playwright/test'

/**
 * The dev member's header, given to exactly two things: the test's own `page`
 * (through its context) and the `request` client.
 *
 * It used to be `use.extraHTTPHeaders` in playwright.config.ts, and the test
 * runner applies `use` options to every context — including one a test opens
 * with `browser.newContext()` to be a plain browser. Such a "signed-out" browser
 * was in fact signed in by the header, whatever its cookie said, so a sign-in or
 * sign-out test could pass without its cookie doing anything. Here a context made
 * by hand starts with no credentials at all; pwa.spec.ts checks that it does.
 *
 * The backend honours the header only with DEV_MODE on, as in this suite.
 */
export const DEV_USER = { 'X-Dev-User': '1000' }

export const test = base.extend({
  context: async ({ context }, use) => {
    await context.setExtraHTTPHeaders(DEV_USER)
    await use(context)
  },
  request: async ({ playwright, baseURL }, use) => {
    const request = await playwright.request.newContext({ baseURL, extraHTTPHeaders: DEV_USER })
    await use(request)
    await request.dispose()
  },
})
