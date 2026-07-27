/**
 * Shop identity for the list.
 *
 * Not the real logos: those are trademarks, and shipping their files in a public
 * repository is someone else's decision to make. Recognition at a glance comes
 * mostly from the colour anyway — the letters are what separate the many shops
 * whose brand is some shade of red or orange.
 *
 * The colours are the brands' own, except where their own pairing is unreadable
 * at 17px: Decathlon's blue and Airbnb's coral are both adjusted, since a tile
 * nobody can read defeats the purpose. `brands.test.ts` keeps every pair above
 * 4.5:1.
 *
 * To use actual logos, drop a PNG into `src/logos/<slug>.png` (the slug is the
 * shop name in lowercase, no spaces). It is collected at build time, so a shop
 * without a file is never requested — the tile is drawn straight away.
 */

export interface Brand {
  label: string
  background: string
  color: string
}

export const BRANDS: Record<string, Brand> = {
  rewe: { label: 'RE', background: '#cc071e', color: '#ffffff' },
  penny: { label: 'PE', background: '#b8000e', color: '#ffdd00' },
  kaufland: { label: 'KL', background: '#e10915', color: '#ffffff' },
  ikea: { label: 'IK', background: '#0058a3', color: '#ffda1a' },
  rossmann: { label: 'RO', background: '#c4022b', color: '#ffffff' },
  rossman: { label: 'RO', background: '#c4022b', color: '#ffffff' },
  jet: { label: 'JET', background: '#ffd500', color: '#1a1a1a' },
  totalenergies: { label: 'TE', background: '#ed0000', color: '#ffffff' },
  total: { label: 'TE', background: '#ed0000', color: '#ffffff' },
  dm: { label: 'DM', background: '#00427d', color: '#ffffff' },
  lidl: { label: 'LD', background: '#0050aa', color: '#ffe500' },
  aldi: { label: 'AL', background: '#00005f', color: '#f7941e' },
  douglas: { label: 'DG', background: '#e5007e', color: '#ffffff' },
  amazon: { label: 'AMZ', background: '#ff9900', color: '#232f3e' },
  mediamarkt: { label: 'MM', background: '#df0000', color: '#ffffff' },
  media: { label: 'MM', background: '#df0000', color: '#ffffff' },
  saturn: { label: 'SAT', background: '#eb680b', color: '#1a1a1a' },
  obi: { label: 'OBI', background: '#ff7f00', color: '#1a1a1a' },
  hm: { label: 'HM', background: '#e50010', color: '#ffffff' },
  decathlon: { label: 'DEC', background: '#0072ad', color: '#ffffff' },
  tkmaxx: { label: 'TKM', background: '#e4002b', color: '#ffffff' },
  louis: { label: 'LO', background: '#f2a900', color: '#1a1a1a' },
  primark: { label: 'PRI', background: '#00263a', color: '#ffffff' },
  lieferando: { label: 'LFR', background: '#ff8000', color: '#1a1a1a' },
  googleplay: { label: 'GP', background: '#01875f', color: '#ffffff' },
  airbnb: { label: 'AIR', background: '#ff5a5f', color: '#4a1113' },
  zalando: { label: 'ZAL', background: '#ff6900', color: '#1a1a1a' },
  otto: { label: 'OT', background: '#d4021d', color: '#ffffff' },
  wolt: { label: 'WLT', background: '#00c2e8', color: '#00374a' },
}

/** Words of the name plus the whole thing glued together, as in the expiry rules. */
function tokens(merchant: string): string[] {
  const words = merchant.toLowerCase().match(/[a-zа-яё0-9]+/g) ?? []
  return [...words, words.join('')]
}

export function brandFor(merchant: string): Brand | null {
  for (const token of tokens(merchant)) {
    if (BRANDS[token]) return BRANDS[token]
  }
  return null
}

// Resolved by Vite at build time: whatever PNGs sit in src/logos, keyed by slug.
// An empty directory yields an empty map, and then no logo is ever requested.
const LOGOS: Record<string, string> = Object.fromEntries(
  Object.entries(
    import.meta.glob<string>('./logos/*.png', {
      eager: true,
      query: '?url',
      import: 'default',
    }),
  ).map(([path, url]) => [path.replace(/^.*\/|\.png$/g, ''), url]),
)

/** The real logo for a shop, when someone has added the file. */
export function logoUrl(merchant: string): string | null {
  for (const token of tokens(merchant)) {
    if (LOGOS[token]) return LOGOS[token]
  }
  return null
}
