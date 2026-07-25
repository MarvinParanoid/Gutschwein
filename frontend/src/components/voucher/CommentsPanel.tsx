import { useState } from 'react'

import { api } from '../../api'
import { formatDateTime } from '../../format'
import { alertMessage, confirmAction, haptic } from '../../telegram'
import type { Comment, User } from '../../types'

export default function CommentsPanel({
  voucherId,
  me,
  comments,
  onChanged,
}: {
  voucherId: number
  me: User
  comments: Comment[]
  onChanged: () => void
}) {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)

  async function send() {
    const trimmed = text.trim()
    if (!trimmed || sending) return
    setSending(true)
    try {
      await api.addComment(voucherId, trimmed)
      setText('')
      haptic()
      onChanged()
    } catch (e) {
      alertMessage((e as Error).message)
    } finally {
      setSending(false)
    }
  }

  async function remove(commentId: number) {
    if (!(await confirmAction('Удалить комментарий?'))) return
    try {
      await api.deleteComment(voucherId, commentId)
      onChanged()
    } catch (e) {
      alertMessage((e as Error).message)
    }
  }

  return (
    <div className="panel">
      <h2>Комментарии</h2>
      {comments.length === 0 && <p className="muted">Пока никто ничего не написал.</p>}
      {comments.map((comment) => (
        <div className="comment" key={comment.id}>
          <div className="head">
            <span className="author">{comment.author.display_name}</span>
            <span>{formatDateTime(comment.created_at)}</span>
            {/* Only your own: deleting someone else's word is not yours to do. */}
            {comment.author.id === me.id && (
              <button className="btn link" onClick={() => remove(comment.id)}>
                удалить
              </button>
            )}
          </div>
          <div>{comment.text}</div>
        </div>
      ))}

      <div className="comment-form">
        <input
          placeholder="Написать семье…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
        />
        <button className="btn primary" disabled={!text.trim() || sending} onClick={send}>
          →
        </button>
      </div>
    </div>
  )
}
