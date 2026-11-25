import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function ProtectedRoute({ children, adminOnly }) {
  const { user, loading, error, isSignedIn, refresh } = useAuth()
  const location = useLocation()
  if (loading) return <div className="page-loading" role="status">Loading your account…</div>
  if (!isSignedIn) {
    // Come back here after signing in.
    const back = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?redirect_url=${back}`} replace />
  }
  if (!user) {
    // Signed in with Clerk, but the API couldn't load/create the app user.
    return (
      <div className="glass-panel" style={{ maxWidth: 520, margin: '2rem auto' }}>
        <h2>Couldn't load your account</h2>
        <p style={{ color: 'var(--text-secondary)', marginTop: '0.5rem' }}>{error}</p>
        <button type="button" className="btn-primary" style={{ marginTop: '1.5rem' }} onClick={refresh}>
          Try again
        </button>
      </div>
    )
  }
  if (adminOnly && !user.is_admin) return <Navigate to="/dashboard" replace />
  return children
}
