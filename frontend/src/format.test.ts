import { describe, expect, it } from 'vitest'

import {
  balanceRatio,
  expiryInfo,
  isPartlySpent,
  money,
  primaryAmount,
  trimAmount,
} from './format'
import type { Voucher } from './types'

const card = (fields: Partial<Voucher>): Voucher =>
  ({
    id: 1,
    status: 'active',
    merchant: 'Rewe',
    title: '',
    code: '',
    value_kind: 'amount',
    value_amount: null,
    balance_amount: null,
    currency: 'EUR',
    valid_until: null,
    expiry_estimated: false,
    days_left: null,
    is_expired: false,
    comments_count: 0,
    ...fields,
  }) as Voucher

describe('trimAmount', () => {
  it('drops the cents when there are none', () => {
    expect(trimAmount('20.00')).toBe('20')
    expect(trimAmount('21.40')).toBe('21.4')
    expect(trimAmount('0.05')).toBe('0.05')
  })

  it('leaves whole numbers alone', () => {
    // The trap: a naive trailing-zero strip turns 100 into 1.
    expect(trimAmount('100')).toBe('100')
    expect(trimAmount('1000')).toBe('1000')
    expect(trimAmount('100.00')).toBe('100')
  })
})

describe('the headline figure on a card', () => {
  it('is what is left, not the face value', () => {
    const voucher = card({ value_amount: '50.00', balance_amount: '32.29' })
    expect(primaryAmount(voucher)).toBe('32.29 EUR')
    expect(isPartlySpent(voucher)).toBe(true)
  })

  it('says nothing about the face value while the card is untouched', () => {
    expect(isPartlySpent(card({ value_amount: '50.00', balance_amount: '50.00' }))).toBe(false)
  })

  it('falls back to the percentage for a discount voucher', () => {
    expect(primaryAmount(card({ value_kind: 'percent', value_amount: '20' }))).toBe('−20%')
  })

  it('formats money without stray zeros', () => {
    expect(money('8.10', 'EUR')).toBe('8.1 EUR')
  })
})

describe('balanceRatio', () => {
  it('is the share still unspent', () => {
    expect(balanceRatio(card({ value_amount: '50', balance_amount: '25' }))).toBe(0.5)
  })

  it('never leaves 0..1, even if the balance was corrected upwards', () => {
    expect(balanceRatio(card({ value_amount: '50', balance_amount: '80' }))).toBe(1)
    expect(balanceRatio(card({ value_amount: '50', balance_amount: '-5' }))).toBe(0)
  })

  it('has no answer for a card with no face value', () => {
    expect(balanceRatio(card({ value_amount: null, balance_amount: '10' }))).toBeNull()
  })
})

describe('expiryInfo', () => {
  it('says nothing when the card has no date', () => {
    expect(expiryInfo(card({}))).toBeNull()
  })

  it('warns within a week and alarms once expired', () => {
    expect(expiryInfo(card({ valid_until: '2030-01-01', days_left: 3 }))?.tone).toBe('soon')
    expect(expiryInfo(card({ valid_until: '2020-01-01', days_left: -2 }))?.tone).toBe('expired')
    expect(expiryInfo(card({ valid_until: '2030-01-01', days_left: 300 }))?.tone).toBe('neutral')
  })

  it('marks a guessed date so it never reads as printed', () => {
    const guessed = expiryInfo(card({ valid_until: '2030-01-01', days_left: 300, expiry_estimated: true }))
    expect(guessed?.text.startsWith('≈')).toBe(true)
  })
})
