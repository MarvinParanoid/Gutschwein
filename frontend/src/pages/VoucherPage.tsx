import { useCallback, useEffect, useState } from 'react'

import { api, imageUrl } from '../api'
import BalancePanel from '../components/voucher/BalancePanel'
import CommentsPanel from '../components/voucher/CommentsPanel'
import HistoryPanel from '../components/voucher/HistoryPanel'
import ScanOverlay from '../components/voucher/ScanOverlay'
import VoucherActions, { type Transition } from '../components/voucher/VoucherActions'
import VoucherFacts from '../components/voucher/VoucherFacts'
import { cardTitle, isGiftCard, statusLabel } from '../format'
import { t } from '../i18n'
import { alertMessage, confirmAction, haptic, inTelegram } from '../telegram'
import type { Comment, User, Voucher, VoucherEvent } from '../types'

interface Props {
  voucherId: number
  me: User
  onBack: () => void
  onDeleted: () => void
  onEdit: () => void
}

/** Loads one card and arranges the panels; each panel owns its own behaviour. */
export default function VoucherPage({ voucherId, me, onBack, onDeleted, onEdit }: Props) {
  const [voucher, setVoucher] = useState<Voucher | null>(null)
  const [comments, setComments] = useState<Comment[]>([])
  const [events, setEvents] = useState<VoucherEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [scanning, setScanning] = useState(false)

  const reloadHistory = useCallback(() => {
    api.comments(voucherId).then(setComments).catch(() => undefined)
    api.events(voucherId).then(setEvents).catch(() => undefined)
  }, [voucherId])

  useEffect(() => {
    api.getVoucher(voucherId).then(setVoucher).catch((e: Error) => setError(e.message))
    reloadHistory()
  }, [voucherId, reloadHistory])

  async function transition(action: Transition) {
    setBusy(true)
    haptic(action === 'use' ? 'success' : 'tap')
    try {
      setVoucher(await api.transition(voucherId, action))
      setEvents(await api.events(voucherId))
    } catch (e) {
      alertMessage((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!(await confirmAction(t.card.deleteConfirm))) return
    try {
      await api.deleteVoucher(voucherId)
      haptic('success')
      onDeleted()
    } catch (e) {
      alertMessage((e as Error).message)
    }
  }

  if (error) return <div className="error">{error}</div>
  if (!voucher) return <div className="spinner" />

  return (
    <>
      {scanning && voucher.image_id && (
        <ScanOverlay
          imageId={voucher.image_id}
          code={voucher.code}
          hasBarcode={Boolean(voucher.barcode_format)}
          onClose={() => setScanning(false)}
        />
      )}

      <div className="topbar">
        {/* Telegram draws its own back button in the header; outside it we need one. */}
        {!inTelegram && (
          <button className="back" onClick={onBack} aria-label={t.common.back}>
            ‹
          </button>
        )}
        <h1>{cardTitle(voucher)}</h1>
        <span className="badge">{statusLabel(voucher.status)}</span>
      </div>

      {voucher.image_id && (
        <button className="hero-button" onClick={() => setScanning(true)}>
          <img className="hero" src={imageUrl(voucher.image_id)} alt="" />
          <span className="hero-hint">{t.card.scanHint}</span>
        </button>
      )}

      {isGiftCard(voucher) && (
        <BalancePanel
          voucher={voucher}
          onUpdated={(updated) => {
            setVoucher(updated)
            reloadHistory()
          }}
        />
      )}

      <VoucherFacts voucher={voucher} />

      <VoucherActions
        voucher={voucher}
        busy={busy}
        onTransition={transition}
        onEdit={onEdit}
        onDelete={remove}
      />

      <CommentsPanel
        voucherId={voucherId}
        me={me}
        comments={comments}
        onChanged={reloadHistory}
      />

      <HistoryPanel events={events} />
    </>
  )
}
