import type {
  AssetKind,
  Game,
  GameCreatePayload,
  GameFilters,
  GamePatchPayload,
  IgdbSearchResult,
  Meta,
  RecentlyPlayed,
  Session,
  SyncStatus,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(detail: string, status: number) {
    super(detail)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
    throw new ApiError('unauthorized', 401)
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body && body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep default detail */
    }
    throw new ApiError(detail, res.status)
  }
  return (await res.json()) as T
}

function queryString(params: Record<string, string>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v) q.set(k, v)
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

export const api = {
  login: (password: string) =>
    request<{ access_token: string; token_type: string; expires_at: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
  me: () => request<{ authenticated: boolean }>('/api/auth/me'),

  games: (filters: GameFilters) =>
    request<Game[]>(
      '/api/games' +
        queryString({
          search: filters.search,
          storefront: filters.storefront,
          status: filters.status,
          tag: filters.tag,
        })
    ),
  game: (id: number) => request<Game>(`/api/games/${id}`),
  createGame: (payload: GameCreatePayload) =>
    request<Game>('/api/games', { method: 'POST', body: JSON.stringify(payload) }),
  patchGame: (id: number, payload: GamePatchPayload) =>
    request<Game>(`/api/games/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  refreshAssets: (id: number) => request<Game>(`/api/games/${id}/assets/refresh`, { method: 'POST' }),
  uploadAsset: async (id: number, kind: AssetKind, file: File) => {
    const res = await fetch(`/api/games/${id}/assets/${kind}`, {
      method: 'PUT',
      credentials: 'include',
      body: file,
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
    })
    if (res.status === 401) window.location.href = '/login'
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try { detail = (await res.json()).detail ?? detail } catch { /* ignore */ }
      throw new ApiError(detail, res.status)
    }
    return (await res.json()) as Game
  },
  deleteAsset: (id: number, kind: AssetKind) =>
    request<Game>(`/api/games/${id}/assets/${kind}`, { method: 'DELETE' }),
  meta: () => request<Meta>('/api/meta'),
  sessions: (id: number) => request<Session[]>(`/api/games/${id}/sessions`),
  addSession: (id: number, startedAt: string, endedAt: string) =>
    request<Session>(`/api/games/${id}/sessions`, {
      method: 'POST',
      body: JSON.stringify({ started_at: startedAt, ended_at: endedAt }),
    }),

  syncStatus: () => request<SyncStatus[]>('/api/sync/status'),
  syncSteam: () => request<SyncStatus>('/api/sync/steam', { method: 'POST' }),
  recentlyPlayed: () => request<RecentlyPlayed[]>('/api/recently-played'),

  igdbSearch: (q: string) => request<IgdbSearchResult[]>(`/api/igdb/search?q=${encodeURIComponent(q)}`),
}

export const coverUrl = (id: number): string => `/api/games/${id}/cover`
