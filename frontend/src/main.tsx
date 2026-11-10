import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import { dropUnversionedBarcodes } from './pwaCache'
import { applyStoredTheme } from './theme'
import './styles.css'

// Before the first paint: a device that picked a mode by hand should not see the
// other one first. (An inline script in index.html would be a hair earlier still,
// at the cost of the storage key living in two places.)
applyStoredTheme()

// Housekeeping, never in the way of the first paint, never worth an error.
void dropUnversionedBarcodes().catch(() => undefined)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
