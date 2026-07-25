import type { EventKind, Voucher, VoucherStatus } from './types'

export const STATUS_TABS: { key: VoucherStatus; label: string }[] = [
  { key: 'active', label: 'Активные' },
  { key: 'draft', label: 'Черновики' },
  { key: 'used', label: 'Использованные' },
  { key: 'archived', label: 'Архив' },
]

const STATUS_LABELS: Record<VoucherStatus, string> = {
  draft: 'Черновик',
  active: 'Активный',
  used: 'Использован',
  archived: 'В архиве',
}

const EVENT_LABELS: Record<EventKind, string> = {
  created: 'создал купон',
  published: 'перевёл в активные',
  updated: 'изменил',
  balance_updated: 'обновил остаток',
  used: 'отметил использованным',
  unused: 'вернул в активные',
  archived: 'отправил в архив',
  restored: 'достал из архива',
  commented: 'оставил комментарий',
  image_replaced: 'заменил фото',
}

const FIELD_LABELS: Record<string, string> = {
  merchant: 'магазин',
  title: 'название',
  code: 'код',
  value_kind: 'тип скидки',
  value_amount: 'размер',
  currency: 'валюта',
  valid_from: 'начало',
  valid_until: 'срок',
  conditions: 'условия',
  notes: 'заметку',
}

export const statusLabel = (status: VoucherStatus) => STATUS_LABELS[status]

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
  return voucher.merchant || voucher.title || `Купон #${voucher.id}`
}

export function cardSubtitle(voucher: Voucher): string {
  const parts = [voucher.merchant ? voucher.title : '', voucher.conditions].filter(Boolean)
  return parts.join(' · ')
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
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
  const days = voucher.days_left ?? 0
  if (days < 0) return { text: 'истёк', tone: 'expired' }
  if (days === 0) return { text: 'сегодня последний день', tone: 'soon' }
  if (days <= 7) return { text: `${days} ${plural(days, 'день', 'дня', 'дней')}`, tone: 'soon' }
  return { text: `до ${formatDate(voucher.valid_until)}`, tone: 'neutral' }
}

export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few
  return many
}

export function eventText(kind: EventKind, payload: Record<string, unknown>): string {
  const base = EVENT_LABELS[kind] ?? kind
  if (kind === 'updated' && Array.isArray(payload.fields)) {
    const fields = (payload.fields as string[]).map((f) => FIELD_LABELS[f] ?? f)
    return `${base}: ${fields.join(', ')}`
  }
  if (kind === 'balance_updated') {
    const spent = trimAmount(String(payload.spent ?? '0'))
    const remaining = trimAmount(String(payload.remaining ?? '0'))
    const note = payload.note ? ` — ${payload.note}` : ''
    return Number(spent) > 0
      ? `списал ${spent}, осталось ${remaining}${note}`
      : `поправил остаток: ${remaining}${note}`
  }
  return base
}
