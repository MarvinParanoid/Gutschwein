import { defineConfig } from 'vitest/config'

// Unit tests live next to the code they cover. The e2e specs under e2e/ belong
// to Playwright and would fail here the moment vitest tried to import them.
export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
  },
})
