import { useEffect, useState } from 'react'

import { api, imageUrl } from '../api'
import {
  STATUS_TABS,
  cardSubtitle,
  cardTitle,
  expiryInfo,
  formatDate,
  isPartlySpent,
  money,
  plural,
  primaryAmount,
} from '../format'
import { haptic, inTelegram } from '../telegram'
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

const EMPTY_STATES: Record<VoucherStatus, { emoji: string; text: string }> = {
  active: { emoji: '🐷', text: 'Пока пусто. Пришлите фото купона боту или добавьте вручную.' },
  draft: { emoji: '📸', text: 'Черновиков нет. Отправьте боту скрин — он появится здесь.' },
  used: { emoji: '✅', text: 'Ничего пока не потрачено.' },
  archived: { emoji: '📦', text: 'Архив пуст.' },
}

const TAB_HINTS: Record<VoucherStatus, string> = {
  active: 'есть чем платить',
  draft: 'фото есть, поля не заполнены',
  used: 'денег на них не осталось',
  archived: 'убраны с глаз, деньги могли остаться',
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

  const empty = EMPTY_STATES[tab]
  const filtering = Boolean(query.trim() || merchant)
  const currentLabel = STATUS_TABS.find((t) => t.key === tab)?.label ?? ''
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
          aria-label="Меню"
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
            Все
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
          {selectedShop.merchant}: {selectedShop.count}{' '}
          {plural(selectedShop.count, 'карта', 'карты', 'карт')}
          {Number(selectedShop.balance) > 0 && ` · ${money(selectedShop.balance, 'EUR')}`}
        </p>
      )}

      <input
        className="search"
        placeholder="Поиск: магазин, заметка…"
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
            <p>Ничего не нашлось{query.trim() && ` по запросу «${query.trim()}»`}.</p>
            <button
              className="btn"
              onClick={() => {
                onQueryChange('')
                onMerchantChange(null)
              }}
            >
              Сбросить фильтры
            </button>
          </div>
        ) : (
          <div className="empty">
            <span className="emoji">{empty.emoji}</span>
            <p>{empty.text}</p>
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

      <button className="fab" onClick={onCreate} aria-label="Добавить купон">
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
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

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
              <span className="sheet-hint">{TAB_HINTS[item.key]}</span>
            </span>
            {counts && <span className="sheet-count">{counts[item.key]}</span>}
          </button>
        ))}

        {leftInArchive && (
          <p className="sheet-note">
            💸 В архиве ещё {money(counts.archived_balance, counts.currency)} — возможно,
            эти карты рано убрали
          </p>
        )}

        <button className="sheet-item separated" onClick={onStats}>
          <span className="sheet-label">
            📊 Статистика
            <span className="sheet-hint">сколько лежит, куда уходит, кто тратит</span>
          </span>
        </button>

        <button className="btn" onClick={onClose}>
          Закрыть
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
      {voucher.image_id ? (
        <img className="thumb" src={imageUrl(voucher.image_id)} alt="" loading="lazy" />
      ) : (
        // The shop's initial reads faster than a row of identical icons.
        <div className="thumb placeholder">
          {(voucher.merchant || voucher.title || '?').trim().charAt(0).toUpperCase()}
        </div>
      )}

      <div className="body">
        <div className="merchant">{cardTitle(voucher)}</div>
        {subtitle && <div className="sub">{subtitle}</div>}
        <div className="card-meta">
          {expiry ? (
            <span className={`badge ${expiry.tone === 'neutral' ? '' : expiry.tone}`}>
              {expiry.text}
            </span>
          ) : (
            <span className="badge">без срока</span>
          )}
          {/* Keyed off used_at, not the status: a spent voucher that was later
              archived must not look like it was never used. */}
          {voucher.used_at && (
            <span className="badge ok">потрачен {formatDate(voucher.used_at)}</span>
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
            <div className="of">из {money(voucher.value_amount, voucher.currency)}</div>
          )}
        </div>
      )}
    </button>
  )
}
