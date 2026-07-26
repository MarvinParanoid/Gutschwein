import { useEffect, useState } from 'react'

import { api } from '../api'
import MerchantMark from '../components/MerchantMark'
import {
  STATUS_TABS,
  cardSubtitle,
  cardTitle,
  expiryInfo,
  formatDate,
  isPartlySpent,
  money,
  primaryAmount,
} from '../format'
import { t } from '../i18n'
import { haptic, inTelegram } from '../telegram'
import { useOverlay } from '../useOverlay'
import type { Counts, MerchantStat, Voucher, VoucherStatus } from '../types'

interface Props {
  tab: VoucherStatus
  onTabChange: (tab: VoucherStatus) => void
  query: string
  onQueryChange: (query: string) => void
  merchant: string | null
  onMerchantChange: (merchant: string | null) => void
  onOpen: (id: number) => void
  onCreate: () => void
  onStats: () => void
}

const EMPTY_EMOJI: Record<VoucherStatus, string> = {
  active: '🐷',
  draft: '📸',
  used: '✅',
  archived: '📦',
}

export default function ListPage({
  tab,
  onTabChange,
  query,
  onQueryChange,
  merchant,
  onMerchantChange,
  onOpen,
  onCreate,
  onStats,
}: Props) {
  const [vouchers, setVouchers] = useState<Voucher[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [debouncedQuery, setDebouncedQuery] = useState(query)
  const [menuOpen, setMenuOpen] = useState(false)
  const [counts, setCounts] = useState<Counts | null>(null)
  const [shops, setShops] = useState<MerchantStat[]>([])

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 250)
    return () => clearTimeout(timer)
  }, [query])

  useEffect(() => {
    let active = true
    setError(null)
    api
      .listVouchers(tab, debouncedQuery, merchant)
      .then((data) => active && setVouchers(data))
      .catch((e: Error) => active && setError(e.message))
    return () => {
      active = false
    }
  }, [tab, debouncedQuery, merchant])

  // Chips describe the tab, not the current filter, so selecting one must not
  // refetch them. Coming back from a voucher remounts this page and refreshes.
  useEffect(() => {
    let active = true
    api
      .merchantStats(tab)
      .then((data) => active && setShops(data))
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [tab])

  // Counters are only needed when the menu opens, and they change as vouchers move.
  useEffect(() => {
    if (!menuOpen) return
    api.counts().then(setCounts).catch(() => undefined)
  }, [menuOpen])

  function selectTab(next: VoucherStatus) {
    haptic()
    setMenuOpen(false)
    if (next === tab) return
    onTabChange(next)
    setVouchers(null)
  }

  const emptyEmoji = EMPTY_EMOJI[tab]
  const filtering = Boolean(query.trim() || merchant)
  const currentLabel = STATUS_TABS.find((item) => item.key === tab)?.label ?? ''
  const selectedShop = shops.find((s) => s.merchant === merchant) ?? null

  return (
    <>
      <div className="topbar">
        {/* Inside Telegram the app name is already in its header, so this row
            carries the current list instead of repeating the title. */}
        <h1>{inTelegram ? currentLabel : `🐷 ${currentLabel}`}</h1>
        <button
          className="burger"
          onClick={() => {
            haptic()
            setMenuOpen(true)
          }}
          aria-label={t.list.menu}
        >
          ☰
        </button>
      </div>

      {menuOpen && (
        <TabMenu
          current={tab}
          counts={counts}
          onSelect={selectTab}
          onStats={() => {
            haptic()
            setMenuOpen(false)
            onStats()
          }}
          onClose={() => setMenuOpen(false)}
        />
      )}

      {shops.length > 1 && (
        <div className="chips">
          <button
            className={`chip ${merchant === null ? 'active' : ''}`}
            onClick={() => {
              haptic()
              onMerchantChange(null)
            }}
          >
            {t.list.all}
          </button>
          {shops.map((shop) => (
            <button
              key={shop.merchant}
              className={`chip ${merchant === shop.merchant ? 'active' : ''}`}
              onClick={() => {
                haptic()
                // Tapping the selected shop again clears the filter.
                onMerchantChange(merchant === shop.merchant ? null : shop.merchant)
              }}
            >
              {shop.merchant}
              <span className="chip-count">{shop.count}</span>
            </button>
          ))}
        </div>
      )}

      {selectedShop && (
        <p className="chip-summary">
          {t.list.shopSummary(
            selectedShop.merchant,
            t.list.cards(selectedShop.count),
            Number(selectedShop.balance) > 0 ? money(selectedShop.balance, 'EUR') : null,
          )}
        </p>
      )}

      <input
        className="search"
        placeholder={t.list.search}
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
      />

      {error && <div className="error">{error}</div>}

      {vouchers === null && !error && <div className="spinner" />}

      {vouchers?.length === 0 &&
        // An empty *result* is not an empty list: saying "add your first card"
        // while six of them sit behind a filter is simply wrong.
        (filtering ? (
          <div className="empty">
            <span className="emoji">🔍</span>
            <p>{t.list.noResults(query.trim())}</p>
            <button
              className="btn"
              onClick={() => {
                onQueryChange('')
                onMerchantChange(null)
              }}
            >
              {t.list.resetFilters}
            </button>
          </div>
        ) : (
          <div className="empty">
            <span className="emoji">{emptyEmoji}</span>
            <p>{t.empty[tab]}</p>
          </div>
        ))}

      {vouchers && vouchers.length > 0 && (
        <div className="list">
          {vouchers.map((voucher) => (
            <VoucherCard
              key={voucher.id}
              voucher={voucher}
              onClick={() => {
                haptic()
                onOpen(voucher.id)
              }}
            />
          ))}
        </div>
      )}

      <button className="fab" onClick={onCreate} aria-label={t.list.add}>
        +
      </button>
    </>
  )
}

/** Bottom sheet with the lists. Telegram's own ⋮ menu can hold a single
    "Settings" item at most, so anything richer has to be drawn by the app. */
function TabMenu({
  current,
  counts,
  onSelect,
  onStats,
  onClose,
}: {
  current: VoucherStatus
  counts: Counts | null
  onSelect: (tab: VoucherStatus) => void
  onStats: () => void
  onClose: () => void
}) {
  useOverlay(onClose)

  const leftInArchive = counts && Number(counts.archived_balance) > 0

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        {STATUS_TABS.map((item) => (
          <button
            key={item.key}
            className={`sheet-item ${item.key === current ? 'active' : ''}`}
            onClick={() => onSelect(item.key)}
          >
            <span className="sheet-label">
              {item.label}
              <span className="sheet-hint">{t.tabHints[item.key]}</span>
            </span>
            {counts && <span className="sheet-count">{counts[item.key]}</span>}
          </button>
        ))}

        {leftInArchive && (
          <p className="sheet-note">
            {t.list.inArchive(money(counts.archived_balance, counts.currency))}
          </p>
        )}

        <button className="sheet-item separated" onClick={onStats}>
          <span className="sheet-label">
            {t.list.stats}
            <span className="sheet-hint">{t.list.statsHint}</span>
          </span>
        </button>

        <button className="btn" onClick={onClose}>
          {t.list.close}
        </button>
      </div>
    </div>
  )
}

function VoucherCard({ voucher, onClick }: { voucher: Voucher; onClick: () => void }) {
  const expiry = expiryInfo(voucher)
  const value = primaryAmount(voucher)
  const subtitle = cardSubtitle(voucher)

  return (
    <button className="card" onClick={onClick}>
      <MerchantMark merchant={voucher.merchant || voucher.title} />

      <div className="body">
        <div className="merchant">{cardTitle(voucher)}</div>
        {subtitle && <div className="sub">{subtitle}</div>}
        <div className="card-meta">
          {/* Keyed off used_at, not the status: a spent voucher that was later
              archived must not look like it was never used. Once it is spent the
              expiry has nothing left to warn about, so it gives up its place. */}
          {voucher.used_at ? (
            <span className="badge ok">{t.list.spentOn(formatDate(voucher.used_at))}</span>
          ) : expiry ? (
            <span className={`badge ${expiry.tone === 'neutral' ? '' : expiry.tone}`}>
              {expiry.text}
            </span>
          ) : (
            <span className="badge">{t.list.noBalance}</span>
          )}
          {/* Icon only: the meta row has to stay on one line, and the word is
              right there on the card itself. */}
          {voucher.balance_uncertain && (
            <span
              className="badge glyph"
              title={t.list.unchecked}
              aria-label={t.list.unchecked}
            >
              ?
            </span>
          )}
          {voucher.comments_count > 0 && (
            <span className="badge">💬 {voucher.comments_count}</span>
          )}
        </div>
      </div>

      {value && (
        <div className="amount">
          <div className="value">{value}</div>
          {/* Face value only matters once part of the card is gone. */}
          {isPartlySpent(voucher) && voucher.value_amount && (
            <div className="of">{t.list.outOf(money(voucher.value_amount, voucher.currency))}</div>
          )}
        </div>
      )}
    </button>
  )
}
