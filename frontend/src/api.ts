const BASE = '/api'

export interface Account {
  id: number
  email: string
  password: string
  access_token: string | null
  refresh_token: string | null
  id_token: string | null
  account_id: string | null
  token_expired_at: string | null
  temp_email_provider: string | null
  proxy_used: string | null
  status: string
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface Provider {
  id: number
  name: string
  base_url: string
  origin: string
  enabled: boolean
  fail_count: number
  created_at: string
}

export interface Proxy {
  id: number
  url: string
  proxy_type: string
  enabled: boolean
  fail_count: number
  last_test_ok: boolean | null
  last_test_ms: number | null
  last_test_info: string | null
  last_test_at: string | null
  created_at: string
}

export interface Settings {
  thread_count: number
  default_password: string
  default_proxy: string
  registration_delay_min: number
  registration_delay_max: number
  email_poll_timeout: number
  auto_switch_provider: boolean
}

export interface RegStatus {
  running: boolean
  total: number
  completed: number
  success: number
  failed: number
}

class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 30000)

  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      ...init,
    })
    if (!res.ok) {
      let msg: string
      try {
        const data = await res.json()
        msg = data.detail || data.message || JSON.stringify(data)
      } catch {
        msg = await res.text()
      }
      throw new ApiError(msg || `HTTP ${res.status}`, res.status)
    }
    const ct = res.headers.get('content-type') || ''
    if (ct.includes('application/json')) return res.json()
    return res as unknown as T
  } finally {
    clearTimeout(timeout)
  }
}

// Accounts
export interface Stats {
  total: number
  success: number
  failed: number
  registering: number
  pending: number
  success_rate: number
}

export const getStats = () => request<Stats>('/accounts/stats')

export const getAccounts = (status?: string, limit = 50, offset = 0) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (status) params.set('status', status)
  return request<{ items: Account[]; total: number }>(`/accounts?${params}`)
}

export const deleteAccount = (id: number) =>
  request(`/accounts/${id}`, { method: 'DELETE' })

export const batchDeleteAccounts = (ids: number[]) =>
  request<{ deleted: number }>('/accounts/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  })

export const deleteFailedAccounts = () =>
  request<{ deleted: number }>('/accounts/failed', { method: 'DELETE' })

export const refreshAccountToken = (id: number) =>
  request<{ ok: boolean; token_expired_at: string }>(`/accounts/${id}/refresh-token`, { method: 'POST' })

export const batchRefreshTokens = () =>
  request<{ success: number; failed: number }>('/accounts/batch-refresh', { method: 'POST' })

export const exportAccounts = async (fields: string[], format: string, statusFilter?: string, ids?: number[]) => {
  const res = await fetch(`${BASE}/accounts/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fields, format, status_filter: statusFilter, ids: ids || null }),
  })
  if (!res.ok) throw new Error(await res.text())
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `accounts.${format}`
  a.click()
  URL.revokeObjectURL(url)
}

// Providers
export const getProviders = () => request<Provider[]>('/providers')
export const addProvider = (data: Partial<Provider>) =>
  request<Provider>('/providers', { method: 'POST', body: JSON.stringify(data) })
export const updateProvider = (id: number, data: Partial<Provider>) =>
  request<Provider>(`/providers/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteProvider = (id: number) =>
  request(`/providers/${id}`, { method: 'DELETE' })
export const testProvider = (id: number) =>
  request<{ ok: boolean; domains?: string[]; error?: string }>(`/providers/${id}/test`, { method: 'POST' })
export const importDefaults = () =>
  request<{ imported: number }>('/providers/import-defaults', { method: 'POST' })

// Proxies
export const getProxies = () => request<Proxy[]>('/proxies')
export const addProxy = (data: Partial<Proxy>) =>
  request<Proxy>('/proxies', { method: 'POST', body: JSON.stringify(data) })
export const batchAddProxies = (proxies: string[], proxyType = 'http') =>
  request<{ added: number }>('/proxies/batch', {
    method: 'POST',
    body: JSON.stringify({ proxies, proxy_type: proxyType }),
  })
export const updateProxy = (id: number, data: Partial<Proxy>) =>
  request<Proxy>(`/proxies/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteProxy = (id: number) =>
  request(`/proxies/${id}`, { method: 'DELETE' })
export const batchDeleteProxies = (ids: number[]) =>
  request<{ deleted: number }>('/proxies/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  })
export const testProxy = (id: number) =>
  request<{ ok: boolean; ms?: number; info?: string; error?: string }>(`/proxies/${id}/test`, { method: 'POST' })
export const batchTestProxies = () =>
  request<{ message: string; testing: number }>('/proxies/batch-test', { method: 'POST' })

// Settings
export const getSettings = () => request<Settings>('/settings')
export const updateSettings = (data: Partial<Settings>) =>
  request<Settings>('/settings', { method: 'PUT', body: JSON.stringify(data) })

// Registration
export const startRegistration = (count: number) =>
  request<{ ok: boolean; message: string }>('/registration/start', { method: 'POST', body: JSON.stringify({ count }) })
export const stopRegistration = () =>
  request('/registration/stop', { method: 'POST' })
export const getRegistrationStatus = () =>
  request<RegStatus>('/registration/status')
