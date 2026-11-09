import { describe, expect, it } from 'vitest'

import { barcodeVersion } from './barcode'

describe('barcodeVersion', () => {
  // The same vectors as backend/tests/test_barcode.py: the server checks what the
  // client computes, so a mismatch would refuse every barcode.
  it.each([
    ['9998887776665', 'Code 128', '31f6f200'],
    ['Ё-1', 'EAN-13', 'fde4f6c1'],
    ['', '', '0f0c6cdd'],
  ])('matches the server for %j / %j', (code, format, expected) => {
    expect(barcodeVersion(code, format)).toBe(expected)
  })

  it('changes when the code is corrected', () => {
    expect(barcodeVersion('1111', 'EAN-13')).not.toBe(barcodeVersion('1112', 'EAN-13'))
  })

  it('changes when only the symbology changes', () => {
    expect(barcodeVersion('1111', 'EAN-13')).not.toBe(barcodeVersion('1111', 'Code 128'))
  })
})
