/**
 * Pictures for the demo, drawn in the browser.
 *
 * A demo card needs something to show in scan mode, and shipping photographs of
 * real gift cards would mean shipping other people's trademarks. These are SVG
 * stand-ins built from a data URI, so they cost no requests and no files.
 *
 * Everything needed to draw one is in the image id itself — `demo:<shop>:<code>`,
 * with an empty code for a card whose barcode never scanned. The colours come
 * from the same table as the tiles in the list, so a card looks like its shop.
 */

import { brandFor } from '../brands'

interface DemoCard {
  shop: string
  code: string
  colour: string
  ink: string
}

const UNBRANDED = { background: '#6b7280', color: '#ffffff' }

export const demoImageId = (shop: string, code = '') => `demo:${shop}:${code}`

function parse(imageId: string): DemoCard | null {
  const [prefix, shop, code] = imageId.split(':')
  if (prefix !== 'demo' || !shop) return null
  const brand = brandFor(shop) ?? UNBRANDED
  return { shop, code: code ?? '', colour: brand.background, ink: brand.color }
}

const dataUri = (svg: string) => `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`

/**
 * Bar widths derived from the digits themselves, so two cards never look alike
 * and the same card always looks the same. Not a real symbology — nothing here
 * is meant to scan.
 */
function bars(code: string, height: number, unit: number): { svg: string; width: number } {
  const rects: string[] = []
  let x = 0
  for (const character of code) {
    const digit = Number(character)
    const widths = [1 + (digit % 3), 1 + ((digit + 1) % 2), 1 + ((digit + 2) % 3), 1]
    widths.forEach((width, index) => {
      if (index % 2 === 0) {
        rects.push(`<rect x="${x}" y="0" width="${width * unit}" height="${height}"/>`)
      }
      x += width * unit
    })
  }
  return { svg: rects.join(''), width: x }
}

/** The redrawn code, the same idea as the server's barcode endpoint. */
export function demoBarcode(imageId: string): string {
  const card = parse(imageId)
  if (!card?.code) return ''
  const { svg, width } = bars(card.code, 90, 3)
  return dataUri(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} 120" width="${width}" height="120">` +
      `<rect width="100%" height="100%" fill="#ffffff"/><g fill="#000000">${svg}</g>` +
      `<text x="${width / 2}" y="113" text-anchor="middle" font-family="monospace" font-size="16"` +
      ` letter-spacing="2">${card.code}</text></svg>`,
  )
}

/** A stand-in for the screenshot you would normally send the bot. */
export function demoImage(imageId: string): string {
  // A photo the visitor added during the demo is already a data URI.
  if (imageId.startsWith('data:')) return imageId
  const card = parse(imageId)
  if (!card) return ''

  // Without a code the card is a plain face — the same as a photo whose barcode
  // came out unreadable.
  const body = card.code
    ? (() => {
        const { svg, width } = bars(card.code, 70, 2)
        return (
          `<g fill="#111111" transform="translate(${20 + (560 - width) / 2} 230)">${svg}</g>` +
          `<text x="300" y="345" text-anchor="middle" font-family="monospace" font-size="22"` +
          ` letter-spacing="3">${card.code}</text>`
        )
      })()
    : `<text x="300" y="300" text-anchor="middle" fill="#9aa0a6" font-family="sans-serif"` +
      ` font-size="26">Geschenkkarte</text>`

  return dataUri(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 420" width="600" height="420">` +
      `<rect width="600" height="420" fill="#f2f3f5"/>` +
      `<rect x="20" y="20" width="560" height="140" rx="16" fill="${card.colour}"/>` +
      `<text x="300" y="105" text-anchor="middle" fill="${card.ink}" font-family="sans-serif"` +
      ` font-size="46" font-weight="700">${card.shop.toUpperCase()}</text>` +
      `<rect x="20" y="180" width="560" height="220" rx="16" fill="#ffffff"/>` +
      body +
      `</svg>`,
  )
}
