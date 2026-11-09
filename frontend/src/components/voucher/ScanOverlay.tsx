import { useEffect, useState } from 'react'

import { api, barcodeUrl, imageUrl, svgSource } from '../../api'
import { codeGroups } from '../../barcodeFormats'
import { copyText } from '../../clipboard'
import { isDemo } from '../../demo/session'
import { cardTitle, isGiftCard, primaryAmount } from '../../format'
import { t } from '../../i18n'
import { alertMessage, haptic } from '../../telegram'
import type { Voucher } from '../../types'
import { useOnline } from '../../useOnline'
import { useOverlay } from '../../useOverlay'
import ZoomableImage from '../ZoomableImage'

/** Where the bars come from, once known. */
type Bars = { state: 'none' } | { state: 'loading' } | { state: 'failed' } | { state: 'ready'; src: string }

/**
 * The redrawn barcode for a card, from whichever address it has.
 *
 * A card with a picture keeps its capability URL (`/api/barcodes/<image>?v=`): an
 * <img> loads it, and the worker caches it cache-first. A card typed in by hand has
 * no such name, so its bars are fetched with credentials and shown inline — the
 * same `?v=`, answered from the API cache when offline.
 */
function useBars(voucher: Voucher): Bars {
  const { id, image_id: imageId, code, barcode_version: version } = voucher
  const direct = Boolean(version && imageId)
  const [fetched, setFetched] = useState<Bars>({ state: 'loading' })

  useEffect(() => {
    if (!version || imageId) return
    let active = true
    setFetched({ state: 'loading' })
    api
      .cardBarcode(id, version)
      .then((drawn) => active && setFetched({ state: 'ready', src: svgSource(drawn.svg) }))
      .catch(() => active && setFetched({ state: 'failed' }))
    return () => {
      active = false
    }
  }, [id, imageId, version])

  if (!version) return { state: 'none' }
  if (direct) return { state: 'ready', src: barcodeUrl(imageId!, code, version) }
  return fetched
}

/**
 * Fullscreen view for the checkout counter: white background, the biggest possible
 * barcode, the number large enough to read out, and which card and how much is on
 * it — the three things asked at a till.
 */
export default function ScanOverlay({
  voucher,
  onClose,
}: {
  voucher: Voucher
  onClose: () => void
}) {
  const bars = useBars(voucher)
  const hasPhoto = Boolean(voucher.image_id)
  const online = useOnline()
  const [rotated, setRotated] = useState(false)
  // A redrawn barcode beats a screenshot of a screen — but only if the scanner
  // agrees, so the original picture stays one tap away. A drawing that failed
  // falls back to the picture by itself.
  const [preferPhoto, setPreferPhoto] = useState(false)
  const showPhoto = hasPhoto && (preferPhoto || bars.state === 'none' || bars.state === 'failed')
  const src = showPhoto ? imageUrl(voucher.image_id!) : bars.state === 'ready' ? bars.src : null

  useOverlay(onClose)

  const amount = primaryAmount(voucher)
  const hint = showPhoto
    ? t.scan.hintPhoto
    : bars.state === 'ready'
      ? hasPhoto
        ? t.scan.hintBarcode
        : t.scan.hintTyped
      : bars.state === 'failed'
        ? t.scan.drawFailed
        : bars.state === 'none'
          ? t.scan.noBarcode
          : null

  return (
    <div className="scan">
      <div className="scan-head">
        <div className="scan-merchant">{cardTitle(voucher)}</div>
        {amount && (
          <div className="scan-amount">
            {isGiftCard(voucher) && <span className="scan-amount-label">{t.scan.balance} </span>}
            <strong>{amount}</strong>
          </div>
        )}
      </div>

      {src ? (
        <>
          <ZoomableImage
            key={showPhoto ? 'photo' : 'barcode'}
            className={`scan-image ${rotated ? 'rotated' : ''}`}
            src={src}
            alt={showPhoto ? t.scan.photoAlt : t.scan.barcodeAlt}
            rotated={rotated}
          />
          {voucher.code && <CodeLine code={voucher.code} large={false} />}
        </>
      ) : (
        // No picture to show: the number takes the middle of the screen.
        <div className="scan-empty">
          {bars.state === 'loading' && <span>{t.scan.drawing}</span>}
          {voucher.code && <CodeLine code={voucher.code} large />}
        </div>
      )}

      <div className="scan-actions">
        {hasPhoto && bars.state === 'ready' && (
          <button className="btn" onClick={() => setPreferPhoto(!preferPhoto)}>
            {showPhoto ? t.scan.code : t.scan.photo}
          </button>
        )}
        {src && (
          <button className="btn" onClick={() => setRotated(!rotated)}>
            {t.scan.rotate}
          </button>
        )}
        <button className="btn primary" onClick={onClose}>
          {t.scan.done}
        </button>
      </div>
      {hint && <p className="scan-hint">{hint}</p>}
      {/* Offline, the card is the one last loaded, and so is its barcode — the two
          always match (the address is versioned by the code), but they may both be
          behind an edit made on another device since. Said, not hidden. */}
      {!online && !isDemo() && <p className="scan-hint scan-offline">{t.scan.offline}</p>}
    </div>
  )
}

function CodeLine({ code, large }: { code: string; large: boolean }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    if (await copyText(code)) {
      haptic('success')
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } else {
      alertMessage(t.card.copyFailed)
    }
  }

  return (
    <div className="scan-code-row">
      {/* Groups are separate elements, not spaces: selecting or copying the text by
          hand still gives the bare code. */}
      <div className={`scan-code ${large ? 'large' : ''}`}>
        {codeGroups(code).map((group, index) => (
          <span key={index}>{group}</span>
        ))}
      </div>
      <button className="btn scan-copy" onClick={copy}>
        {copied ? t.scan.copied : t.scan.copy}
      </button>
    </div>
  )
}
