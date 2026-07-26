import { useCallback, useEffect, useRef, useState } from 'react'

import { t } from '../i18n'

const MIN_SCALE = 1
const MAX_SCALE = 6
const STEP = 1.6
const DOUBLE_TAP_MS = 300
const DOUBLE_TAP_SCALE = 2.5

interface Props {
  src: string
  alt: string
  /** Rotated 90°: the layout box keeps its pre-rotation size. */
  rotated: boolean
  className?: string
}

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value))

/**
 * Pan-and-zoom image for the checkout counter: pinch, double-tap or the ± buttons.
 *
 * The page viewport is locked (`user-scalable=no`), so browser zoom is not an
 * option — and inside Telegram a native pinch would scale the whole Mini App.
 * Gestures are handled here with pointer events and `touch-action: none`, which
 * also stops Telegram from reading a drag as swipe-to-close.
 */
export default function ZoomableImage({ src, alt, rotated, className }: Props) {
  const [scale, setScale] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [frame, setFrame] = useState({ width: 0, height: 0 })
  const [natural, setNatural] = useState({ width: 0, height: 0 })
  const frameRef = useRef<HTMLDivElement | null>(null)
  // Read inside gesture callbacks, which must not be re-created on every fit change.
  const fitRef = useRef(1)
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const pinch = useRef<{ distance: number; scale: number } | null>(null)
  const lastTap = useRef(0)

  // A fresh image (or a rotation) should start from a neutral view.
  useEffect(() => {
    setScale(1)
    setOffset({ x: 0, y: 0 })
  }, [src, rotated])

  const measureFrame = useCallback(() => {
    const frame = frameRef.current
    if (frame) setFrame({ width: frame.clientWidth, height: frame.clientHeight })
  }, [])

  useEffect(() => {
    measureFrame()
    window.addEventListener('resize', measureFrame)
    return () => window.removeEventListener('resize', measureFrame)
  }, [measureFrame])

  // The element is sized to the picture itself instead of being letterboxed by
  // object-fit: then the layout box and the visible image are the same thing, and
  // the rotation maths below has nothing to guess.
  const contain =
    natural.width && frame.width
      ? Math.min(frame.width / natural.width, frame.height / natural.height)
      : 0
  const shown = { width: natural.width * contain, height: natural.height * contain }
  // Rotated, the picture takes its height across and its width down.
  const fit =
    rotated && shown.width
      ? Math.min(frame.width / shown.height, frame.height / shown.width)
      : 1
  fitRef.current = fit

  /** Keep the image from being dragged off-screen. */
  const clampOffset = useCallback(
    (next: { x: number; y: number }, currentScale: number) => {
      const frame = frameRef.current
      if (!frame) return next
      // The visible size is the user's zoom times the rotation fit, so the pan
      // limits have to account for both — otherwise a rotated image can be
      // dragged past its own edge.
      const effective = currentScale * fitRef.current
      const limitX = (frame.clientWidth * (effective - 1)) / 2
      const limitY = (frame.clientHeight * (effective - 1)) / 2
      return {
        x: clamp(next.x, -limitX, limitX),
        y: clamp(next.y, -limitY, limitY),
      }
    },
    [],
  )

  const zoomTo = useCallback(
    (target: number) => {
      const next = clamp(target, MIN_SCALE, MAX_SCALE)
      setScale(next)
      setOffset((current) =>
        next === MIN_SCALE ? { x: 0, y: 0 } : clampOffset(current, next),
      )
    },
    [clampOffset],
  )

  function onPointerDown(event: React.PointerEvent) {
    try {
      // Keeps move events coming if the finger leaves the frame; throws when the
      // pointer is no longer active, which must not break the gesture.
      ;(event.target as Element).setPointerCapture?.(event.pointerId)
    } catch {
      // ignore
    }
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })

    if (pointers.current.size > 1) {
      // A second finger means this is a pinch, not a tap. Forget the first
      // finger's timestamp, or the next single tap right after the pinch would
      // count as a double tap and jump the zoom.
      lastTap.current = 0
      return
    }

    const now = event.timeStamp
    if (now - lastTap.current < DOUBLE_TAP_MS) {
      zoomTo(scale > MIN_SCALE ? MIN_SCALE : DOUBLE_TAP_SCALE)
      lastTap.current = 0
    } else {
      lastTap.current = now
    }
  }

  function onPointerMove(event: React.PointerEvent) {
    const previous = pointers.current.get(event.pointerId)
    if (!previous) return
    const current = { x: event.clientX, y: event.clientY }
    pointers.current.set(event.pointerId, current)

    const points = [...pointers.current.values()]
    if (points.length >= 2) {
      const [a, b] = points
      const distance = Math.hypot(a.x - b.x, a.y - b.y)
      if (pinch.current === null) {
        pinch.current = { distance, scale }
        return
      }
      zoomTo((pinch.current.scale * distance) / pinch.current.distance)
      return
    }

    if (scale > MIN_SCALE) {
      const dx = current.x - previous.x
      const dy = current.y - previous.y
      setOffset((o) => clampOffset({ x: o.x + dx, y: o.y + dy }, scale))
    }
  }

  function onPointerUp(event: React.PointerEvent) {
    pointers.current.delete(event.pointerId)
    if (pointers.current.size < 2) pinch.current = null
  }

  function onWheel(event: React.WheelEvent) {
    event.preventDefault()
    zoomTo(scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15))
  }

  return (
    <>
      <div
        className="zoom-frame"
        ref={frameRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onWheel={onWheel}
      >
        <img
          className={className}
          src={src}
          alt={alt}
          draggable={false}
          onLoad={(e) =>
            setNatural({
              width: e.currentTarget.naturalWidth,
              height: e.currentTarget.naturalHeight,
            })
          }
          style={{
            width: shown.width || undefined,
            height: shown.height || undefined,
            // Read right to left: rotate, then scale to fit and to the user's
            // zoom, then pan — so dragging stays aligned with the screen axes.
            transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale * fit}) ${
              rotated ? 'rotate(90deg)' : ''
            }`,
          }}
        />
      </div>

      <div className="zoom-controls">
        <button
          className="btn"
          onClick={() => zoomTo(scale / STEP)}
          disabled={scale <= MIN_SCALE}
          aria-label={t.scan.zoomOut}
        >
          −
        </button>
        <span className="zoom-level">{Math.round(scale * 100)}%</span>
        <button
          className="btn"
          onClick={() => zoomTo(scale * STEP)}
          disabled={scale >= MAX_SCALE}
          aria-label={t.scan.zoomIn}
        >
          +
        </button>
      </div>
    </>
  )
}
