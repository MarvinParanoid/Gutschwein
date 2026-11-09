import { t } from './i18n'

/**
 * The symbologies a code typed by hand can be drawn in — the server's
 * `barcode.MANUAL_FORMATS`, spelled the way the decoder names them, because a
 * card's `barcode_format` is the same field whichever of the two filled it.
 *
 * The rules mirror `barcode.problem()` so the form can say what is wrong while
 * the code is being typed. The server stays the judge: it refuses what these
 * miss, in the same words.
 */
export const MANUAL_FORMATS = [
  'Code 128',
  'EAN-13',
  'EAN-8',
  'UPC-A',
  'Code 39',
  'ITF',
  'QR Code',
  'Data Matrix',
  'PDF417',
  'Aztec',
] as const

const CHECKED_LENGTH: Record<string, number> = { 'EAN-13': 13, 'EAN-8': 8, 'UPC-A': 12 }
const DIGITS = /^[0-9]+$/
const CODE39 = /^[0-9A-Z \-.$/+%]+$/
const CODE128 = /^[\x20-\x7e]+$/

/** The GS1 check digit for `digits`, the number without its last digit. */
export function checkDigit(digits: string): number {
  let total = 0
  for (let i = 0; i < digits.length; i++) {
    const digit = Number(digits[digits.length - 1 - i])
    total += digit * (i % 2 === 0 ? 3 : 1)
  }
  return (10 - (total % 10)) % 10
}

/**
 * Why `code` cannot be drawn as `format`, or null when it can — or when there is
 * nothing to judge yet (no code, no format, or a format only a picture produced).
 */
export function barcodeProblem(
  code: string | null | undefined,
  format: string | null | undefined,
): string | null {
  const value = (code ?? '').trim()
  if (!value || !format) return null
  const length = CHECKED_LENGTH[format]
  if (length !== undefined) {
    if (!DIGITS.test(value) || value.length !== length) return t.barcode.digits(format, length)
    const expected = checkDigit(value.slice(0, -1))
    if (Number(value.at(-1)) !== expected) return t.barcode.checkDigit(format, expected)
    return null
  }
  if (format === 'ITF' && (!DIGITS.test(value) || value.length % 2)) return t.barcode.itf
  if (format === 'Code 39' && !CODE39.test(value)) return t.barcode.code39
  if (format === 'Code 128' && !CODE128.test(value)) return t.barcode.code128
  return null
}

/**
 * The code as a cashier reads it off the screen: long runs of digits and letters
 * in groups of four. Only for display — the groups are separate elements, so the
 * text still copies (and tests still read) as the bare code.
 */
export function codeGroups(code: string): string[] {
  if (code.length < 9 || !/^[0-9A-Za-z]+$/.test(code)) return [code]
  const groups: string[] = []
  for (let i = 0; i < code.length; i += 4) groups.push(code.slice(i, i + 4))
  return groups
}
