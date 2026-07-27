import { useEffect } from 'react'

/**
 * Marks the page as scrolled, so the sticky top bar can cast a shadow only when
 * there is something underneath it.
 *
 * A flag on <body> rather than per-page state: every screen has a top bar, and
 * one listener is enough for all of them.
 */
export function useScrolled(): void {
  useEffect(() => {
    const update = () => {
      document.body.classList.toggle('scrolled', window.scrollY > 4)
    }
    update()
    window.addEventListener('scroll', update, { passive: true })
    return () => {
      window.removeEventListener('scroll', update)
      document.body.classList.remove('scrolled')
    }
  }, [])
}
