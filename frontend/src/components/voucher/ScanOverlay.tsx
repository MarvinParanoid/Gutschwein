import { useEffect, useState } from 'react'

import { barcodeUrl, imageUrl } from '../../api'
import ZoomableImage from '../ZoomableImage'

/**
 * Fullscreen view for the checkout counter: white background and the biggest
 * possible image, because that is what a barcode scanner needs off a screen.
 */
export default function ScanOverlay({
  imageId,
  code,
  hasBarcode,
  onClose,
}: {
  imageId: string
  code: string
  hasBarcode: boolean
  onClose: () => void
}) {
  const [rotated, setRotated] = useState(false)
  // A redrawn barcode beats a screenshot of a screen — but only if the scanner
  // agrees, so the original picture stays one tap away.
  const [showPhoto, setShowPhoto] = useState(!hasBarcode)

  // Keep the page underneath from scrolling while the overlay is up.
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  return (
    <div className="scan">
      <ZoomableImage
        key={showPhoto ? 'photo' : 'barcode'}
        className={`scan-image ${rotated ? 'rotated' : ''}`}
        src={showPhoto ? imageUrl(imageId) : barcodeUrl(imageId)}
        alt={showPhoto ? 'Купон для сканирования' : 'Штрихкод карты'}
        rotated={rotated}
      />
      {code && <div className="scan-code">{code}</div>}
      <div className="scan-actions">
        {hasBarcode && (
          <button className="btn" onClick={() => setShowPhoto(!showPhoto)}>
            {showPhoto ? '▮▮ Код' : '🖼 Фото'}
          </button>
        )}
        <button className="btn" onClick={() => setRotated(!rotated)}>
          ↻ Повернуть
        </button>
        <button className="btn primary" onClick={onClose}>
          Готово
        </button>
      </div>
      <p className="scan-hint">
        {showPhoto
          ? 'Щипок или двойной тап — увеличить. Выкрутите яркость: так сканер читает надёжнее'
          : 'Код перерисован из карты — чёткий на любом увеличении. Не читается? Переключитесь на фото'}
      </p>
    </div>
  )
}
