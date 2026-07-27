import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

/** Past this many pixels the sheet is being dismissed, not nudged. */
const DISMISS_AFTER = 90

/**
 * Drag a bottom sheet down to close it.
 *
 * The handle at the top of a sheet promises this gesture on every phone, and a
 * handle that does nothing when pulled reads as a broken app rather than as a
 * decoration.
 *
 * The drag starts anywhere on the sheet, not only on the handle — a 40×4 bar is
 * a cruel target — but only while the sheet is scrolled to the top, so a long
 * sheet can still be scrolled with the same finger movement.
 */
export function useSheetDrag(onClose: () => void) {
  const [offset, setOffset] = useState(0)
  const [dragging, setDragging] = useState(false)
  const start = useRef(0)

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    if (event.currentTarget.scrollTop > 0) return
    start.current = event.clientY
    setDragging(true)
  }

  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!dragging) return
    const delta = event.clientY - start.current
    // Upwards the sheet does not move: there is nothing above it to reveal.
    setOffset(Math.max(0, delta))
  }

  function onPointerUp() {
    if (!dragging) return
    setDragging(false)
    if (offset > DISMISS_AFTER) onClose()
    else setOffset(0)
  }

  return {
    dragging,
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel: onPointerUp,
    },
    style: {
      transform: offset ? `translateY(${offset}px)` : undefined,
      // While the finger is down the sheet tracks it exactly; on release it
      // springs back, unless it is already on its way out.
      transition: dragging ? 'none' : undefined,
    },
  }
}
