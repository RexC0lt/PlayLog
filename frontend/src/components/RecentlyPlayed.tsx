import { Link } from 'react-router-dom'
import type { RecentlyPlayed } from '../types'
import { formatPlaytime, relativeTime } from '../utils'

export default function RecentlyPlayed({ items }: { items: RecentlyPlayed[] }) {
  if (items.length === 0) return null
  return (
    <section className="recent">
      <h2>Recently played</h2>
      <div className="recent-strip">
        {items.map((item) => (
          <Link key={item.game_id} to={`/games/${item.game_id}`} className="recent-card">
            <div className="recent-cover">
              {item.cover_url ? (
                <img src={item.cover_url} alt={item.title} loading="lazy" />
              ) : (
                <div className="cover-placeholder">{item.title.charAt(0).toUpperCase()}</div>
              )}
            </div>
            <div className="recent-info">
              <div className="recent-title">{item.title}</div>
              <div className="recent-meta">
                {relativeTime(item.last_played_at)}
                {item.recent_playtime_minutes ? ` · ${formatPlaytime(item.recent_playtime_minutes)} in 2 wks` : ''}
              </div>
              {item.storefront && <span className={`badge badge-${item.storefront}`}>{item.storefront}</span>}
            </div>
          </Link>
        ))}
      </div>
    </section>
  )
}
