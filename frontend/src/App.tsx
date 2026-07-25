import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import ListPage from './pages/ListPage'
import StatsPage from './pages/StatsPage'
import VoucherForm from './pages/VoucherForm'
import VoucherPage from './pages/VoucherPage'
import { inTelegram, initTelegram } from './telegram'
import type { User, VoucherStatus } from './types'
import { useBackButton } from './useBackButton'

type View =
  | { name: 'list' }
  | { name: 'voucher'; id: number }
  | { name: 'form'; id?: number }
  | { name: 'stats' }

export default function App() {
  const [view, setView] = useState<View>({ name: 'list' })
  const [me, setMe] = useState<User | null>(null)
  const [authError, setAuthError] = useState<string | null>(null)

  // Tab, query and shop filter live here so they survive navigation into a
  // voucher and back — you pick Rewe, open a card, and come back to Rewe.
  const [tab, setTab] = useState<VoucherStatus>('active')
  const [query, setQuery] = useState('')
  const [merchant, setMerchant] = useState<string | null>(null)

  useEffect(() => {
    initTelegram()
    api
      .me()
      .then((data) => setMe(data.user))
      .catch((error: Error) => setAuthError(error.message))
  }, [])

  // Views are mirrored into the history stack, so Telegram's back button, the
  // Android system back gesture and the browser's back arrow all do the same
  // thing. Without this, system back would close the Mini App outright.
  useEffect(() => {
    history.replaceState({ view: { name: 'list' } satisfies View }, '')
    const onPopState = (event: PopStateEvent) =>
      setView((event.state?.view as View | undefined) ?? { name: 'list' })
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigate = useCallback((next: View, replace = false) => {
    setView(next)
    if (replace) history.replaceState({ view: next }, '')
    else history.pushState({ view: next }, '')
  }, [])

  const goBack = useCallback(() => history.back(), [])
  useBackButton(view.name !== 'list', goBack)

  if (authError) {
    return (
      <div className="app">
        <div className="empty">
          <span className="emoji">🔒</span>
          <p>{authError}</p>
          {!inTelegram && (
            <p className="muted">Откройте приложение через бота в Telegram.</p>
          )}
        </div>
      </div>
    )
  }

  if (!me) return <div className="spinner" />

  return (
    <div className="app">
      {view.name === 'list' && (
        <ListPage
          tab={tab}
          onTabChange={(next) => {
            setTab(next)
            // A shop that has cards in one list may have none in another.
            setMerchant(null)
          }}
          query={query}
          onQueryChange={setQuery}
          merchant={merchant}
          onMerchantChange={setMerchant}
          onOpen={(id) => navigate({ name: 'voucher', id })}
          onCreate={() => navigate({ name: 'form' })}
          onStats={() => navigate({ name: 'stats' })}
        />
      )}

      {view.name === 'stats' && <StatsPage onBack={goBack} />}

      {view.name === 'voucher' && (
        <VoucherPage
          voucherId={view.id}
          me={me}
          onBack={goBack}
          onDeleted={() => navigate({ name: 'list' }, true)}
          onEdit={() => navigate({ name: 'form', id: view.id })}
        />
      )}

      {view.name === 'form' && (
        <VoucherForm
          voucherId={view.id}
          onCancel={goBack}
          // Replace, so back from the saved voucher lands on the list, not the form.
          onSaved={(id) => navigate({ name: 'voucher', id }, true)}
        />
      )}
    </div>
  )
}
