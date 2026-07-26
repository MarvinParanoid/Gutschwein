/**
 * Shop identity for the list.
 *
 * Not the real logos: those are trademarks, and shipping their files in a public
 * repository is someone else's decision to make. Recognition at a glance comes
 * mostly from the colour anyway — the letters only separate the four German
 * retailers that are all red.
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

const BRANDS: Record<string, Brand> = {
  rewe: { label: 'RE', background: '#cc071e', color: '#ffffff' },
  penny: { label: 'PE', background: '#e30613', color: '#ffdd00' },
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
