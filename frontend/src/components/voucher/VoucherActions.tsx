import { isGiftCard } from '../../format'
import { t } from '../../i18n'
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
            {t.actions.activate}
          </button>
        )}
        {voucher.status === 'active' && (
          <button className="btn" disabled={busy} onClick={() => onTransition('use')}>
            {isGiftCard(voucher) ? t.actions.useUp : t.actions.markUsed}
          </button>
        )}
        {voucher.status === 'used' && (
          <button className="btn" disabled={busy} onClick={() => onTransition('unuse')}>
            {t.actions.unuse}
          </button>
        )}
        {voucher.status === 'archived' ? (
          <button className="btn" disabled={busy} onClick={() => onTransition('restore')}>
            {t.actions.restore}
          </button>
        ) : (
          <button className="btn" disabled={busy} onClick={() => onTransition('archive')}>
            {t.actions.archive}
          </button>
        )}
        <button className="btn" onClick={onEdit}>
          {t.actions.edit}
        </button>
        <button className="btn danger" onClick={onDelete}>
          {t.actions.delete}
        </button>
      </div>
    </div>
  )
}
