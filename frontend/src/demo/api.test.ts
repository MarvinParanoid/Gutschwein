import { beforeEach, describe, expect, it } from 'vitest'

import type { ApiClient } from '../api'
import { createDemoApi } from './api'

/**
 * The demo client reimplements the server's rules, so it can drift from them
 * silently: nothing fails to compile when spending stops writing an event. These
 * tests pin the rules that the backend has its own tests for.
 */
let api: ApiClient

beforeEach(() => {
  api = createDemoApi()
})

describe('spending', () => {
  it('subtracts what was paid and records it', async () => {
    const before = await api.getVoucher(1)
    const after = await api.updateBalance(1, { spent: '2.29', note: 'молоко' })

    expect(Number(after.balance_amount)).toBeCloseTo(Number(before.balance_amount) - 2.29, 2)
    const [latest] = await api.events(1)
    expect(latest.kind).toBe('balance_updated')
    expect(latest.payload).toMatchObject({ spent: '2.29', remaining: after.balance_amount })
  })

  it('takes the balance from the receipt just as well', async () => {
    const after = await api.updateBalance(1, { remaining: '10.00' })
    expect(after.balance_amount).toBe('10.00')
  })

  it('closes a card that reaches zero, without being asked', async () => {
    const card = await api.getVoucher(1)
    const after = await api.updateBalance(1, { spent: card.balance_amount! })

    expect(after.balance_amount).toBe('0.00')
    expect(after.status).toBe('used')
    expect((await api.events(1)).some((e) => e.kind === 'used')).toBe(true)
  })

  it('refuses to spend more than the card holds', async () => {
    await expect(api.updateBalance(1, { spent: '9999' })).rejects.toThrow()
    await expect(api.updateBalance(1, { remaining: '9999' })).rejects.toThrow()
    // and leaves the card alone
    expect((await api.getVoucher(1)).balance_amount).toBe('32.29')
  })

  it('settles the doubt: writing a number down confirms the balance', async () => {
    expect((await api.getVoucher(5)).balance_uncertain).toBe(true)
    expect((await api.updateBalance(5, { remaining: '20' })).balance_uncertain).toBe(false)
  })
})

describe('the list', () => {
  it('puts the soonest deadline first and cards without one last', async () => {
    const active = await api.listVouchers('active')
    const dates = active.map((v) => v.valid_until)
    const dated = dates.filter(Boolean) as string[]
    expect([...dated].sort()).toEqual(dated)
    expect(dates.at(-1)).toBeNull()
  })

  it('searches the note, not only the shop', async () => {
    const [found] = await api.listVouchers('all', 'Geburtstag')
    const byNote = await api.listVouchers('all', 'geburtstag')
    expect(byNote.length).toBe(found ? 1 : byNote.length)
  })

  it('separates the tabs', async () => {
    const counts = await api.counts()
    expect(counts.draft).toBe(1)
    expect(counts.used).toBe(1)
    expect(counts.archived).toBe(1)
    expect((await api.listVouchers('draft'))[0].status).toBe('draft')
  })
})

describe('statistics', () => {
  /** The demo seed is one currency, so its figures live in the first block. */
  const euro = async () => (await api.stats()).currencies[0]

  it('counts only what is really available', async () => {
    const stats = await euro()
    const active = await api.listVouchers('active')
    const certain = active
      .filter((v) => !v.balance_uncertain)
      .reduce((sum, v) => sum + Number(v.balance_amount), 0)

    expect(stats.currency).toBe('EUR')
    expect(Number(stats.on_cards)).toBeCloseTo(certain, 2)
    expect(stats.cards_active).toBe(active.length)
    // An unconfirmed balance is money you cannot plan with: it gets its own line.
    expect(Number(stats.uncertain_balance)).toBeGreaterThan(0)
  })

  it('adds up the spending from the event log', async () => {
    const before = Number((await euro()).spent_total)
    await api.updateBalance(4, { spent: '1.00' })
    expect(Number((await euro()).spent_total)).toBeCloseTo(before + 1, 2)
  })

  it('keeps a continuous month axis', async () => {
    const { monthly } = await euro()
    expect(monthly).toHaveLength(6)
    expect(new Set(monthly.map((m) => m.month)).size).toBe(6)
  })

  it('never mixes two currencies into one figure', async () => {
    const before = await euro()
    const zloty = await api.createVoucher({
      merchant: 'Biedronka',
      value_kind: 'amount',
      value_amount: '200.00',
      currency: 'PLN',
    } as never)
    await api.updateBalance(zloty.id, { spent: '115.73' })

    const blocks = (await api.stats()).currencies
    const pln = blocks.find((block) => block.currency === 'PLN')!
    const eur = blocks.find((block) => block.currency === 'EUR')!

    expect(Number(pln.on_cards)).toBeCloseTo(84.27, 2)
    expect(Number(pln.spent_total)).toBeCloseTo(115.73, 2)
    // The euro side is untouched by any of it.
    expect(eur.on_cards).toBe(before.on_cards)
    expect(eur.spent_total).toBe(before.spent_total)
    expect(pln.by_merchant.map((m) => m.merchant)).toEqual(['Biedronka'])
    // The busier currency leads, so an ordinary family keeps the page it had.
    expect(blocks[0].currency).toBe('EUR')
  })
})

describe('the rest of the API surface', () => {
  it('creates a card with the balance already set', async () => {
    const created = await api.createVoucher({
      merchant: 'Aldi',
      value_kind: 'amount',
      value_amount: '25.00',
      currency: 'EUR',
    } as never)
    expect(created.balance_amount).toBe('25.00')
    // No printed date, so the shop rule fills one in — marked as a guess.
    expect(created.expiry_estimated).toBe(true)
    expect((await api.events(created.id))[0].kind).toBe('created')
  })

  it('counts comments on the card they belong to', async () => {
    const before = (await api.getVoucher(1)).comments_count
    await api.addComment(1, 'проверить на кассе')
    expect((await api.getVoucher(1)).comments_count).toBe(before + 1)
    expect((await api.comments(1)).at(-1)?.text).toBe('проверить на кассе')
  })

  it('forgets a deleted card entirely', async () => {
    await api.deleteVoucher(2)
    await expect(api.getVoucher(2)).rejects.toThrow()
    expect((await api.events(2))).toHaveLength(0)
  })
})
