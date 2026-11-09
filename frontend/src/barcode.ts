/**
 * The version that goes into a barcode's address (`?v=`).
 *
 * The address is derived from the picture, but the bars are drawn from the card's
 * code, which can be corrected later. Without a version the service worker kept
 * answering the old address with the old bars — at the till, where a wrong number
 * means a failed payment. With it a corrected code is a different address, and the
 * server refuses an outdated one (`routers/barcodes.py`), so nothing cached under
 * an address can be anything but what that address names.
 *
 * Must match `app.barcode.version` byte for byte: FNV-1a, 32 bits, over the UTF-8
 * of `format + "\n" + code`. Both sides test the same vectors.
 */
export function barcodeVersion(code: string, format: string): string {
  let value = 0x811c9dc5
  for (const byte of new TextEncoder().encode(`${format}\n${code}`)) {
    value = Math.imul(value ^ byte, 0x01000193) >>> 0
  }
  return value.toString(16).padStart(8, '0')
}
