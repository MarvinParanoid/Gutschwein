import { useState } from 'react'

import { api } from '../../api'
import { balanceRatio, money } from '../../format'
import { t } from '../../i18n'
import { haptic } from '../../telegram'
import type { Voucher } from '../../types'

/** Remaining balance plus the two-tap way to change it after paying. */
export default function BalancePanel({
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

  async function toggleUncertain() {
    try {
      onUpdated(
        await api.updateVoucher(voucher.id, {
          balance_uncertain: !voucher.balance_uncertain,
        }),
      )
      haptic()
    } catch (e) {
      setError((e as Error).message)
    }
  }

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
              ? t.list.outOf(money(voucher.value_amount, voucher.currency))
              : t.balance.rest}
          </div>
          {voucher.balance_uncertain && (
            <div className="badge soon uncertain">{t.balance.uncertainBadge}</div>
          )}
        </div>
        {!open && (
          <button className="btn primary" onClick={() => setOpen(true)}>
            {t.balance.update}
          </button>
        )}
      </div>

      {ratio !== null && (
        <div className="bar">
          <div className="fill" style={{ width: `${Math.round(ratio * 100)}%` }} />
        </div>
      )}

      {!open && (
        <button className="btn link uncertain-toggle" onClick={toggleUncertain}>
          {voucher.balance_uncertain ? t.balance.markCertain : t.balance.markUncertain}
        </button>
      )}

      {open && (
        <div className="balance-form">
          <div className="segmented">
            <button
              className={mode === 'remaining' ? 'active' : ''}
              onClick={() => setMode('remaining')}
            >
              {t.balance.remaining}
            </button>
            <button
              className={mode === 'spent' ? 'active' : ''}
              onClick={() => setMode('spent')}
            >
              {t.balance.spent}
            </button>
          </div>

          {error && <div className="error">{error}</div>}

          <div className="field">
            <input
              type="text"
              inputMode="decimal"
              autoFocus
              placeholder={mode === 'spent' ? t.balance.amountSpent : t.balance.amountRemaining}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
            />
          </div>
          <div className="field">
            <input
              type="text"
              placeholder={t.balance.note}
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
              {saving ? t.balance.saving : t.balance.save}
            </button>
            <button className="btn" onClick={() => setOpen(false)}>
              {t.balance.cancel}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
