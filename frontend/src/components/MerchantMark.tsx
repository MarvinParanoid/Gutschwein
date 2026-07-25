import { useState } from 'react'

import { brandFor, logoUrl } from '../brands'

/**
 * The square in front of a card in the list.
 *
 * Always the shop's mark, never the voucher photo: a thumbnail of a barcode
 * screenshot is unreadable at 56px and looks the same for every card. The photo
 * is one tap away on the card itself, where it is large enough to matter.
 *
 * A real logo file in `public/logos/<slug>.png` wins if someone adds one;
 * otherwise a tile in the shop's colours, or its initial for an unknown shop.
 */
export default function MerchantMark({ merchant }: { merchant: string }) {
  const [logoFailed, setLogoFailed] = useState(false)

  const logo = merchant && !logoFailed ? logoUrl(merchant) : null
  if (logo) {
    return (
      <img
        className="thumb"
        src={logo}
        alt=""
        loading="lazy"
        // No such file is the normal case, not an error worth showing.
        onError={() => setLogoFailed(true)}
      />
    )
  }

  const brand = brandFor(merchant)
  const initial = (merchant || '?').trim().charAt(0).toUpperCase()
  return (
    <div
      className="thumb placeholder"
      style={brand ? { background: brand.background, color: brand.color } : undefined}
    >
      {brand ? brand.label : initial}
    </div>
  )
}
