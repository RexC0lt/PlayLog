import { Link } from 'react-router-dom'
import type { Game } from '../types'
import { formatPlaytime, statusLabel } from '../utils'

export default function GameCard({ game }: { game: Game }) {
  return (
    <Link to={`/games/${game.id}`} className="card">
      <div className="cover">
        {game.cover_url ? (
          <img src={game.cover_url} alt={game.title} loading="lazy" />
        ) : (
          <div className="cover-placeholder">{game.title.charAt(0).toUpperCase()}</div>
        )}
        <span className={`status-chip status-${game.status}`}>{statusLabel(game.status)}</span>
      </div>
      <div className="card-body">
        <div className="card-title-row">
          {game.icon_url && <img className="card-icon-inline" src={game.icon_url} alt="" loading="lazy" />}
          <div className="card-title" title={game.title}>
            {game.title}
          </div>
        </div>
        <div className="badges">
          {game.ownerships.map((o) => (
            <span key={o.storefront} className={`badge badge-${o.storefront}`}>
              {o.storefront}
            </span>
          ))}
        </div>
        <div className="playtime">{formatPlaytime(game.total_playtime_minutes)} played</div>
      </div>
    </Link>
  )
}
