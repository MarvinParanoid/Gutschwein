import { useEffect } from 'react'

import { tg } from './telegram'

/** Wires Telegram's native back button to `onBack` while `visible` is true. */
export function useBackButton(visible: boolean, onBack: () => void): void {
  useEffect(() => {
    const back = tg?.BackButton
    if (!back) return
    if (!visible) {
      back.hide()
      return
    }
    back.onClick(onBack)
    back.show()
    return () => {
      back.offClick(onBack)
      back.hide()
    }
  }, [visible, onBack])
}
