import { describe, expect, it } from 'vitest'

import { barcodeProblem, checkDigit, codeGroups, MANUAL_FORMATS } from './barcodeFormats'
import { t } from './i18n'

/**
 * The same cases as backend/tests/test_manual_barcode.py: the form's hint and the
 * server's refusal must agree, or the form would wave through what the server
 * then refuses — or the other way round.
 */
describe('barcodeProblem', () => {
  it.each([
    ['4006381333931', 'EAN-13'],
    ['96385074', 'EAN-8'],
    ['036000291452', 'UPC-A'],
    ['12345678', 'ITF'],
    ['GUT-2031 $/+%.', 'Code 39'],
    ['Gift-1234 abc!', 'Code 128'],
    ['https://example.com/card/1?x=ü', 'QR Code'],
    ['ABC-123', 'Data Matrix'],
    ['ABC-123', 'PDF417'],
    ['ABC-123', 'Aztec'],
  ])('accepts %s as %s', (code, format) => {
    expect(barcodeProblem(code, format)).toBeNull()
  })

  it.each([
    ['400638133393', 'EAN-13', t.barcode.digits('EAN-13', 13)],
    ['40063813339311', 'EAN-13', t.barcode.digits('EAN-13', 13)],
    ['40063813339A1', 'EAN-13', t.barcode.digits('EAN-13', 13)],
    ['4006381333932', 'EAN-13', t.barcode.checkDigit('EAN-13', 1)],
    ['96385075', 'EAN-8', t.barcode.checkDigit('EAN-8', 4)],
    ['036000291453', 'UPC-A', t.barcode.checkDigit('UPC-A', 2)],
    ['1234567', 'ITF', t.barcode.itf],
    ['12AB', 'ITF', t.barcode.itf],
    ['gut-2031', 'Code 39', t.barcode.code39],
    ['Grüße', 'Code 128', t.barcode.code128],
    ['ПОДАРОК', 'Code 128', t.barcode.code128],
  ])('refuses %s as %s', (code, format, message) => {
    expect(barcodeProblem(code, format)).toBe(message)
  })

  it('has nothing to say without a code or a format', () => {
    expect(barcodeProblem('', 'EAN-13')).toBeNull()
    expect(barcodeProblem('  ', 'EAN-13')).toBeNull()
    expect(barcodeProblem('12', null)).toBeNull()
    expect(barcodeProblem('12', undefined)).toBeNull()
  })

  it('leaves a format only a picture produced to the server', () => {
    expect(MANUAL_FORMATS).not.toContain('Code 93')
    expect(barcodeProblem('anything', 'Code 93')).toBeNull()
  })
})

describe('checkDigit', () => {
  it('computes the GS1 check digit', () => {
    expect(checkDigit('400638133393')).toBe(1)
    expect(checkDigit('9638507')).toBe(4)
    expect(checkDigit('03600029145')).toBe(2)
    // A sum already divisible by ten gives 0, not 10.
    expect(checkDigit('000000000000')).toBe(0)
  })
})

describe('codeGroups', () => {
  it('splits a long code into fours for reading aloud', () => {
    expect(codeGroups('6036001234567890123')).toEqual(['6036', '0012', '3456', '7890', '123'])
    expect(codeGroups('9998887776665').join('')).toBe('9998887776665')
  })

  it('leaves short codes and codes with their own separators alone', () => {
    expect(codeGroups('12345678')).toEqual(['12345678'])
    expect(codeGroups('GUT-2031-XYZ')).toEqual(['GUT-2031-XYZ'])
    expect(codeGroups('ab cd ef gh')).toEqual(['ab cd ef gh'])
  })
})
