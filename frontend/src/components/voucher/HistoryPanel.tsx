import { eventText, formatDateTime } from '../../format'
import type { VoucherEvent } from '../../types'

/** The append-only trail: who spent what, who fixed what, and when. */
export default function HistoryPanel({ events }: { events: VoucherEvent[] }) {
  return (
    <div className="panel">
      <h2>История</h2>
      <div className="history">
        {events.map((event) => (
          <div className="item" key={event.id}>
            <span className="when">{formatDateTime(event.created_at)}</span>
            <span>
              {event.actor?.display_name ?? 'Система'} {eventText(event.kind, event.payload)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
