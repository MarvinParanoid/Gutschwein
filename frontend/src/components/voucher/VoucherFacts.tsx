import { useState } from 'react'

import { expiryInfo, formatDate, isGiftCard, valueLabel } from '../../format'
import { t } from '../../i18n'
import { alertMessage, haptic } from '../../telegram'
import type { Voucher } from '../../types'

/** Everything the card says about itself. Empty fields are not rendered at all. */
export default function VoucherFacts({ voucher }: { voucher: Voucher }) {
  const expiry = expiryInfo(voucher)
  const giftCard = isGiftCard(voucher)

  return (
    <div className="panel">
      <div className="rows">
        {!giftCard && valueLabel(voucher) && (
          <Row label={t.card.discount}>
            <span className="value">{valueLabel(voucher)}</span>
          </Row>
        )}
        {/* No «Номинал» row for gift cards: the balance panel above already
            reads «32.65 EUR из 50 EUR». */}
        {voucher.title && voucher.merchant && <Row label={t.card.name}>{voucher.title}</Row>}

        {/* Most gift cards are added without a deadline; an empty row with a
            dash is just noise. */}
        {voucher.valid_until && (
          <Row
            label={
              <>
                {t.card.expires}
                {voucher.expiry_estimated && (
                  <span className="hint-note">{t.card.expiresByRule}</span>
                )}
              </>
            }
          >
            {voucher.expiry_estimated && '≈ '}
            {formatDate(voucher.valid_until)}
            {expiry && expiry.tone !== 'neutral' && (
              <>
                {' '}
                <span className={`badge ${expiry.tone}`}>{expiry.text}</span>
              </>
            )}
          </Row>
        )}

        {voucher.valid_from && (
          <Row label={t.card.validFrom}>{formatDate(voucher.valid_from)}</Row>
        )}
        {voucher.conditions && <Row label={t.card.conditions}>{voucher.conditions}</Row>}
        {voucher.notes && <Row label={t.card.note}>{voucher.notes}</Row>}

        <Row label={t.card.addedBy}>
          {voucher.created_by.display_name}, {formatDate(voucher.created_at)}
        </Row>
        {voucher.used_by && voucher.used_at && (
          <Row label={t.card.usedBy}>
            {voucher.used_by.display_name}, {formatDate(voucher.used_at)}
          </Row>
        )}
      </div>

      {voucher.code && <CodeBlock code={voucher.code} />}
    </div>
  )
}

function Row({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="row">
      <span className="label">{label}</span>
      <span className="val">{children}</span>
    </div>
  )
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      haptic('success')
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      alertMessage(t.card.copyFailed)
    }
  }

  return (
    <div className="code" style={{ marginTop: 12 }}>
      <span>{code}</span>
      <button className="btn link" onClick={copy}>
        {copied ? t.card.copied : t.card.copy}
      </button>
    </div>
  )
}
