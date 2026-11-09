import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import { dropUnversionedBarcodes } from './pwaCache'
import './styles.css'

// Housekeeping, never in the way of the first paint, never worth an error.
void dropUnversionedBarcodes().catch(() => undefined)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
