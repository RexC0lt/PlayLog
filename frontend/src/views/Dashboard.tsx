import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import FilterBar from '../components/FilterBar'
import GameCard from '../components/GameCard'
import RecentlyPlayed from '../components/RecentlyPlayed'
import type { Game, GameFilters, RecentlyPlayed as RP, SyncStatus } from '../types'

const EMPTY_FILTERS: GameFilters = { search: '', storefront: '', status: '', tag: '', genre: '', sort: 'title' }

export default function Dashboard() {
  const [filters, setFilters] = useState<GameFilters>(EMPTY_FILTERS)
  const [debounced, setDebounced] = useState<GameFilters>(EMPTY_FILTERS)
  const [games, setGames] = useState<Game[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [statuses, setStatuses] = useState<SyncStatus[]>([])
  const [recent, setRecent] = useState<RP[]>([])
  const [allGames, setAllGames] = useState<Game[]>([])

  // debounce the text search
  useEffect(() => {
    const t = setTimeout(() => setDebounced(filters), 300)
    return () => clearTimeout(t)
  }, [filters])

  useEffect(() => {
    api
      .games(debounced)
      .then(setGames)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load games'))
  }, [debounced])

  useEffect(() => {
    api.syncStatus().then(setStatuses).catch(() => {})
    api.recentlyPlayed().then(setRecent).catch(() => {})
    // unfiltered list, only to populate the tag/genre filter dropdowns
    api.games(EMPTY_FILTERS).then(setAllGames).catch(() => {})
  }, [])

  const storefronts = useMemo(() => statuses.map((s) => s.storefront), [statuses])
  const allTags = useMemo(() => {
    const set = new Set<string>()
    for (const g of allGames) for (const t of g.tags) set.add(t)
    return [...set].sort()
  }, [allGames])
  const allGenres = useMemo(() => {
    const set = new Set<string>()
    for (const g of allGames) for (const ge of g.genres) set.add(ge)
    return [...set].sort()
  }, [allGames])

  const steamStatus = statuses.find((s) => s.storefront === 'steam')

  return (
    <div>
      <RecentlyPlayed items={recent} />

      {steamStatus?.success === false && (
        <div className="banner error">
          Steam sync failed {steamStatus.last_run_at ? `(${new Date(steamStatus.last_run_at).toLocaleString()})` : ''}:{' '}
          {steamStatus.error}
        </div>
      )}

      <FilterBar filters={filters} storefronts={storefronts} tags={allTags} genres={allGenres} onChange={setFilters} />

      {error && <div className="banner error">{error}</div>}
      {games === null && !error && <p className="muted">Loading library…</p>}
      {games !== null && games.length === 0 && (
        <p className="muted">No games match. Try clearing the filters or add a game manually.</p>
      )}
      <div className="grid">
        {(games ?? []).map((g) => (
          <GameCard key={g.id} game={g} />
        ))}
      </div>
    </div>
  )
}
