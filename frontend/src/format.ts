import { locale, t } from './i18n'
import type { EventKind, Voucher, VoucherStatus } from './types'

export const STATUS_TABS: { key: VoucherStatus; label: string }[] = [
  { key: 'active', label: t.tabs.active },
  { key: 'draft', label: t.tabs.draft },
  { key: 'used', label: t.tabs.used },
  { key: 'archived', label: t.tabs.archived },
]

export const statusLabel = (status: VoucherStatus) => t.status[status]

/** Trims trailing zeros so 20.00 reads as 20. */
export function trimAmount(amount: string): string {
  return amount.includes('.') ? amount.replace(/\.?0+$/, '') : amount
}

export function valueLabel(voucher: Voucher): string {
  if (voucher.value_amount !== null) {
    const amount = trimAmount(voucher.value_amount)
    if (voucher.value_kind === 'amount') return `${amount} ${voucher.currency}`
    if (voucher.value_kind === 'percent') return `−${amount}%`
  }
  return ''
}

export const isGiftCard = (voucher: Voucher) =>
  voucher.value_kind === 'amount' && voucher.balance_amount !== null

export function money(amount: string, currency: string): string {
  return `${trimAmount(amount)} ${currency}`
}

/** Headline figure for a card: what is left, falling back to the face value. */
export function primaryAmount(voucher: Voucher): string {
  if (isGiftCard(voucher)) return money(voucher.balance_amount!, voucher.currency)
  return valueLabel(voucher)
}

/** Share of the gift card still unspent, for the progress bar. */
export function balanceRatio(voucher: Voucher): number | null {
  if (!isGiftCard(voucher) || !voucher.value_amount) return null
  const face = Number(voucher.value_amount)
  if (!face) return null
  return Math.max(0, Math.min(1, Number(voucher.balance_amount) / face))
}

export const isPartlySpent = (voucher: Voucher) =>
  isGiftCard(voucher) &&
  voucher.value_amount !== null &&
  Number(voucher.balance_amount) !== Number(voucher.value_amount)

export function cardTitle(voucher: Voucher): string {
  return voucher.merchant || voucher.title || t.list.cardFallback(voucher.id)
}

export function cardSubtitle(voucher: Voucher): string {
  const parts = [voucher.merchant ? voucher.title : '', voucher.conditions].filter(Boolean)
  return parts.join(' · ')
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  // Numeric: "25.07.2029" fits a badge, where "25 июл. 2029 г." wraps and the
  // trailing "г." carries nothing.
  return new Date(iso).toLocaleDateString(locale, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(locale, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export interface ExpiryInfo {
  text: string
  tone: 'soon' | 'expired' | 'neutral'
}

export function expiryInfo(voucher: Voucher): ExpiryInfo | null {
  if (voucher.valid_until === null) return null
  // A derived date is a guess; "≈" keeps it from reading as printed fact.
  const prefix = voucher.expiry_estimated ? '≈ ' : ''
  const days = voucher.days_left ?? 0
  if (days < 0) return { text: `${prefix}${t.expiry.expired}`, tone: 'expired' }
  if (days === 0) return { text: `${prefix}${t.expiry.lastDay}`, tone: 'soon' }
  if (days <= 7) return { text: `${prefix}${t.expiry.days(days)}`, tone: 'soon' }
  return { text: `${prefix}${t.expiry.until(formatDate(voucher.valid_until))}`, tone: 'neutral' }
}

export function eventText(kind: EventKind, payload: Record<string, unknown>): string {
  const base = t.events[kind] ?? kind
  if (kind === 'updated' && Array.isArray(payload.fields)) {
    const labels = t.fields as Record<string, string>
    const fields = (payload.fields as string[]).map((f) => labels[f] ?? f)
    return `${base}: ${fields.join(', ')}`
  }
  if (kind === 'balance_updated') {
    const spent = trimAmount(String(payload.spent ?? '0'))
    const remaining = trimAmount(String(payload.remaining ?? '0'))
    const note = payload.note ? ` — ${payload.note}` : ''
    return Number(spent) > 0
      ? t.events.spentLeft(spent, remaining, note)
      : t.events.corrected(remaining, note)
  }
  return base
}
