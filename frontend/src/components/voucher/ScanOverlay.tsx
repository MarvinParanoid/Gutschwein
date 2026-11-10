import { useEffect, useRef, useState } from 'react'

import { api, barcodeUrl, imageUrl, svgSource } from '../../api'
import { codeGroups } from '../../barcodeFormats'
import { copyText } from '../../clipboard'
import { isDemo } from '../../demo/session'
import { cardTitle, codeUrl, isGiftCard, primaryAmount } from '../../format'
import { t } from '../../i18n'
import { alertMessage, haptic, openUrl } from '../../telegram'
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
  // A card with a picture is handed its bars as an address, which is what lets the
  // worker serve them offline — and means only the picture itself can report that
  // they are not there. The server refuses to draw a pair it cannot (a card from an
  // older version could keep the code of a replaced picture), and an <img> left to
  // itself shows that refusal as a broken picture at the till. One failed load is
  // enough: the card's own picture is what is left.
  const [drawFailed, setDrawFailed] = useState(false)
  const drawn = bars.state === 'ready' && !drawFailed
  const showPhoto = hasPhoto && (preferPhoto || !drawn)
  const src = showPhoto ? imageUrl(voucher.image_id!) : drawn ? bars.src : null

  useOverlay(onClose)
  const dialog = useRef<HTMLDivElement | null>(null)
  const done = useRef<HTMLButtonElement | null>(null)

  // Keyboard: the screen is a modal dialog. Focus moves in (to "Done", which Enter
  // or Escape then closes), Tab stays inside rather than wandering to the list
  // behind it, and closing hands focus back to the button that opened it.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    done.current?.focus()
    return () => opener?.focus()
  }, [])

  function keepFocusInside(event: React.KeyboardEvent) {
    if (event.key !== 'Tab' || !dialog.current) return
    const focusable = Array.from(
      dialog.current.querySelectorAll<HTMLElement>('button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'),
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const amount = primaryAmount(voucher)
  const hint = showPhoto
    ? t.scan.hintPhoto
    : drawn
      ? hasPhoto
        ? t.scan.hintBarcode
        : t.scan.hintTyped
      : bars.state === 'failed' || drawFailed
        ? t.scan.drawFailed
        : bars.state === 'none'
          ? t.scan.noBarcode
          : null

  return (
    <div
      className="scan"
      role="dialog"
      aria-modal="true"
      aria-label={cardTitle(voucher)}
      ref={dialog}
      onKeyDown={keepFocusInside}
    >
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
        <ZoomableImage
          key={showPhoto ? 'photo' : 'barcode'}
          className={`scan-image ${rotated ? 'rotated' : ''}`}
          src={src}
          alt={showPhoto ? t.scan.photoAlt : t.scan.barcodeAlt}
          rotated={rotated}
          snapModules={!showPhoto}
          // Only the drawing can be refused. A picture that will not load has
          // nothing left to fall back to, so its error is not listened for.
          onError={showPhoto ? undefined : () => setDrawFailed(true)}
        />
      ) : (
        <div className="scan-empty">{bars.state === 'loading' && t.scan.drawing}</div>
      )}
      {/* Always this element, in this place: when the bars finish loading the
          number must not be remounted, or a keyboard user's focus on "Copy" is
          dropped onto the page behind the dialog. */}
      {voucher.code && <CodeLine code={voucher.code} large={!src} />}
      {/* No picture: an equal space below, so the number sits mid-screen. */}
      {!src && <div className="scan-empty" aria-hidden="true" />}

      <div className="scan-actions">
        {/* Not while the drawing is missing: switching back to it would only show
            the same refusal again. */}
        {hasPhoto && drawn && (
          <button className="btn" onClick={() => setPreferPhoto(!preferPhoto)}>
            {showPhoto ? t.scan.code : t.scan.photo}
          </button>
        )}
        {src && (
          <button className="btn" onClick={() => setRotated(!rotated)}>
            {t.scan.rotate}
          </button>
        )}
        <button className="btn primary" ref={done} onClick={onClose}>
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
  // An address is opened, not read out to the cashier, so it is not grouped and
  // not grown to the size the number is — but it still copies.
  const href = codeUrl(code)

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
      {href ? (
        <a
          className="scan-code link"
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => {
            // Inside Telegram the client opens it; anywhere else the link itself
            // does, and this leaves the click alone.
            if (openUrl(href)) event.preventDefault()
          }}
        >
          {code}
        </a>
      ) : (
        /* Groups are separate elements, not spaces: selecting or copying the text
           by hand still gives the bare code. */
        <div className={`scan-code ${large ? 'large' : ''}`}>
          {codeGroups(code).map((group, index) => (
            <span key={index}>{group}</span>
          ))}
        </div>
      )}
      <button className="btn scan-copy" onClick={copy}>
        {copied ? t.scan.copied : t.scan.copy}
      </button>
    </div>
  )
}
