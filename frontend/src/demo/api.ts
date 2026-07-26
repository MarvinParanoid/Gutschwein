/**
 * The API client used in demo mode: the same surface as the HTTP one, answered
 * from an object in this tab.
 *
 * It reimplements the server's rules rather than faking screens — spending
 * writes a balance event, emptying a card marks it used, statistics are summed
 * from the event log — so what a visitor tries out is what the real thing does.
 * Nothing here touches the network.
 */

import type { ApiClient } from '../api'
import { trimAmount } from '../format'
import { t } from '../i18n'
import type {
  Comment,
  EventKind,
  Stats,
  User,
  Voucher,
  VoucherDraft,
  VoucherStatus,
} from '../types'
import { blankVoucher, createSeed, PARTNER, YOU, type DemoState } from './seed'

const MONTHS_BACK = 6
const TOP_MERCHANTS = 8
const EXPIRING_SOON_DAYS = 30
/** What most German retailers do; enough of the rule to demonstrate the "≈". */
const DEFAULT_EXPIRY_YEARS = 3

const state: DemoState = createSeed()

const cents = (amount: string | null | undefined) => Math.round(Number(amount ?? 0) * 100)
const money = (value: number) => (value / 100).toFixed(2)
const now = () => new Date().toISOString()
const today = () => new Date(new Date().toISOString().slice(0, 10))

function fail(message: string): never {
  throw new Error(message)
}

/** days_left and is_expired are derived on the server; here too, on every read. */
function derive(voucher: Voucher): Voucher {
  if (!voucher.valid_until) return { ...voucher, days_left: null, is_expired: false }
  const left = Math.round((Date.parse(voucher.valid_until) - today().getTime()) / 86_400_000)
  return { ...voucher, days_left: left, is_expired: left < 0 }
}

function find(id: number): Voucher {
  const voucher = state.vouchers.find((v) => v.id === id)
  if (!voucher) fail(t.app.genericError(404))
  return voucher
}

function record(
  voucher: Voucher,
  kind: EventKind,
  payload: Record<string, unknown> = {},
  actor: User | null = YOU,
): void {
  state.events.push({
    id: state.events.length + 1,
    voucher_id: voucher.id,
    kind,
    payload,
    actor,
    created_at: now(),
  })
  voucher.updated_at = now()
}

function markUsed(voucher: Voucher): void {
  voucher.status = 'used'
  voucher.used_at = now()
  voucher.used_by = YOU
}

function matches(voucher: Voucher, query: string): boolean {
  const needle = query.trim().toLowerCase()
  return [voucher.merchant, voucher.title, voucher.code, voucher.conditions, voucher.notes]
    .join('\n')
    .toLowerCase()
    .includes(needle)
}

const monthKey = (iso: string) => iso.slice(0, 7)

function shiftMonth(offset: number): string {
  const date = today()
  date.setUTCDate(1)
  date.setUTCMonth(date.getUTCMonth() + offset)
  return date.toISOString().slice(0, 7)
}

export function createDemoApi(): ApiClient {
  return {
    login: async () => YOU,
    logout: async () => undefined,
    me: async () => ({ user: YOU, members: [YOU, PARTNER] }),

    listVouchers: async (status, q, merchant) => {
      let found = state.vouchers.filter((v) => status === 'all' || v.status === status)
      if (merchant) found = found.filter((v) => v.merchant === merchant)
      if (q?.trim()) found = found.filter((v) => matches(v, q))

      const byExpiry = status === 'active' || status === 'all'
      return [...found]
        .sort((a, b) => {
          if (byExpiry && a.valid_until !== b.valid_until) {
            // Soonest deadline first; a card without one sinks to the bottom.
            if (!a.valid_until) return 1
            if (!b.valid_until) return -1
            return a.valid_until < b.valid_until ? -1 : 1
          }
          const key = byExpiry ? 'created_at' : 'updated_at'
          return a[key] < b[key] ? 1 : -1
        })
        .map(derive)
    },

    getVoucher: async (id) => derive(find(id)),

    merchants: async () =>
      [...new Set(state.vouchers.map((v) => v.merchant).filter(Boolean))].sort(),

    counts: async () => {
      const of = (status: VoucherStatus) => state.vouchers.filter((v) => v.status === status)
      return {
        active: of('active').length,
        draft: of('draft').length,
        used: of('used').length,
        archived: of('archived').length,
        archived_balance: money(
          of('archived').reduce((sum, v) => sum + cents(v.balance_amount), 0),
        ),
        currency: 'EUR',
      }
    },

    merchantStats: async (status) => {
      const uses = new Map<string, number>()
      for (const event of state.events) {
        if (event.kind !== 'balance_updated') continue
        const shop = state.vouchers.find((v) => v.id === event.voucher_id)?.merchant
        if (shop) uses.set(shop, (uses.get(shop) ?? 0) + 1)
      }

      const shops = new Map<string, { count: number; balance: number }>()
      for (const voucher of state.vouchers) {
        if (!voucher.merchant) continue
        if (status !== 'all' && voucher.status !== status) continue
        const entry = shops.get(voucher.merchant) ?? { count: 0, balance: 0 }
        entry.count += 1
        entry.balance += cents(voucher.balance_amount)
        shops.set(voucher.merchant, entry)
      }

      return [...shops.entries()]
        .map(([merchant, { count, balance }]) => ({
          merchant,
          count,
          balance: money(balance),
          uses: uses.get(merchant) ?? 0,
        }))
        // Regulars float up; one-off shops sink to the end of the row.
        .sort(
          (a, b) =>
            b.uses - a.uses ||
            b.count - a.count ||
            a.merchant.toLowerCase().localeCompare(b.merchant.toLowerCase()),
        )
    },

    stats: async () => buildStats(),

    createVoucher: async (draft: VoucherDraft) => {
      const { status = 'active', ...fields } = draft
      const voucher = blankVoucher(state.nextId++, {
        ...fields,
        status,
        created_at: now(),
        updated_at: now(),
      })
      if (voucher.value_kind === 'amount') voucher.balance_amount = voucher.value_amount
      // Most cards print no date, only a shop rule. Three years is the common
      // one; the app says "≈" so the guess never reads as printed fact.
      if (!voucher.valid_until && voucher.merchant && voucher.value_kind === 'amount') {
        const guess = today()
        guess.setUTCFullYear(guess.getUTCFullYear() + DEFAULT_EXPIRY_YEARS)
        voucher.valid_until = guess.toISOString().slice(0, 10)
        voucher.expiry_estimated = true
      }
      state.vouchers.push(voucher)
      record(voucher, 'created')
      return derive(voucher)
    },

    updateVoucher: async (id, patch) => {
      const voucher = find(id)
      const changed: string[] = []
      const previousValue = voucher.value_amount

      for (const [field, value] of Object.entries(patch) as [keyof VoucherDraft, never][]) {
        if (field === 'status') continue
        if (voucher[field as keyof Voucher] !== value) {
          Object.assign(voucher, { [field]: value })
          changed.push(field)
        }
      }
      // Correcting the face value of an untouched card moves the balance with it.
      if (
        changed.includes('value_amount') &&
        voucher.value_kind === 'amount' &&
        cents(previousValue) === cents(voucher.balance_amount)
      ) {
        voucher.balance_amount = voucher.value_amount
      }
      if (changed.length) record(voucher, 'updated', { fields: changed })
      voucher.updated_at = now()
      return derive(voucher)
    },

    deleteVoucher: async (id) => {
      state.vouchers = state.vouchers.filter((v) => v.id !== id)
      state.comments = state.comments.filter((c) => c.voucher_id !== id)
      state.events = state.events.filter((e) => e.voucher_id !== id)
    },

    transition: async (id, action) => {
      const voucher = find(id)
      if (action === 'use') {
        if (voucher.status === 'used') fail('used')
        if (cents(voucher.balance_amount) > 0) {
          record(voucher, 'balance_updated', {
            spent: voucher.balance_amount,
            remaining: '0',
            note: '',
          })
          voucher.balance_amount = '0.00'
        }
        markUsed(voucher)
        record(voucher, 'used')
      } else if (action === 'unuse') {
        voucher.status = 'active'
        voucher.used_at = null
        voucher.used_by = null
        record(voucher, 'unused')
      } else if (action === 'archive') {
        voucher.status = 'archived'
        record(voucher, 'archived')
      } else if (action === 'restore') {
        voucher.status = 'active'
        record(voucher, 'restored')
      } else {
        voucher.status = 'active'
        record(voucher, 'published')
      }
      return derive(voucher)
    },

    updateBalance: async (id, body) => {
      const voucher = find(id)
      if (voucher.value_kind !== 'amount') fail(t.app.genericError(400))
      const current = cents(voucher.balance_amount ?? voucher.value_amount)
      const withCurrency = (value: number) => `${trimAmount(money(value))} ${voucher.currency}`

      let next: number
      if (body.spent !== undefined) {
        const spent = cents(body.spent)
        if (spent > current) {
          fail(t.demo.errors.spendTooMuch(trimAmount(money(spent)), withCurrency(current)))
        }
        next = current - spent
      } else {
        next = cents(body.remaining)
        const face = cents(voucher.value_amount)
        if (face > 0 && next > face) fail(t.demo.errors.aboveFace(withCurrency(face)))
      }

      const delta = current - next
      voucher.balance_amount = money(next)
      // You just read the number off a receipt, so the doubt is settled.
      voucher.balance_uncertain = false
      record(voucher, 'balance_updated', {
        spent: money(delta),
        remaining: money(next),
        note: body.note ?? '',
      })
      if (next === 0 && voucher.status !== 'used') {
        markUsed(voucher)
        record(voucher, 'used', { reason: 'balance_empty' })
      }
      return derive(voucher)
    },

    comments: async (id) =>
      state.comments
        .filter((c) => c.voucher_id === id)
        .map(({ voucher_id: _ignored, ...comment }) => comment satisfies Comment),

    addComment: async (id, text) => {
      const voucher = find(id)
      const comment = {
        id: state.comments.length + 1,
        voucher_id: id,
        text,
        author: YOU,
        created_at: now(),
      }
      state.comments.push(comment)
      voucher.comments_count += 1
      return comment
    },

    deleteComment: async (voucherId, commentId) => {
      state.comments = state.comments.filter((c) => c.id !== commentId)
      find(voucherId).comments_count = state.comments.filter(
        (c) => c.voucher_id === voucherId,
      ).length
    },

    events: async (id) =>
      state.events
        .filter((e) => e.voucher_id === id)
        // Newest first, with the id breaking ties: two events can share a second.
        .sort((a, b) =>
          a.created_at === b.created_at ? b.id - a.id : a.created_at < b.created_at ? 1 : -1,
        )
        .map(({ voucher_id: _ignored, ...event }) => event),

    // The photo never leaves the page either: it becomes a data URI that the
    // image URL helper hands straight back to the <img>.
    uploadImage: (file) =>
      new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result))
        reader.onerror = () => reject(new Error('read failed'))
        reader.readAsDataURL(file)
      }),
  }
}

function buildStats(): Stats {
  const soon = new Date(today().getTime() + EXPIRING_SOON_DAYS * 86_400_000)
    .toISOString()
    .slice(0, 10)
  const startOfToday = today().toISOString().slice(0, 10)

  let onCards = 0
  let cardsActive = 0
  let uncertain = 0
  let cardsUncertain = 0
  let expiring = 0
  let expired = 0
  const onCardsByShop = new Map<string, number>()

  for (const voucher of state.vouchers.filter((v) => v.status === 'active')) {
    const amount = cents(voucher.balance_amount)
    cardsActive += 1
    if (voucher.balance_uncertain) {
      // Money you are unsure about is not money you can plan with: it gets its
      // own line instead of joining the total.
      uncertain += amount
      cardsUncertain += 1
      continue
    }
    onCards += amount
    if (voucher.merchant) {
      onCardsByShop.set(voucher.merchant, (onCardsByShop.get(voucher.merchant) ?? 0) + amount)
    }
    if (voucher.valid_until && amount > 0) {
      if (voucher.valid_until < startOfToday) expired += amount
      else if (voucher.valid_until <= soon) expiring += amount
    }
  }

  let spentTotal = 0
  const byShop = new Map<string, number>()
  const byMember = new Map<string, { spent: number; payments: number }>()
  const byMonth = new Map<string, number>()

  for (const event of state.events) {
    if (event.kind !== 'balance_updated') continue
    const amount = cents(String(event.payload.spent ?? '0'))
    if (amount <= 0) continue
    spentTotal += amount

    const month = monthKey(event.created_at)
    byMonth.set(month, (byMonth.get(month) ?? 0) + amount)

    const shop = state.vouchers.find((v) => v.id === event.voucher_id)?.merchant
    if (shop) byShop.set(shop, (byShop.get(shop) ?? 0) + amount)

    const name = event.actor?.display_name ?? YOU.display_name
    const member = byMember.get(name) ?? { spent: 0, payments: 0 }
    member.spent += amount
    member.payments += 1
    byMember.set(name, member)
  }

  const shops = new Set([...byShop.keys(), ...onCardsByShop.keys()])
  return {
    currency: 'EUR',
    on_cards: money(onCards),
    cards_active: cardsActive,
    uncertain_balance: money(uncertain),
    cards_uncertain: cardsUncertain,
    expiring_soon: money(expiring),
    expiring_soon_days: EXPIRING_SOON_DAYS,
    expired_balance: money(expired),
    archived_balance: money(
      state.vouchers
        .filter((v) => v.status === 'archived')
        .reduce((sum, v) => sum + cents(v.balance_amount), 0),
    ),
    spent_total: money(spentTotal),
    spent_this_month: money(byMonth.get(shiftMonth(0)) ?? 0),
    spent_prev_month: money(byMonth.get(shiftMonth(-1)) ?? 0),
    by_merchant: [...shops]
      .map((merchant) => ({
        merchant,
        spent: money(byShop.get(merchant) ?? 0),
        on_cards: money(onCardsByShop.get(merchant) ?? 0),
      }))
      .sort(
        (a, b) =>
          Number(b.spent) - Number(a.spent) ||
          Number(b.on_cards) - Number(a.on_cards) ||
          a.merchant.localeCompare(b.merchant),
      )
      .slice(0, TOP_MERCHANTS),
    by_member: [...byMember.entries()]
      .map(([name, { spent, payments }]) => ({ name, spent: money(spent), payments }))
      .sort((a, b) => Number(b.spent) - Number(a.spent)),
    // A continuous axis: a month with no spending has to render as zero rather
    // than disappear.
    monthly: Array.from({ length: MONTHS_BACK }, (_, index) => {
      const month = shiftMonth(index - (MONTHS_BACK - 1))
      return { month, spent: money(byMonth.get(month) ?? 0) }
    }),
  }
}
