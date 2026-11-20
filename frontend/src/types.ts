export type BacklogStatus = 'unplayed' | 'in_progress' | 'completed' | 'abandoned'

export const BACKLOG_STATUSES: BacklogStatus[] = ['unplayed', 'in_progress', 'completed', 'abandoned']

export interface Ownership {
  storefront: string
  store_product_id: string | null
  playtime_minutes: number
  recent_playtime_minutes: number | null
  last_played_at: string | null
  acquired_at: string | null
  last_synced_at: string | null
}

export interface Game {
  id: number
  title: string
  igdb_id: number | null
  description: string | null
  cover_url: string | null
  cover_filename: string | null
  icon_url: string | null
  logo_url: string | null
  icon_filename: string | null
  logo_filename: string | null
  release_year: number | null
  genres: string[]
  status: BacklogStatus
  notes: string | null
  rating: number | null
  tags: string[]
  created_at: string
  total_playtime_minutes: number
  last_played_at: string | null
  ownerships: Ownership[]
}

export interface GamePatchPayload {
  title?: string
  status?: BacklogStatus
  notes?: string | null
  rating?: number | null
  tags?: string[]
}

export interface GameCreatePayload {
  title: string
  igdb_id?: number | null
  status?: BacklogStatus
  notes?: string | null
  rating?: number | null
  tags?: string[]
}

export interface Session {
  id: number
  game_id: number
  started_at: string
  ended_at: string
  source: string
}

export interface SyncStatus {
  storefront: string
  last_run_at: string | null
  success: boolean | null
  error: string | null
  items_synced: number | null
}

export interface RecentlyPlayed {
  game_id: number
  title: string
  cover_url: string | null
  storefront: string | null
  last_played_at: string
  recent_playtime_minutes: number | null
  total_playtime_minutes: number
}

export interface IgdbSearchResult {
  igdb_id: number
  title: string
  release_year: number | null
  summary: string | null
  cover_url: string | null
}

export interface GameFilters {
  search: string
  storefront: string
  status: string
  tag: string
}

export interface Meta {
  steam_configured: boolean
  igdb_configured: boolean
  steamgriddb_configured: boolean
}

export type AssetKind = 'cover' | 'icon' | 'logo'
