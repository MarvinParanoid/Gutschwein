import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // The app updates itself: nobody is going to hunt for a refresh button
      // while standing at a till.
      registerType: 'autoUpdate',
      includeAssets: ['icon-192.png', 'icon-512.png', 'icon-maskable.png', 'favicon-32.png'],
      manifest: {
        name: 'Gutschwein — карты и купоны',
        short_name: 'Gutschwein',
        description: 'Подарочные карты семьи: остатки, сроки, штрихкод у кассы',
        lang: 'ru',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        theme_color: '#e0518a',
        background_color: '#ffffff',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icon-maskable.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        navigateFallback: '/index.html',
        // API routes must reach the server, not be answered with the shell.
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          {
            // Barcodes are drawn from the card's code, which can be corrected, so
            // their address carries a version of it (`?v=`, src/barcode.ts) and the
            // server refuses an outdated one. Under a versioned address the content
            // never changes, so cache first is safe — the till screen opens without
            // network — and a corrected code is simply a new address.
            urlPattern: ({ url }) =>
              url.pathname.startsWith('/api/barcodes/') && url.searchParams.has('v'),
            handler: 'CacheFirst',
            options: {
              cacheName: 'gutschwein-barcodes',
              expiration: { maxEntries: 100, maxAgeSeconds: 60 * 60 * 24 * 180 },
              cacheableResponse: { statuses: [200] },
              plugins: [
                {
                  // One version per barcode: once the new one is stored, the old
                  // ones can only ever be asked for by a stale copy of the card,
                  // and the server would refuse them anyway. Serialised into the
                  // generated sw.js, so it may use nothing but the worker's globals.
                  cacheDidUpdate: async ({ cacheName, request }) => {
                    const stored = new URL(request.url)
                    const cache = await caches.open(cacheName)
                    for (const key of await cache.keys()) {
                      const url = new URL(key.url)
                      if (url.pathname === stored.pathname && url.search !== stored.search) {
                        await cache.delete(key)
                      }
                    }
                  },
                },
              ],
            },
          },
          {
            // Card pictures never change: their names are content handles. Cache
            // first means the till screen opens without network.
            urlPattern: ({ url }) => url.pathname.startsWith('/api/images/'),
            handler: 'CacheFirst',
            options: {
              cacheName: 'gutschwein-cards',
              expiration: { maxEntries: 300, maxAgeSeconds: 60 * 60 * 24 * 180 },
              cacheableResponse: { statuses: [200] },
            },
          },
          {
            // Lists and balances: fresh when possible, last known when not.
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkFirst',
            method: 'GET',
            options: {
              cacheName: 'gutschwein-api',
              networkTimeoutSeconds: 4,
              expiration: { maxEntries: 60, maxAgeSeconds: 60 * 60 * 24 * 7 },
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
    }),
  ],
  build: {
    // The backend serves this build as static files from the same origin.
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
