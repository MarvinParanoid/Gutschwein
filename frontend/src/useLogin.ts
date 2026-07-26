import { useEffect, useState } from 'react'

import { api } from './api'
import { t } from './i18n'

export type LoginState = 'idle' | 'working' | 'failed'

/**
 * Handles the `/login#<token>` link the bot sends.
 *
 * The token lives in the fragment on purpose: fragments are never sent to a
 * server, so the one-time credential stays out of access logs and referrers.
 * It is also wiped from the address bar as soon as it has been redeemed.
 */
export function useLogin(): { state: LoginState; error: string | null } {
  const [state, setState] = useState<LoginState>(() =>
    window.location.pathname === '/login' ? 'working' : 'idle',
  )
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (window.location.pathname !== '/login') return
    const token = window.location.hash.replace(/^#/, '')
    if (!token) {
      setState('failed')
      setError(t.app.loginNoToken)
      return
    }

    api
      .login(token)
      .then(() => {
        // Drop the token from the URL before anything can bookmark or share it.
        window.history.replaceState({}, '', '/')
        setState('idle')
      })
      .catch((e: Error) => {
        window.history.replaceState({}, '', '/')
        setState('failed')
        setError(e.message)
      })
  }, [])

  return { state, error }
}
