import { useEffect, useState } from 'react'

import { api, imageUrl } from '../api'
import { trimAmount } from '../format'
import { t } from '../i18n'
import { alertMessage, haptic, inTelegram } from '../telegram'
import type { ValueKind, VoucherDraft } from '../types'

interface Props {
  voucherId?: number
  onCancel: () => void
  onSaved: (id: number) => void
}

const VALUE_KINDS: { key: ValueKind; label: string }[] = [
  { key: 'amount', label: t.form.kindAmount },
  { key: 'percent', label: t.form.kindPercent },
  { key: 'other', label: t.form.kindOther },
]

/**
 * Suggestions for the currency field, not a permitted list: any three-letter code
 * is accepted. These are the ones a card bought around here is actually in — the
 * euro neighbours plus the currencies Bitrefill sells in. A suggestion is the only
 * defence against a plausible-looking wrong code, since PLZ is as well-formed as PLN.
 */
const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'PLN', 'CZK', 'SEK', 'DKK', 'NOK', 'RON', 'HUF']

// Placeholders rotate on every open: they show the format and make a form nobody
// wants to fill in slightly less of a chore.
const pick = (options: readonly string[]) =>
  options[Math.floor(Math.random() * options.length)]

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
  const [showExtra, setShowExtra] = useState(false)
  // Chosen once per mount, so the text does not shuffle while typing.
  const [hints] = useState(() => ({
    notes: pick(t.form.noteHints),
    conditions: pick(t.form.conditionHints),
  }))
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
      .then((voucher) => {
        // Never hide data that is already there.
        if (
          voucher.title ||
          voucher.code ||
          voucher.valid_from ||
          voucher.valid_until ||
          voucher.conditions
        ) {
          setShowExtra(true)
        }
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
        })
      })
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
          <button className="back" onClick={onCancel} aria-label={t.common.back}>
            ‹
          </button>
        )}
        <h1>{voucherId ? t.form.editTitle : t.form.newTitle}</h1>
      </div>

      {error && <div className="error">{error}</div>}

      <label className="photo-picker">
        {draft.image_id ? (
          <img src={imageUrl(draft.image_id)} alt="" />
        ) : (
          <span>{uploading ? t.form.uploading : t.form.addPhoto}</span>
        )}
        <input
          type="file"
          accept="image/*"
          onChange={(e) => pickImage(e.target.files?.[0])}
        />
      </label>
      {draft.image_id && (
        <button className="btn link" onClick={() => set('image_id', null)}>
          {t.form.removePhoto}
        </button>
      )}

      <div className="panel">
        <div className="field">
          <label htmlFor="merchant">{t.form.merchant}</label>
          <input
            id="merchant"
            list="merchants"
            value={draft.merchant}
            placeholder={t.form.merchantPlaceholder}
            onChange={(e) => set('merchant', e.target.value)}
          />
          <datalist id="merchants">
            {merchants.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </div>

        <div className="field">
          <label>{t.form.kind}</label>
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
                {draft.value_kind === 'percent' ? t.form.percent : t.form.faceValue}
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
              <div className="field narrow">
                <label htmlFor="currency">{t.form.currency}</label>
                <input
                  id="currency"
                  list="currencies"
                  maxLength={3}
                  autoCapitalize="characters"
                  spellCheck={false}
                  value={draft.currency}
                  // Statistics groups by this code, so a stray case would split a
                  // currency in two. The server insists on three letters; letting
                  // anything else be typed only to be rejected on save is unkind.
                  onChange={(e) =>
                    set('currency', e.target.value.replace(/[^a-zA-Z]/g, '').toUpperCase())
                  }
                />
                <datalist id="currencies">
                  {CURRENCIES.map((code) => (
                    <option key={code} value={code} />
                  ))}
                </datalist>
              </div>
            )}
          </div>
        )}

        <div className="field">
          <label htmlFor="notes">{t.form.note}</label>
          <textarea
            id="notes"
            value={draft.notes}
            placeholder={hints.notes}
            onChange={(e) => set('notes', e.target.value)}
          />
        </div>

        {/* Name, code, dates and conditions are the exception, not the rule: a
            gift card is identified by the shop and the photo. They stay in the
            model, just out of the way. */}
        <button className="btn link disclosure" onClick={() => setShowExtra(!showExtra)}>
          {showExtra ? t.form.less : t.form.more}
        </button>

        {showExtra && (
          <>
            <div className="field">
              <label htmlFor="title">{t.form.name}</label>
              <input
                id="title"
                value={draft.title}
                placeholder={t.form.namePlaceholder}
                onChange={(e) => set('title', e.target.value)}
              />
            </div>

            <div className="field">
              <label htmlFor="code">{t.form.code}</label>
              <input
                id="code"
                value={draft.code}
                placeholder={t.form.codePlaceholder}
                onChange={(e) => set('code', e.target.value)}
              />
            </div>

            <div className="field-row">
              <div className="field">
                <label htmlFor="from">{t.form.validFrom}</label>
                <input
                  id="from"
                  type="date"
                  value={draft.valid_from ?? ''}
                  onChange={(e) => set('valid_from', e.target.value || null)}
                />
              </div>
              <div className="field">
                <label htmlFor="until">{t.form.validUntil}</label>
                <input
                  id="until"
                  type="date"
                  value={draft.valid_until ?? ''}
                  onChange={(e) => set('valid_until', e.target.value || null)}
                />
              </div>
            </div>

            <div className="field">
              <label htmlFor="conditions">{t.form.conditions}</label>
              <input
                id="conditions"
                value={draft.conditions}
                placeholder={hints.conditions}
                onChange={(e) => set('conditions', e.target.value)}
              />
            </div>
          </>
        )}
      </div>

      <div className="actions">
        <button className="btn primary" disabled={saving || uploading} onClick={save}>
          {saving ? t.form.saving : t.form.save}
        </button>
        <button className="btn" onClick={onCancel}>
          {t.form.cancel}
        </button>
      </div>
    </>
  )
}
