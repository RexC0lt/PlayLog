import type { GameFilters } from '../types'
import { BACKLOG_STATUSES, SORT_OPTIONS } from '../types'

interface Props {
  filters: GameFilters
  storefronts: string[]
  tags: string[]
  genres: string[]
  onChange: (f: GameFilters) => void
}

export default function FilterBar({ filters, storefronts, tags, genres, onChange }: Props) {
  const set = (patch: Partial<GameFilters>) => onChange({ ...filters, ...patch })
  return (
    <div className="filterbar">
      <input
        type="search"
        placeholder="Search titles…"
        value={filters.search}
        onChange={(e) => set({ search: e.target.value })}
        className="input search"
      />
      <select value={filters.storefront} onChange={(e) => set({ storefront: e.target.value })} className="input">
        <option value="">All storefronts</option>
        {storefronts.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <select value={filters.status} onChange={(e) => set({ status: e.target.value })} className="input">
        <option value="">All statuses</option>
        {BACKLOG_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s.replace('_', ' ')}
          </option>
        ))}
      </select>
      <select value={filters.tag} onChange={(e) => set({ tag: e.target.value })} className="input">
        <option value="">All tags</option>
        {tags.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <select value={filters.genre} onChange={(e) => set({ genre: e.target.value })} className="input">
        <option value="">All genres</option>
        {genres.map((g) => (
          <option key={g} value={g}>
            {g}
          </option>
        ))}
      </select>
      <select value={filters.sort} onChange={(e) => set({ sort: e.target.value })} className="input" title="Sort by">
        {SORT_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            Sort: {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}
