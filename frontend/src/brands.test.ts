import { describe, expect, it } from 'vitest'

import { BRANDS, brandFor } from './brands'

/** WCAG relative luminance, so the tiles can be checked rather than eyeballed. */
function contrast(a: string, b: string): number {
  const lum = (hex: string) => {
    const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    const [r, g, bl] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl
  }
  const [x, y] = [lum(a), lum(b)]
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

describe('the shop tiles', () => {
  it('are readable: the letters are the only thing telling two red shops apart', () => {
    const weak = Object.entries(BRANDS)
      .map(([slug, brand]) => [slug, contrast(brand.color, brand.background)] as const)
      .filter(([, ratio]) => ratio < 4.5)
    expect(weak).toEqual([])
  })

  it('match a shop however it is typed', () => {
    expect(brandFor('MediaMarkt')?.label).toBe('MM')
    expect(brandFor('Media Markt')?.label).toBe('MM')
    expect(brandFor('H&M')?.label).toBe('HM')
    expect(brandFor('TK Maxx')?.label).toBe('TKM')
    expect(brandFor('google play')?.label).toBe('GP')
    // The company name is on the receipt, the brand alone is on the sign.
    expect(brandFor('PKN Orlen')?.label).toBe('ORL')
  })

  it('gives each shop its own letters, whatever it is called', () => {
    // Aliases share a tile on purpose (rossman/rossmann, total/totalenergies). Two
    // different shops sharing one would be indistinguishable: most of these tiles
    // are some shade of red, so the letters are all that is left to tell them apart.
    const tileOf = new Map<string, string>()
    for (const brand of Object.values(BRANDS)) {
      const tile = `${brand.background} on ${brand.color}`
      expect(tileOf.get(brand.label) ?? tile).toBe(tile)
      tileOf.set(brand.label, tile)
    }
  })

  it('never matches on a substring', () => {
    // "Jetzt Markt" must not be served the Jet tile, hence whole words only.
    expect(brandFor('Jetzt Markt')).toBeNull()
    expect(brandFor('Ottokar')).toBeNull()
    expect(brandFor('')).toBeNull()
  })
})
