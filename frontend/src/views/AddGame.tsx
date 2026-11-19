import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { IgdbSearchResult } from '../types'

export default function AddGame() {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [results, setResults] = useState<IgdbSearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // debounced IGDB search
  useEffect(() => {
    const q = title.trim()
    if (q.length < 2) {
      setResults(null)
      return
    }
    setSearching(true)
    const t = setTimeout(() => {
      api
        .igdbSearch(q)
        .then((r) => {
          setResults(r)
          setError(null)
        })
        .catch((e) => {
          setResults(null)
          setError(e instanceof Error ? e.message : 'IGDB search failed')
        })
        .finally(() => setSearching(false))
    }, 350)
    return () => clearTimeout(t)
  }, [title])

  const addWithIgdb = async (r: IgdbSearchResult) => {
    setBusy(true)
    try {
      const game = await api.createGame({ title: r.title, igdb_id: r.igdb_id })
      navigate(`/games/${game.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add game')
      setBusy(false)
    }
  }

  const addManual = async () => {
    if (!title.trim()) return
    setBusy(true)
    try {
      const game = await api.createGame({ title: title.trim() })
      navigate(`/games/${game.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add game')
      setBusy(false)
    }
  }

  return (
    <div className="add-game">
      <h1>Add a game</h1>
      <p className="muted">
        Type a title to search IGDB. Pick a match to get cover art, description, genres and release year — or add it as a
        plain manual entry (e.g. DRM-free or retro titles).
      </p>
      <input
        className="input big"
        placeholder="Search IGDB for a title…"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
      />
      {searching && <p className="muted">Searching IGDB…</p>}
      {error && <div className="banner error">{error}</div>}
      {results !== null && results.length === 0 && !searching && <p className="muted">No IGDB matches found.</p>}
      {results && results.length > 0 && (
        <ul className="pick-list">
          {results.map((r) => (
            <li key={r.igdb_id}>
              <button className="pick" onClick={() => addWithIgdb(r)} disabled={busy}>
                {r.cover_url ? <img src={r.cover_url} alt="" /> : <div className="cover-placeholder">{r.title.charAt(0)}</div>}
                <span className="pick-info">
                  <strong>{r.title}</strong>
                  {r.release_year && <span className="muted"> · {r.release_year}</span>}
                  {r.summary && <small className="muted line-clamp">{r.summary}</small>}
                </span>
                <span className="btn small">Add</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="actions">
        <button className="btn primary" onClick={addManual} disabled={busy || !title.trim()}>
          Add “{title.trim() || '…'}” as manual entry (no IGDB)
        </button>
      </div>
    </div>
  )
}
