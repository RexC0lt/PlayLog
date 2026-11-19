import { useEffect, useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { SyncStatus } from '../types'
import { relativeTime } from '../utils'

export default function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const [steamStatus, setSteamStatus] = useState<SyncStatus | null>(null)
  const [syncing, setSyncing] = useState(false)

  const refreshStatus = () => {
    api
      .syncStatus()
      .then((rows) => setSteamStatus(rows.find((r) => r.storefront === 'steam') ?? null))
      .catch(() => {})
  }

  useEffect(refreshStatus, [])

  const onSync = async () => {
    setSyncing(true)
    try {
      await api.syncSteam()
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Sync failed')
    } finally {
      setSyncing(false)
      refreshStatus()
    }
  }

  const onLogout = async () => {
    await api.logout().catch(() => {})
    navigate('/login')
  }

  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          🎮 PlayLog
        </Link>
        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Library
          </NavLink>
          <NavLink to="/add" className={({ isActive }) => (isActive ? 'active' : '')}>
            Add game
          </NavLink>
        </nav>
        <div className="topbar-right">
          {steamStatus && (
            <span
              className={`sync-dot ${steamStatus.success === true ? 'ok' : steamStatus.success === false ? 'err' : 'idle'}`}
              title={
                steamStatus.success === null
                  ? 'Steam sync never run'
                  : `${steamStatus.success ? 'Last sync OK' : 'Last sync failed'}: ${relativeTime(steamStatus.last_run_at)}${
                      steamStatus.error ? `\n${steamStatus.error}` : ''
                    }`
              }
            >
              {steamStatus.success === true ? '✓' : steamStatus.success === false ? '✗' : '·'} steam{' '}
              {steamStatus.last_run_at ? relativeTime(steamStatus.last_run_at) : ''}
            </span>
          )}
          <button className="btn small" onClick={onSync} disabled={syncing}>
            {syncing ? 'Syncing…' : 'Sync Steam'}
          </button>
          <button className="btn small ghost" onClick={onLogout}>
            Log out
          </button>
        </div>
      </header>
      <main className="content">{children}</main>
    </div>
  )
}
