import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { api } from './api'
import Layout from './components/Layout'
import Login from './views/Login'
import Dashboard from './views/Dashboard'
import GameDetail from './views/GameDetail'
import AddGame from './views/AddGame'

function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<'loading' | 'in' | 'out'>('loading')
  useEffect(() => {
    api
      .me()
      .then(() => setState('in'))
      .catch(() => setState('out'))
  }, [])
  if (state === 'loading') return <div className="loading-screen">Loading…</div>
  if (state === 'out') return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <AuthGate>
              <Layout>
                <Dashboard />
              </Layout>
            </AuthGate>
          }
        />
        <Route
          path="/games/:id"
          element={
            <AuthGate>
              <Layout>
                <GameDetail />
              </Layout>
            </AuthGate>
          }
        />
        <Route
          path="/add"
          element={
            <AuthGate>
              <Layout>
                <AddGame />
              </Layout>
            </AuthGate>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
