import { isGiftCard } from '../../format'
import type { Voucher } from '../../types'

export type Transition = 'use' | 'unuse' | 'archive' | 'restore' | 'activate'

/** Which actions make sense depends on the status, so the buttons are derived. */
export default function VoucherActions({
  voucher,
  busy,
  onTransition,
  onEdit,
  onDelete,
}: {
  voucher: Voucher
  busy: boolean
  onTransition: (action: Transition) => void
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <div className="panel">
      <div className="actions">
        {voucher.status === 'draft' && (
          <button className="btn primary" disabled={busy} onClick={() => onTransition('activate')}>
            В активные
          </button>
        )}
        {voucher.status === 'active' && (
          <button className="btn" disabled={busy} onClick={() => onTransition('use')}>
            ✅ {isGiftCard(voucher) ? 'Потратил полностью' : 'Использован'}
          </button>
        )}
        {voucher.status === 'used' && (
          <button className="btn" disabled={busy} onClick={() => onTransition('unuse')}>
            Вернуть в активные
          </button>
        )}
        {voucher.status === 'archived' ? (
          <button className="btn" disabled={busy} onClick={() => onTransition('restore')}>
            Достать из архива
          </button>
        ) : (
          <button className="btn" disabled={busy} onClick={() => onTransition('archive')}>
            📦 В архив
          </button>
        )}
        <button className="btn" onClick={onEdit}>
          ✏️ Изменить
        </button>
        <button className="btn danger" onClick={onDelete}>
          Удалить
        </button>
      </div>
    </div>
  )
}
