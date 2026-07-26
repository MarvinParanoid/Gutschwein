import { createDemoApi } from './demo/api'
import { demoBarcode, demoImage } from './demo/assets'
import { isDemo } from './demo/session'
import { locale, t } from './i18n'
import { tg } from './telegram'
import type {
  Comment,
  Counts,
  MerchantStat,
  Stats,
  User,
  Voucher,
  VoucherDraft,
  VoucherEvent,
  VoucherStatus,
} from './types'

export class ApiError extends Error {}

/** The server answers errors in this language; it matches what the UI shows. */
function languageHeader(): Record<string, string> {
  return { 'Accept-Language': locale.startsWith('ru') ? 'ru' : 'en' }
}

function authHeaders(): Record<string, string> {
  const initData = tg?.initData
  if (initData) return { Authorization: `tma ${initData}` }
  // Outside Telegram only the dev server can authenticate (backend DEV_MODE=true).
  if (import.meta.env.DEV) return { 'X-Dev-User': '1000' }
  return {}
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    // Carries the PWA session cookie; inside Telegram there is none and the
    // Authorization header below does the work.
    credentials: 'same-origin',
    headers: {
      ...authHeaders(),
      ...languageHeader(),
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init.headers,
    },
  })

  if (!response.ok) {
    let detail = t.app.genericError(response.status)
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = body.detail[0]?.msg ?? detail
    } catch {
      // non-JSON error body: keep the status text
    }
    throw new ApiError(detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const httpApi = {
  /** Exchanges the one-time token from the bot's link for a session cookie. */
  login: (token: string) =>
    request<User>('/api/auth/login', { method: 'POST', body: JSON.stringify({ token }) }),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),

  me: () => request<{ user: User; members: User[] }>('/api/me'),

  listVouchers: (status: VoucherStatus | 'all', q?: string, merchant?: string | null) => {
    const params = new URLSearchParams({ status })
    if (q?.trim()) params.set('q', q.trim())
    if (merchant) params.set('merchant', merchant)
    return request<Voucher[]>(`/api/vouchers?${params}`)
  },
  getVoucher: (id: number) => request<Voucher>(`/api/vouchers/${id}`),
  merchants: () => request<string[]>('/api/vouchers/merchants'),
  counts: () => request<Counts>('/api/vouchers/counts'),
  stats: () => request<Stats>('/api/vouchers/stats'),
  merchantStats: (status: VoucherStatus | 'all') =>
    request<MerchantStat[]>(`/api/vouchers/merchants/stats?status=${status}`),

  createVoucher: (draft: VoucherDraft) =>
    request<Voucher>('/api/vouchers', { method: 'POST', body: JSON.stringify(draft) }),
  updateVoucher: (id: number, patch: Partial<VoucherDraft>) =>
    request<Voucher>(`/api/vouchers/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteVoucher: (id: number) => request<void>(`/api/vouchers/${id}`, { method: 'DELETE' }),

  transition: (id: number, action: 'use' | 'unuse' | 'archive' | 'restore' | 'activate') =>
    request<Voucher>(`/api/vouchers/${id}/${action}`, { method: 'POST' }),

  /** Send either what was just spent, or the balance printed on the receipt. */
  updateBalance: (id: number, body: { spent?: string; remaining?: string; note?: string }) =>
    request<Voucher>(`/api/vouchers/${id}/balance`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  comments: (id: number) => request<Comment[]>(`/api/vouchers/${id}/comments`),
  addComment: (id: number, text: string) =>
    request<Comment>(`/api/vouchers/${id}/comments`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  deleteComment: (voucherId: number, commentId: number) =>
    request<void>(`/api/vouchers/${voucherId}/comments/${commentId}`, { method: 'DELETE' }),

  events: (id: number) => request<VoucherEvent[]>(`/api/vouchers/${id}/events`),

  uploadImage: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const { image_id } = await request<{ image_id: string }>('/api/uploads', {
      method: 'POST',
      body: form,
    })
    return image_id
  },
}

/** The shape every screen talks to. The demo client has to satisfy it exactly. */
export type ApiClient = typeof httpApi

// Chosen once, at load: a demo session never has a code path back to the server.
export const api: ApiClient = isDemo() ? createDemoApi() : httpApi

export const imageUrl = (imageId: string) =>
  isDemo() ? demoImage(imageId) : `/api/images/${imageId}`
/** Barcode redrawn from the decoded code — sharp at any zoom, unlike the screenshot. */
export const barcodeUrl = (imageId: string) =>
  isDemo() ? demoBarcode(imageId) : `/api/barcodes/${imageId}`
