/**
 * Pictures for the demo, drawn in the browser.
 *
 * A demo card needs something to show in scan mode, and shipping photographs of
 * real gift cards would mean shipping other people's trademarks. These are SVG
 * stand-ins built from a data URI, so they cost no requests and no files.
 */

interface DemoCard {
  merchant: string
  code: string
  colour: string
  ink: string
}

/** Image ids the seed hands out. Anything else is a photo the visitor uploaded. */
const CARDS: Record<string, DemoCard> = {
  'demo:rewe': { merchant: 'REWE', code: '4012345678901', colour: '#cc0817', ink: '#ffffff' },
  'demo:draft': { merchant: 'ALDI', code: '4260112340008', colour: '#00538f', ink: '#ffffff' },
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
  const card = CARDS[imageId]
  if (!card) return ''
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
  const card = CARDS[imageId]
  if (!card) return ''
  const { svg, width } = bars(card.code, 70, 2)
  const offset = (560 - width) / 2
  return dataUri(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 420" width="600" height="420">` +
      `<rect width="600" height="420" fill="#f2f3f5"/>` +
      `<rect x="20" y="20" width="560" height="140" rx="16" fill="${card.colour}"/>` +
      `<text x="300" y="105" text-anchor="middle" fill="${card.ink}" font-family="sans-serif"` +
      ` font-size="46" font-weight="700">${card.merchant}</text>` +
      `<rect x="20" y="180" width="560" height="220" rx="16" fill="#ffffff"/>` +
      `<g fill="#111111" transform="translate(${20 + offset} 230)">${svg}</g>` +
      `<text x="300" y="345" text-anchor="middle" font-family="monospace" font-size="22"` +
      ` letter-spacing="3">${card.code}</text></svg>`,
  )
}
