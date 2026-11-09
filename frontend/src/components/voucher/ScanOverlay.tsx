import { useState } from 'react'

import { barcodeUrl, imageUrl } from '../../api'
import { isDemo } from '../../demo/session'
import { t } from '../../i18n'
import { useOnline } from '../../useOnline'
import { useOverlay } from '../../useOverlay'
import ZoomableImage from '../ZoomableImage'

/**
 * Fullscreen view for the checkout counter: white background and the biggest
 * possible image, because that is what a barcode scanner needs off a screen.
 */
export default function ScanOverlay({
  imageId,
  code,
  barcodeFormat,
  onClose,
}: {
  imageId: string
  code: string
  barcodeFormat: string | null
  onClose: () => void
}) {
  const hasBarcode = Boolean(barcodeFormat)
  const online = useOnline()
  const [rotated, setRotated] = useState(false)
  // A redrawn barcode beats a screenshot of a screen — but only if the scanner
  // agrees, so the original picture stays one tap away.
  const [showPhoto, setShowPhoto] = useState(!hasBarcode)

  useOverlay(onClose)

  return (
    <div className="scan">
      <ZoomableImage
        key={showPhoto ? 'photo' : 'barcode'}
        className={`scan-image ${rotated ? 'rotated' : ''}`}
        src={showPhoto ? imageUrl(imageId) : barcodeUrl(imageId, code, barcodeFormat ?? '')}
        alt={showPhoto ? t.scan.photoAlt : t.scan.barcodeAlt}
        rotated={rotated}
      />
      {code && <div className="scan-code">{code}</div>}
      <div className="scan-actions">
        {hasBarcode && (
          <button className="btn" onClick={() => setShowPhoto(!showPhoto)}>
            {showPhoto ? t.scan.code : t.scan.photo}
          </button>
        )}
        <button className="btn" onClick={() => setRotated(!rotated)}>
          {t.scan.rotate}
        </button>
        <button className="btn primary" onClick={onClose}>
          {t.scan.done}
        </button>
      </div>
      <p className="scan-hint">
        {showPhoto ? t.scan.hintPhoto : t.scan.hintBarcode}
      </p>
      {/* Offline, the card is the one last loaded, and so is its barcode — the two
          always match (the address is versioned by the code), but they may both be
          behind an edit made on another device since. Said, not hidden. */}
      {!online && !isDemo() && <p className="scan-hint scan-offline">{t.scan.offline}</p>}
    </div>
  )
}
