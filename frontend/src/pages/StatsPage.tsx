import { useEffect, useState } from 'react'

import { api } from '../api'
import { money, trimAmount } from '../format'
import { locale, t } from '../i18n'
import { inTelegram } from '../telegram'
import type { Stats } from '../types'

/**
 * Statistics screen.
 *
 * Every chart here is deliberately single-hue: the palette validator reports the
 * app's accent and the success green only ΔE 3.2 apart under deuteranopia, so hue
 * must never carry identity in this app. Magnitude is length, identity is the
 * label next to the bar — which also makes each chart its own table.
 */
export default function StatsPage({ onBack }: { onBack: () => void }) {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)

  useEffect(() => {
    api.stats().then(setStats).catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <div className="error">{error}</div>
  if (!stats) return <div className="spinner" />

  // One currency at a time, because that is how the money works: nothing here can
  // be added to a figure from another currency, so nothing here is. The first block
  // is the family's busiest currency, which for most families is the only one.
  const block = stats.currencies.find((c) => c.currency === picked) ?? stats.currencies[0]
  const { currency } = block
  const thisMonth = Number(block.spent_this_month)
  const prevMonth = Number(block.spent_prev_month)
  const atRisk =
    Number(block.expired_balance) +
    Number(block.expiring_soon) +
    Number(block.uncertain_balance)
  // A shop nothing was ever spent at says nothing about where money goes.
  const spentByMerchant = block.by_merchant.filter((m) => Number(m.spent) > 0)

  return (
    <>
      <div className="topbar">
        {!inTelegram && (
          <button className="back" onClick={onBack} aria-label={t.common.back}>
            ‹
          </button>
        )}
        <h1>{t.stats.title}</h1>
      </div>

      {stats.currencies.length > 1 && (
        <div className="segmented currencies">
          {stats.currencies.map((option) => (
            <button
              className={option.currency === currency ? 'active' : ''}
              key={option.currency}
              onClick={() => setPicked(option.currency)}
            >
              {option.currency}
            </button>
          ))}
        </div>
      )}

      <div className="panel">
        <div className="stat-hero">{money(block.on_cards, currency)}</div>
        <div className="stat-hero-caption">
          {t.stats.onCards} · {t.stats.activeCards(block.cards_active)}
        </div>
      </div>

      <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-value">{money(block.spent_this_month, currency)}</div>
          <div className="kpi-label">{t.stats.thisMonth}</div>
          {prevMonth > 0 && <MonthDelta current={thisMonth} previous={prevMonth} />}
        </div>
        <div className="kpi">
          <div className="kpi-value">{money(block.spent_total, currency)}</div>
          <div className="kpi-label">{t.stats.allTime}</div>
        </div>
      </div>

      {atRisk > 0 && (
        <div className="panel">
          <h2>{t.stats.atRisk}</h2>
          <div className="rows">
            {Number(block.expired_balance) > 0 && (
              <div className="row">
                <span className="label">{t.stats.expired}</span>
                <span className="val">{money(block.expired_balance, currency)}</span>
              </div>
            )}
            {Number(block.expiring_soon) > 0 && (
              <div className="row">
                <span className="label">{t.stats.expiringIn(stats.expiring_soon_days)}</span>
                <span className="val">{money(block.expiring_soon, currency)}</span>
              </div>
            )}
            {Number(block.uncertain_balance) > 0 && (
              <div className="row">
                <span className="label">{t.stats.uncertain}</span>
                <span className="val">{money(block.uncertain_balance, currency)}</span>
              </div>
            )}
            {Number(block.archived_balance) > 0 && (
              <div className="row">
                <span className="label">{t.stats.inArchive}</span>
                <span className="val">{money(block.archived_balance, currency)}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {spentByMerchant.length > 0 && (
        <div className="panel">
          <h2>{t.stats.whereItGoes}</h2>
          <BarList
            items={spentByMerchant.map((m) => ({
              label: m.merchant,
              value: Number(m.spent),
              text: money(m.spent, currency),
              note: Number(m.on_cards) > 0 ? t.stats.left(money(m.on_cards, currency)) : '',
            }))}
          />
        </div>
      )}

      {block.by_member.length > 0 && (
        <div className="panel">
          <h2>{t.stats.whoSpends}</h2>
          <BarList
            items={block.by_member.map((m) => ({
              label: m.name,
              value: Number(m.spent),
              text: money(m.spent, currency),
              note: t.stats.purchases(m.payments),
            }))}
          />
        </div>
      )}

      <div className="panel">
        <h2>{t.stats.byMonth}</h2>
        <MonthlyChart months={block.monthly} currency={currency} />
      </div>
    </>
  )
}

function MonthDelta({ current, previous }: { current: number; previous: number }) {
  const diff = current - previous
  if (Math.abs(diff) < 0.01)
    return <div className="kpi-delta">{t.stats.sameAsLastMonth}</div>
  // Arrow plus words, never colour alone: this app's accent and green are
  // indistinguishable to a deuteranope.
  return (
    <div className="kpi-delta">
      {t.stats.vsLastMonth(
        `${diff > 0 ? '▲' : '▼'} ${trimAmount(Math.abs(diff).toFixed(2))}`,
      )}
    </div>
  )
}

interface BarItem {
  label: string
  value: number
  text: string
  note?: string
}

/** Horizontal bars, one hue, every row directly labelled — a chart and a table at once. */
function BarList({ items }: { items: BarItem[] }) {
  const max = Math.max(...items.map((i) => i.value), 0)

  return (
    <div className="bars">
      {items.map((item) => (
        <div className="bar-row" key={item.label}>
          <div className="bar-head">
            <span className="bar-label">{item.label}</span>
            <span className="bar-value">{item.text}</span>
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              // Zero stays visibly zero rather than collapsing into the track.
              style={{ width: max > 0 ? `${Math.max(2, (item.value / max) * 100)}%` : '2%' }}
            />
          </div>
          {item.note && <div className="bar-note">{item.note}</div>}
        </div>
      ))}
    </div>
  )
}

function monthLabel(month: string): string {
  const [year, index] = month.split('-').map(Number)
  return new Date(year, index - 1, 1).toLocaleDateString(locale, { month: 'short' })
}

/**
 * Six months of spending. Only the tallest column is labelled by default;
 * tapping any column reveals its own value — the touch equivalent of hover.
 */
function MonthlyChart({
  months,
  currency,
}: {
  months: { month: string; spent: string }[]
  currency: string
}) {
  const [picked, setPicked] = useState<string | null>(null)
  const values = months.map((m) => Number(m.spent))
  const max = Math.max(...values, 0)

  if (max === 0) return <p className="muted">{t.stats.nothingSpent}</p>

  const peak = months[values.indexOf(max)]?.month
  const selected = months.find((m) => m.month === picked)

  return (
    <>
      <div className="columns">
        {months.map((m, index) => {
          const value = values[index]
          const isLabelled = m.month === peak || m.month === picked
          return (
            <button
              className={`column ${m.month === picked ? 'picked' : ''}`}
              key={m.month}
              onClick={() => setPicked(picked === m.month ? null : m.month)}
            >
              <span className="column-value">
                {isLabelled && value > 0 ? trimAmount(value.toFixed(2)) : ''}
              </span>
              {/* The plot area is its own box, so a full-height bar cannot push
                  the value and month labels out of the chart. */}
              <span className="column-plot">
                <span
                  className="column-fill"
                  // A zero month gets no bar at all — its labelled empty slot is
                  // what reads as zero. A 2% floor applies only to real amounts,
                  // so a tiny spend stays visible.
                  style={{ height: value > 0 ? `${Math.max(2, (value / max) * 100)}%` : '0' }}
                />
              </span>
              <span className="column-label">{monthLabel(m.month)}</span>
            </button>
          )
        })}
      </div>
      <p className="muted">
        {selected
          ? `${monthLabel(selected.month)}: ${money(selected.spent, currency)}`
          : t.stats.tapColumn}
      </p>
    </>
  )
}
