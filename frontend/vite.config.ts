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
            // Card pictures and barcodes never change: their names are content
            // handles. Cache first means the till screen opens without network.
            urlPattern: ({ url }) => /^\/api\/(images|barcodes)\//.test(url.pathname),
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
