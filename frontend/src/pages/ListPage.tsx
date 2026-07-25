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
  primaryAmount,
} from '../format'
import { haptic, inTelegram } from '../telegram'
import type { Voucher, VoucherStatus } from '../types'

interface Props {
  tab: VoucherStatus
  onTabChange: (tab: VoucherStatus) => void
  query: string
  onQueryChange: (query: string) => void
  onOpen: (id: number) => void
  onCreate: () => void
}

const EMPTY_STATES: Record<VoucherStatus, { emoji: string; text: string }> = {
  active: { emoji: '🐷', text: 'Пока пусто. Пришлите фото купона боту или добавьте вручную.' },
  draft: { emoji: '📸', text: 'Черновиков нет. Отправьте боту скрин — он появится здесь.' },
  used: { emoji: '✅', text: 'Ничего пока не потрачено.' },
  archived: { emoji: '📦', text: 'Архив пуст.' },
}

export default function ListPage({
  tab,
  onTabChange,
  query,
  onQueryChange,
  onOpen,
  onCreate,
}: Props) {
  const [vouchers, setVouchers] = useState<Voucher[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [debouncedQuery, setDebouncedQuery] = useState(query)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 250)
    return () => clearTimeout(timer)
  }, [query])

  useEffect(() => {
    let active = true
    setError(null)
    api
      .listVouchers(tab, debouncedQuery)
      .then((data) => active && setVouchers(data))
      .catch((e: Error) => active && setError(e.message))
    return () => {
      active = false
    }
  }, [tab, debouncedQuery])

  const empty = EMPTY_STATES[tab]

  return (
    <>
      {/* Telegram already shows the app name in its own header; only the browser
          (and a future PWA) needs a title of our own. */}
      {!inTelegram && (
        <div className="topbar">
          <h1>🐷 Sparschwein</h1>
        </div>
      )}

      <div className="tabs">
        {STATUS_TABS.map((item) => (
          <button
            key={item.key}
            className={`tab ${item.key === tab ? 'active' : ''}`}
            onClick={() => {
              haptic()
              onTabChange(item.key)
              setVouchers(null)
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      <input
        className="search"
        placeholder="Поиск: магазин, код, условия…"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
      />

      {error && <div className="error">{error}</div>}

      {vouchers === null && !error && <div className="spinner" />}

      {vouchers?.length === 0 && (
        <div className="empty">
          <span className="emoji">{empty.emoji}</span>
          <p>{empty.text}</p>
        </div>
      )}

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

function VoucherCard({ voucher, onClick }: { voucher: Voucher; onClick: () => void }) {
  const expiry = expiryInfo(voucher)
  const value = primaryAmount(voucher)
  const subtitle = cardSubtitle(voucher)

  return (
    <button className="card" onClick={onClick}>
      {voucher.image_id ? (
        <img className="thumb" src={imageUrl(voucher.image_id)} alt="" loading="lazy" />
      ) : (
        <div className="thumb placeholder">🎟️</div>
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
          {voucher.status === 'used' && voucher.used_at && (
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
