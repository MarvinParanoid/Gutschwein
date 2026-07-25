import { useCallback, useEffect, useState } from 'react'

import ZoomableImage from '../ZoomableImage'
import { api, barcodeUrl, imageUrl } from '../api'
import {
  balanceRatio,
  eventText,
  expiryInfo,
  formatDate,
  formatDateTime,
  isGiftCard,
  money,
  statusLabel,
  valueLabel,
} from '../format'
import { alertMessage, confirmAction, haptic, inTelegram } from '../telegram'
import type { Comment, User, Voucher, VoucherEvent } from '../types'

interface Props {
  voucherId: number
  me: User
  onBack: () => void
  onDeleted: () => void
  onEdit: () => void
}

type Action = 'use' | 'unuse' | 'archive' | 'restore' | 'activate'

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

  async function run(action: Action) {
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
    if (!(await confirmAction('Удалить купон вместе с фото и историей?'))) return
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

  const expiry = expiryInfo(voucher)
  const giftCard = isGiftCard(voucher)

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
          <button className="back" onClick={onBack} aria-label="Назад">
            ‹
          </button>
        )}
        <h1>{voucher.merchant || voucher.title || `Купон #${voucher.id}`}</h1>
        <span className="badge">{statusLabel(voucher.status)}</span>
      </div>

      {voucher.image_id && (
        <button className="hero-button" onClick={() => setScanning(true)}>
          <img className="hero" src={imageUrl(voucher.image_id)} alt="Купон" />
          <span className="hero-hint">📷 Нажмите, чтобы показать сканеру</span>
        </button>
      )}

      {giftCard && (
        <BalancePanel
          voucher={voucher}
          onUpdated={(updated) => {
            setVoucher(updated)
            reloadHistory()
          }}
        />
      )}

      <div className="panel">
        <div className="rows">
          {!giftCard && valueLabel(voucher) && (
            <div className="row">
              <span className="label">Скидка</span>
              <span className="val value">{valueLabel(voucher)}</span>
            </div>
          )}
          {/* No «Номинал» row for gift cards: the balance panel above already
              reads «32.65 EUR из 50 EUR». */}
          {voucher.title && voucher.merchant && (
            <div className="row">
              <span className="label">Название</span>
              <span className="val">{voucher.title}</span>
            </div>
          )}
          {/* Most gift cards are added without a deadline; an empty row with a
              dash is just noise. */}
          {voucher.valid_until && (
            <div className="row">
              <span className="label">Срок</span>
              <span className="val">
                {formatDate(voucher.valid_until)}
                {expiry && expiry.tone !== 'neutral' && (
                  <>
                    {' '}
                    <span className={`badge ${expiry.tone}`}>{expiry.text}</span>
                  </>
                )}
              </span>
            </div>
          )}
          {voucher.valid_from && (
            <div className="row">
              <span className="label">Действует с</span>
              <span className="val">{formatDate(voucher.valid_from)}</span>
            </div>
          )}
          {voucher.conditions && (
            <div className="row">
              <span className="label">Условия</span>
              <span className="val">{voucher.conditions}</span>
            </div>
          )}
          {voucher.notes && (
            <div className="row">
              <span className="label">Заметка</span>
              <span className="val">{voucher.notes}</span>
            </div>
          )}
          <div className="row">
            <span className="label">Добавил</span>
            <span className="val">
              {voucher.created_by.display_name}, {formatDate(voucher.created_at)}
            </span>
          </div>
          {voucher.used_by && voucher.used_at && (
            <div className="row">
              <span className="label">Использовал</span>
              <span className="val">
                {voucher.used_by.display_name}, {formatDate(voucher.used_at)}
              </span>
            </div>
          )}
        </div>

        {voucher.code && <CodeBlock code={voucher.code} />}
      </div>

      <div className="panel">
        <div className="actions">
          {voucher.status === 'draft' && (
            <button className="btn primary" disabled={busy} onClick={() => run('activate')}>
              В активные
            </button>
          )}
          {voucher.status === 'active' && (
            <button className="btn" disabled={busy} onClick={() => run('use')}>
              ✅ {giftCard ? 'Потратил полностью' : 'Использован'}
            </button>
          )}
          {voucher.status === 'used' && (
            <button className="btn" disabled={busy} onClick={() => run('unuse')}>
              Вернуть в активные
            </button>
          )}
          {voucher.status === 'archived' ? (
            <button className="btn" disabled={busy} onClick={() => run('restore')}>
              Достать из архива
            </button>
          ) : (
            <button className="btn" disabled={busy} onClick={() => run('archive')}>
              📦 В архив
            </button>
          )}
          <button className="btn" onClick={onEdit}>
            ✏️ Изменить
          </button>
          <button className="btn danger" onClick={remove}>
            Удалить
          </button>
        </div>
      </div>

      <CommentsPanel
        voucherId={voucherId}
        me={me}
        comments={comments}
        onChanged={reloadHistory}
      />

      <div className="panel">
        <h2>История</h2>
        <div className="history">
          {events.map((event) => (
            <div className="item" key={event.id}>
              <span className="when">{formatDateTime(event.created_at)}</span>
              <span>
                {event.actor?.display_name ?? 'Система'} {eventText(event.kind, event.payload)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

/**
 * Fullscreen view for the checkout counter: white background and the biggest
 * possible image, because that is what a barcode scanner needs off a screen.
 */
function ScanOverlay({
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

/** Remaining balance plus the two-tap way to change it after paying. */
function BalancePanel({
  voucher,
  onUpdated,
}: {
  voucher: Voucher
  onUpdated: (voucher: Voucher) => void
}) {
  const [open, setOpen] = useState(false)
  // The receipt prints what is left, and that is what gets typed in almost every
  // time — so "осталось" is the default rather than the amount just spent.
  const [mode, setMode] = useState<'spent' | 'remaining'>('remaining')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const ratio = balanceRatio(voucher)

  async function submit() {
    // Phone keyboards give a comma in most European locales.
    const value = amount.replace(',', '.').trim()
    if (!value) return
    setSaving(true)
    setError(null)
    try {
      const updated = await api.updateBalance(voucher.id, {
        [mode]: value,
        note: note.trim(),
      })
      haptic('success')
      onUpdated(updated)
      setOpen(false)
      setAmount('')
      setNote('')
    } catch (e) {
      setError((e as Error).message)
      haptic('error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="panel balance">
      <div className="balance-head">
        <div>
          <div className="balance-value">
            {money(voucher.balance_amount!, voucher.currency)}
          </div>
          <div className="muted">
            {voucher.value_amount
              ? `из ${money(voucher.value_amount, voucher.currency)}`
              : 'остаток'}
          </div>
        </div>
        {!open && (
          <button className="btn primary" onClick={() => setOpen(true)}>
            Обновить остаток
          </button>
        )}
      </div>

      {ratio !== null && (
        <div className="bar">
          <div className="fill" style={{ width: `${Math.round(ratio * 100)}%` }} />
        </div>
      )}

      {open && (
        <div className="balance-form">
          <div className="segmented">
            <button
              className={mode === 'remaining' ? 'active' : ''}
              onClick={() => setMode('remaining')}
            >
              Осталось
            </button>
            <button
              className={mode === 'spent' ? 'active' : ''}
              onClick={() => setMode('spent')}
            >
              Потратил
            </button>
          </div>

          {error && <div className="error">{error}</div>}

          <div className="field">
            <input
              type="text"
              inputMode="decimal"
              autoFocus
              placeholder={mode === 'spent' ? 'Сумма покупки' : 'Остаток с чека'}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
            />
          </div>
          <div className="field">
            <input
              type="text"
              placeholder="Заметка: что купили (необязательно)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>

          <div className="actions">
            <button
              className="btn primary"
              disabled={saving || !amount.trim()}
              onClick={submit}
            >
              {saving ? 'Сохраняю…' : 'Сохранить'}
            </button>
            <button className="btn" onClick={() => setOpen(false)}>
              Отмена
            </button>
          </div>
        </div>
      )}
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
      alertMessage('Не удалось скопировать — выделите код вручную.')
    }
  }

  return (
    <div className="code" style={{ marginTop: 12 }}>
      <span>{code}</span>
      <button className="btn link" onClick={copy}>
        {copied ? 'скопировано' : 'копировать'}
      </button>
    </div>
  )
}

function CommentsPanel({
  voucherId,
  me,
  comments,
  onChanged,
}: {
  voucherId: number
  me: User
  comments: Comment[]
  onChanged: () => void
}) {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)

  async function send() {
    const trimmed = text.trim()
    if (!trimmed || sending) return
    setSending(true)
    try {
      await api.addComment(voucherId, trimmed)
      setText('')
      haptic()
      onChanged()
    } catch (e) {
      alertMessage((e as Error).message)
    } finally {
      setSending(false)
    }
  }

  async function remove(commentId: number) {
    if (!(await confirmAction('Удалить комментарий?'))) return
    try {
      await api.deleteComment(voucherId, commentId)
      onChanged()
    } catch (e) {
      alertMessage((e as Error).message)
    }
  }

  return (
    <div className="panel">
      <h2>Комментарии</h2>
      {comments.length === 0 && <p className="muted">Пока никто ничего не написал.</p>}
      {comments.map((comment) => (
        <div className="comment" key={comment.id}>
          <div className="head">
            <span className="author">{comment.author.display_name}</span>
            <span>{formatDateTime(comment.created_at)}</span>
            {comment.author.id === me.id && (
              <button className="btn link" onClick={() => remove(comment.id)}>
                удалить
              </button>
            )}
          </div>
          <div>{comment.text}</div>
        </div>
      ))}

      <div className="comment-form">
        <input
          placeholder="Написать семье…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
        />
        <button className="btn primary" disabled={!text.trim() || sending} onClick={send}>
          →
        </button>
      </div>
    </div>
  )
}
