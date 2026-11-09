/**
 * Puts `text` on the clipboard. True when it got there.
 *
 * The async Clipboard API is missing or refused in some of the places the app
 * runs — older Android WebViews inside Telegram among them — so the old
 * select-and-copy route is the fallback before giving up.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // fall through to the textarea
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
  }
}
