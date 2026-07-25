export type VoucherStatus = 'draft' | 'active' | 'used' | 'archived'
export type ValueKind = 'amount' | 'percent' | 'other'

export interface User {
  id: number
  telegram_id: number
  username: string
  display_name: string
}

export interface Voucher {
  id: number
  status: VoucherStatus
  merchant: string
  title: string
  code: string
  value_kind: ValueKind
  /** Face value: the amount printed on the voucher, or the percentage. */
  value_amount: string | null
  /** What is left to spend on a gift card; null for percent/other vouchers. */
  balance_amount: string | null
  currency: string
  valid_from: string | null
  valid_until: string | null
  conditions: string
  notes: string
  image_id: string | null
  is_expired: boolean
  days_left: number | null
  created_by: User
  used_by: User | null
  created_at: string
  updated_at: string
  used_at: string | null
  comments_count: number
}

export interface VoucherDraft {
  merchant: string
  title: string
  code: string
  value_kind: ValueKind
  value_amount: string | null
  currency: string
  valid_from: string | null
  valid_until: string | null
  conditions: string
  notes: string
  image_id: string | null
  status?: VoucherStatus
}

export interface Counts {
  active: number
  draft: number
  used: number
  archived: number
  /** Money still left on archived gift cards. */
  archived_balance: string
  currency: string
}

export interface Comment {
  id: number
  text: string
  author: User
  created_at: string
}

export type EventKind =
  | 'created'
  | 'published'
  | 'updated'
  | 'balance_updated'
  | 'used'
  | 'unused'
  | 'archived'
  | 'restored'
  | 'commented'
  | 'image_replaced'

export interface VoucherEvent {
  id: number
  kind: EventKind
  payload: Record<string, unknown>
  actor: User | null
  created_at: string
}
