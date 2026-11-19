import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import type { BacklogStatus, Game, Session } from '../types'
import { BACKLOG_STATUSES } from '../types'
import { formatDateTime, formatPlaytime, statusLabel } from '../utils'

export default function GameDetail() {
  const { id } = useParams<{ id: string }>()
  const gameId = Number(id)
  const [game, setGame] = useState<Game | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  // editable fields
  const [status, setStatus] = useState<BacklogStatus>('unplayed')
  const [rating, setRating] = useState<string>('')
  const [tags, setTags] = useState('')
  const [notes, setNotes] = useState('')

  // manual session form
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')

  const load = async () => {
    try {
      const g = await api.game(gameId)
      setGame(g)
      setStatus(g.status)
      setRating(g.rating === null ? '' : String(g.rating))
      setTags(g.tags.join(', '))
      setNotes(g.notes ?? '')
      setSessions(await api.sessions(gameId))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load game')
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameId])

  const save = async () => {
    setSaved(false)
    const payload: Parameters<typeof api.patchGame>[1] = {
      status,
      notes: notes.trim() === '' ? null : notes,
      rating: rating === '' ? null : Number(rating),
      tags: tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
    }
    const updated = await api.patchGame(gameId, payload)
    setGame(updated)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const addSession = async () => {
    if (!start || !end) return
    await api.addSession(gameId, new Date(start).toISOString(), new Date(end).toISOString())
    setStart('')
    setEnd('')
    await load()
  }

  if (error) return <div className="banner error">{error}</div>
  if (!game) return <p className="muted">Loading…</p>

  return (
    <div className="detail">
      <Link to="/" className="back">
        ← Back to library
      </Link>
      <div className="detail-header">
        <div className="detail-cover">
          {game.cover_url ? <img src={game.cover_url} alt={game.title} /> : <div className="cover-placeholder big">{game.title.charAt(0).toUpperCase()}</div>}
        </div>
        <div className="detail-head-info">
          <h1>{game.title}</h1>
          <div className="meta-row">
            {game.release_year && <span>{game.release_year}</span>}
            {game.genres.map((g) => (
              <span key={g} className="chip">
                {g}
              </span>
            ))}
            {game.ownerships.map((o) => (
              <span key={o.storefront} className={`badge badge-${o.storefront}`}>
                {o.storefront}
              </span>
            ))}
          </div>
          <div className="meta-row muted">
            {formatPlaytime(game.total_playtime_minutes)} played
            {game.last_played_at ? ` · last played ${formatDateTime(game.last_played_at)}` : ' · never played'}
          </div>
          {game.description && <p className="description">{game.description}</p>}
        </div>
      </div>

      <section className="panel">
        <h2>My metadata</h2>
        <div className="form-grid">
          <label>
            Backlog status
            <select className="input" value={status} onChange={(e) => setStatus(e.target.value as BacklogStatus)}>
              {BACKLOG_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(s)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Rating (0–10)
            <input
              className="input"
              type="number"
              min={0}
              max={10}
              value={rating}
              onChange={(e) => setRating(e.target.value)}
              placeholder="—"
            />
          </label>
          <label>
            Tags (comma separated)
            <input className="input" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="jrpg, retro, …" />
          </label>
        </div>
        <label className="block">
          Notes
          <textarea className="input" rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Personal notes…" />
        </label>
        <div className="actions">
          <button className="btn primary" onClick={save}>
            Save
          </button>
          {saved && <span className="muted">Saved ✓</span>}
        </div>
        {game.tags.length > 0 && (
          <div className="meta-row">
            {game.tags.map((t) => (
              <span key={t} className="chip tag">
                {t}
              </span>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Ownership</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Storefront</th>
              <th>Product ID</th>
              <th>Playtime</th>
              <th>Last played</th>
              <th>Acquired</th>
              <th>Last synced</th>
            </tr>
          </thead>
          <tbody>
            {game.ownerships.map((o) => (
              <tr key={o.storefront}>
                <td>
                  <span className={`badge badge-${o.storefront}`}>{o.storefront}</span>
                </td>
                <td>{o.store_product_id ?? '—'}</td>
                <td>{formatPlaytime(o.playtime_minutes)}</td>
                <td>{formatDateTime(o.last_played_at)}</td>
                <td>{formatDateTime(o.acquired_at)}</td>
                <td>{formatDateTime(o.last_synced_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h2>Play sessions</h2>
        {sessions.length === 0 && <p className="muted">No sessions recorded yet.</p>}
        {sessions.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Started</th>
                <th>Ended</th>
                <th>Duration</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => {
                const mins = Math.max(0, Math.round((new Date(s.ended_at).getTime() - new Date(s.started_at).getTime()) / 60000))
                return (
                  <tr key={s.id}>
                    <td>{formatDateTime(s.started_at)}</td>
                    <td>{formatDateTime(s.ended_at)}</td>
                    <td>{formatPlaytime(mins)}</td>
                    <td>{s.source}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        <div className="session-form">
          <label>
            Start
            <input type="datetime-local" className="input" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>
            End
            <input type="datetime-local" className="input" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <button className="btn" onClick={addSession} disabled={!start || !end}>
            Log manual session
          </button>
        </div>
      </section>
    </div>
  )
}
