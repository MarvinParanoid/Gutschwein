import { useEffect, useState } from 'react'

import { api, imageUrl } from '../api'
import { trimAmount } from '../format'
import { alertMessage, haptic, inTelegram } from '../telegram'
import type { ValueKind, VoucherDraft } from '../types'

interface Props {
  voucherId?: number
  onCancel: () => void
  onSaved: (id: number) => void
}

const VALUE_KINDS: { key: ValueKind; label: string }[] = [
  { key: 'amount', label: 'На сумму' },
  { key: 'percent', label: 'Процент' },
  { key: 'other', label: 'Другое' },
]

const EMPTY: VoucherDraft = {
  merchant: '',
  title: '',
  code: '',
  // Gift cards with a balance are the common case, so start there.
  value_kind: 'amount',
  value_amount: '',
  currency: 'EUR',
  valid_from: null,
  valid_until: null,
  conditions: '',
  notes: '',
  image_id: null,
}

export default function VoucherForm({ voucherId, onCancel, onSaved }: Props) {
  const [draft, setDraft] = useState<VoucherDraft>(EMPTY)
  const [merchants, setMerchants] = useState<string[]>([])
  const [loading, setLoading] = useState(Boolean(voucherId))
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.merchants().then(setMerchants).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!voucherId) return
    api
      .getVoucher(voucherId)
      .then((voucher) =>
        setDraft({
          merchant: voucher.merchant,
          title: voucher.title,
          code: voucher.code,
          value_kind: voucher.value_kind,
          // The API returns Numeric(10, 2) as "20.00"; the input should read "20".
          value_amount: voucher.value_amount ? trimAmount(voucher.value_amount) : '',
          currency: voucher.currency,
          valid_from: voucher.valid_from,
          valid_until: voucher.valid_until,
          conditions: voucher.conditions,
          notes: voucher.notes,
          image_id: voucher.image_id,
        }),
      )
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [voucherId])

  function set<K extends keyof VoucherDraft>(key: K, value: VoucherDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }))
  }

  async function pickImage(file: File | undefined) {
    if (!file) return
    setUploading(true)
    try {
      set('image_id', await api.uploadImage(file))
      haptic()
    } catch (e) {
      alertMessage((e as Error).message)
    } finally {
      setUploading(false)
    }
  }

  async function save() {
    setSaving(true)
    setError(null)
    const payload: VoucherDraft = {
      ...draft,
      // The API expects a number or nothing; an empty input means "not set".
      value_amount: draft.value_amount?.toString().trim() || null,
      valid_from: draft.valid_from || null,
      valid_until: draft.valid_until || null,
    }
    try {
      const voucher = voucherId
        ? await api.updateVoucher(voucherId, payload)
        : await api.createVoucher({ ...payload, status: 'active' })
      haptic('success')
      onSaved(voucher.id)
    } catch (e) {
      setError((e as Error).message)
      haptic('error')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="spinner" />

  const showAmount = draft.value_kind !== 'other'

  return (
    <>
      <div className="topbar">
        {!inTelegram && (
          <button className="back" onClick={onCancel} aria-label="Назад">
            ‹
          </button>
        )}
        <h1>{voucherId ? 'Изменить купон' : 'Новый купон'}</h1>
      </div>

      {error && <div className="error">{error}</div>}

      <label className="photo-picker">
        {draft.image_id ? (
          <img src={imageUrl(draft.image_id)} alt="Фото купона" />
        ) : (
          <span>{uploading ? 'Загружаю…' : '📷 Добавить фото или скрин'}</span>
        )}
        <input
          type="file"
          accept="image/*"
          onChange={(e) => pickImage(e.target.files?.[0])}
        />
      </label>
      {draft.image_id && (
        <button className="btn link" onClick={() => set('image_id', null)}>
          убрать фото
        </button>
      )}

      <div className="panel">
        <div className="field">
          <label htmlFor="merchant">Магазин</label>
          <input
            id="merchant"
            list="merchants"
            value={draft.merchant}
            placeholder="DM, Rewe, Lidl…"
            onChange={(e) => set('merchant', e.target.value)}
          />
          <datalist id="merchants">
            {merchants.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </div>

        <div className="field">
          <label htmlFor="title">Название</label>
          <input
            id="title"
            value={draft.title}
            placeholder="20% на бытовую химию"
            onChange={(e) => set('title', e.target.value)}
          />
        </div>

        <div className="field">
          <label>Тип скидки</label>
          <div className="segmented">
            {VALUE_KINDS.map((kind) => (
              <button
                key={kind.key}
                className={draft.value_kind === kind.key ? 'active' : ''}
                onClick={() => set('value_kind', kind.key)}
              >
                {kind.label}
              </button>
            ))}
          </div>
        </div>

        {showAmount && (
          <div className="field-row">
            <div className="field">
              <label htmlFor="amount">
                {draft.value_kind === 'percent' ? 'Процент' : 'Номинал'}
              </label>
              <input
                id="amount"
                type="number"
                inputMode="decimal"
                step="0.01"
                min="0"
                value={draft.value_amount ?? ''}
                onChange={(e) => set('value_amount', e.target.value)}
              />
            </div>
            {draft.value_kind === 'amount' && (
              <div className="field">
                <label htmlFor="currency">Валюта</label>
                <input
                  id="currency"
                  value={draft.currency}
                  onChange={(e) => set('currency', e.target.value)}
                />
              </div>
            )}
          </div>
        )}

        <div className="field">
          <label htmlFor="code">Код</label>
          <input
            id="code"
            value={draft.code}
            placeholder="XK92-7741"
            onChange={(e) => set('code', e.target.value)}
          />
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="from">Действует с</label>
            <input
              id="from"
              type="date"
              value={draft.valid_from ?? ''}
              onChange={(e) => set('valid_from', e.target.value || null)}
            />
          </div>
          <div className="field">
            <label htmlFor="until">Действует до</label>
            <input
              id="until"
              type="date"
              value={draft.valid_until ?? ''}
              onChange={(e) => set('valid_until', e.target.value || null)}
            />
          </div>
        </div>

        <div className="field">
          <label htmlFor="conditions">Условия</label>
          <input
            id="conditions"
            value={draft.conditions}
            placeholder="от 30 EUR, кроме акционных товаров"
            onChange={(e) => set('conditions', e.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="notes">Заметка для семьи</label>
          <textarea
            id="notes"
            value={draft.notes}
            placeholder="Лежит в кошельке у Ани"
            onChange={(e) => set('notes', e.target.value)}
          />
        </div>
      </div>

      <div className="actions">
        <button className="btn primary" disabled={saving || uploading} onClick={save}>
          {saving ? 'Сохраняю…' : 'Сохранить'}
        </button>
        <button className="btn" onClick={onCancel}>
          Отмена
        </button>
      </div>
    </>
  )
}
