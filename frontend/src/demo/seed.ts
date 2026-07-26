import { demoImageId } from './assets'
import { t } from '../i18n'
import type { Comment, User, Voucher, VoucherEvent } from '../types'

export interface DemoComment extends Comment {
  voucher_id: number
}

export interface DemoEvent extends VoucherEvent {
  voucher_id: number
}

export interface DemoState {
  vouchers: Voucher[]
  comments: DemoComment[]
  events: DemoEvent[]
  nextId: number
}

export const YOU: User = {
  id: 1,
  telegram_id: 1,
  username: 'you',
  get display_name() {
    return t.demo.you
  },
}

export const PARTNER: User = {
  id: 2,
  telegram_id: 2,
  username: 'anna',
  get display_name() {
    return t.demo.partner
  },
}

const DAY = 86_400_000
/** Everything is relative to the visit, so "expires in 5 days" is always true. */
const at = (days: number) => new Date(Date.now() + days * DAY).toISOString()
const on = (days: number) => at(days).slice(0, 10)

export function blankVoucher(id: number, fields: Partial<Voucher> = {}): Voucher {
  return {
    id,
    status: 'active',
    merchant: '',
    title: '',
    code: '',
    value_kind: 'amount',
    value_amount: null,
    balance_amount: null,
    currency: 'EUR',
    valid_from: null,
    valid_until: null,
    conditions: '',
    notes: '',
    image_id: null,
    barcode_format: null,
    expiry_estimated: false,
    balance_uncertain: false,
    is_expired: false,
    days_left: null,
    created_by: YOU,
    used_by: null,
    created_at: at(-200),
    updated_at: at(-200),
    used_at: null,
    comments_count: 0,
    ...fields,
  }
}

/**
 * A family's cards a few months in: some spent down, one about to expire, one
 * nobody is sure about, a draft waiting to be filled in. Enough for every screen
 * to have something to show, including the statistics.
 */
export function createSeed(): DemoState {
  const vouchers: Voucher[] = [
    blankVoucher(1, {
      merchant: 'Rewe',
      value_amount: '50.00',
      balance_amount: '32.29',
      valid_until: on(1150),
      expiry_estimated: true,
      notes: t.demo.seed.reweNote,
      image_id: demoImageId('Rewe', '4012345678901'),
      code: '4012345678901',
      barcode_format: 'EAN_13',
      created_at: at(-190),
    }),
    blankVoucher(2, {
      merchant: 'Ikea',
      image_id: demoImageId('Ikea', '4029764001807'),
      code: '4029764001807',
      barcode_format: 'EAN_13',
      value_amount: '40.00',
      balance_amount: '25.00',
      valid_until: on(980),
      expiry_estimated: true,
      created_at: at(-170),
    }),
    blankVoucher(3, {
      merchant: 'Penny',
      image_id: demoImageId('Penny', '4306188339458'),
      code: '4306188339458',
      barcode_format: 'EAN_13',
      value_amount: '30.00',
      balance_amount: '4.27',
      valid_until: on(640),
      expiry_estimated: true,
      created_at: at(-120),
    }),
    blankVoucher(4, {
      merchant: 'Rossmann',
      image_id: demoImageId('Rossmann', '4305615591261'),
      code: '4305615591261',
      barcode_format: 'EAN_13',
      value_amount: '10.00',
      balance_amount: '8.10',
      valid_until: on(1080),
      expiry_estimated: true,
      created_at: at(-60),
    }),
    blankVoucher(5, {
      merchant: 'Jet',
      image_id: demoImageId('Jet', '4260112349001'),
      code: '4260112349001',
      barcode_format: 'EAN_13',
      value_amount: '50.00',
      balance_amount: '50.00',
      valid_until: on(900),
      balance_uncertain: true,
      comments_count: 1,
      created_at: at(-95),
    }),
    blankVoucher(6, {
      merchant: 'Kaufland',
      image_id: demoImageId('Kaufland', '4337256112390'),
      code: '4337256112390',
      barcode_format: 'EAN_13',
      value_amount: '20.00',
      balance_amount: '20.00',
      valid_until: on(5),
      comments_count: 1,
      created_at: at(-30),
    }),
    blankVoucher(7, {
      merchant: 'TotalEnergies',
      image_id: demoImageId('TotalEnergies', ''),
      value_amount: '50.00',
      balance_amount: '50.00',
      balance_uncertain: true,
      created_at: at(-45),
    }),
    blankVoucher(8, {
      status: 'draft',
      image_id: demoImageId('Aldi', '4260112340008'),
      created_at: at(-1),
      updated_at: at(-1),
    }),
    blankVoucher(9, {
      status: 'used',
      merchant: 'Lidl',
      image_id: demoImageId('Lidl', '4056489472018'),
      code: '4056489472018',
      barcode_format: 'EAN_13',
      value_amount: '25.00',
      balance_amount: '0.00',
      used_at: at(-75),
      used_by: PARTNER,
      created_by: PARTNER,
      comments_count: 1,
      created_at: at(-140),
    }),
    blankVoucher(10, {
      status: 'archived',
      merchant: 'Douglas',
      value_amount: '15.00',
      balance_amount: '15.00',
      conditions: t.demo.seed.douglasConditions,
      created_at: at(-220),
    }),
  ]

  const comments: DemoComment[] = [
    { id: 1, voucher_id: 5, text: t.demo.seed.jetComment, author: PARTNER, created_at: at(-20) },
    { id: 2, voucher_id: 6, text: t.demo.seed.kauflandComment, author: YOU, created_at: at(-6) },
    { id: 3, voucher_id: 7, text: t.demo.seed.totalComment, author: PARTNER, created_at: at(-40) },
    { id: 4, voucher_id: 9, text: t.demo.seed.lidlComment, author: PARTNER, created_at: at(-75) },
  ]

  const spends: [number, number, string, string, string, User][] = [
    // [voucher, days ago, spent, remaining, note, who]
    [2, -150, '15.00', '25.00', t.demo.seed.candles, PARTNER],
    [1, -110, '10.00', '40.00', t.demo.seed.groceries, YOU],
    [9, -75, '25.00', '0.00', t.demo.seed.weeklyShop, PARTNER],
    [3, -40, '25.73', '4.27', t.demo.seed.weeklyShop, PARTNER],
    [1, -12, '7.71', '32.29', t.demo.seed.groceries, YOU],
    [4, -3, '1.90', '8.10', t.demo.seed.shampoo, YOU],
  ]

  let eventId = 0
  const events: DemoEvent[] = []
  for (const voucher of vouchers) {
    events.push({
      id: ++eventId,
      voucher_id: voucher.id,
      kind: 'created',
      payload: {},
      actor: voucher.created_by,
      created_at: voucher.created_at,
    })
  }
  for (const [voucherId, days, spent, remaining, note, actor] of spends) {
    events.push({
      id: ++eventId,
      voucher_id: voucherId,
      kind: 'balance_updated',
      payload: { spent, remaining, note },
      actor,
      created_at: at(days),
    })
  }
  events.push({
    id: ++eventId,
    voucher_id: 9,
    kind: 'used',
    payload: { reason: 'balance_empty' },
    actor: PARTNER,
    created_at: at(-75),
  })

  return { vouchers, comments, events, nextId: 100 }
}
