import { useEffect } from 'react'

/**
 * Closes an overlay on Escape and locks the page behind it.
 *
 * On a phone the backdrop is enough, but the PWA runs in a browser where Escape
 * is what people press — and nothing was listening for it.
 */
export function useOverlay(onClose: () => void): void {
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)

    return () => {
      document.body.style.overflow = previous
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [onClose])
}
