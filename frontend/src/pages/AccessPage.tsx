import { useEffect, useState } from 'react'

import { api } from '../api'
import { formatDateTime } from '../format'
import { t } from '../i18n'
import { haptic } from '../telegram'
import type { Invite, Session } from '../types'

/**
 * Who can get in, and from where.
 *
 * Two jobs on one screen because they are two halves of the same thing: minting a
 * way in, and taking one away. Handing out invitations without being able to
 * sign a lost phone out would be lopsided.
 */
export default function AccessPage({ onBack }: { onBack: () => void }) {
  const [sessions, setSessions] = useState<Session[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [link, setLink] = useState<Invite | null>(null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const load = () =>
    api
      .sessions()
      .then(setSessions)
      .catch((e: Error) => setError(e.message))

  useEffect(() => {
    void load()
  }, [])

  async function act(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      haptic('success')
      await load()
    } catch (e) {
      setError((e as Error).message)
      haptic('error')
    } finally {
      setBusy(false)
    }
  }

  async function mint(withName: boolean) {
    setBusy(true)
    setError(null)
    setCopied(false)
    try {
      setLink(await api.invite(withName ? name.trim() : ''))
      if (withName) setName('')
      haptic('success')
    } catch (e) {
      setError((e as Error).message)
      haptic('error')
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    if (!link) return
    try {
      await navigator.clipboard.writeText(link.url)
      setCopied(true)
      haptic()
    } catch {
      setCopied(false)
    }
  }

  return (
    <>
      <div className="topbar">
        <button className="back" onClick={onBack} aria-label={t.common.back}>
          ‹
        </button>
        <h1>{t.access.title}</h1>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="panel">
        <h2>{t.access.inviteTitle}</h2>
        <input
          className="invite-name"
          placeholder={t.access.namePlaceholder}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <div className="access-actions">
          <button className="btn primary" disabled={busy || !name.trim()} onClick={() => mint(true)}>
            {t.access.invite}
          </button>
          <button className="btn" disabled={busy} onClick={() => mint(false)}>
            {t.access.myDevice}
          </button>
        </div>

        {link && (
          <div className="invite-link">
            <code>{link.url}</code>
            <button className="btn link" onClick={copy}>
              {copied ? t.card.copied : t.card.copy}
            </button>
            <p className="muted">{t.access.linkNote(link.minutes)}</p>
          </div>
        )}
      </div>

      <div className="panel">
        <h2>{t.access.devices}</h2>
        {sessions === null && !error && <div className="spinner" />}
        {sessions?.length === 0 && <p className="muted">{t.access.empty}</p>}

        {sessions?.map((session) => (
          <div className="device" key={session.id}>
            <div className="sheet-label">
              {session.member}
              <span className="sheet-hint">
                {session.current
                  ? t.access.thisDevice
                  : session.last_used_at
                    ? t.access.lastSeen(formatDateTime(session.last_used_at))
                    : t.access.never}
              </span>
            </div>
            {!session.current && (
              <button
                className="btn link danger"
                disabled={busy}
                onClick={() => act(() => api.revokeSession(session.id))}
              >
                {t.access.revoke}
              </button>
            )}
          </div>
        ))}

        {(sessions?.length ?? 0) > 1 && (
          <button
            className="btn"
            disabled={busy}
            onClick={() => {
              if (confirm(t.access.revokeOthersConfirm)) void act(api.revokeOtherSessions)
            }}
          >
            {t.access.revokeOthers}
          </button>
        )}

        <p className="muted">{t.access.telegramNote}</p>
      </div>
    </>
  )
}
