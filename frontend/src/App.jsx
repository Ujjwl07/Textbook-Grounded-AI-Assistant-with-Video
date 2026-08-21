import React from 'react'
import { Routes, Route, Link } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import TopicSearch from './pages/TopicSearch'
import VideoGeneration from './pages/VideoGeneration'
import VideoPlayer from './pages/VideoPlayer'
import QuizSession from './pages/QuizSession'
import QuizPage from './pages/QuizPage'
import Dashboard from './pages/Dashboard'
import AdminPanel from './pages/AdminPanel'
import Login from './pages/Login'
import Register from './pages/Register'
import { useAuth } from './contexts/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'

export default function App() {
  const { user, logout } = useAuth()
  return (
    <div>
      <nav className="navbar">
        <Link to="/" style={{ textDecoration: 'none' }}>
          <div style={{ fontWeight: 800, fontSize: '1.25rem', color: '#fff' }}>Textbook<span style={{ color: 'var(--accent-primary)' }}>AI</span></div>
        </Link>
        <div className="nav-links">
          <Link to="/" className="nav-link">Home</Link>
          <Link to="/search" className="nav-link">Search</Link>
          <Link to="/dashboard" className="nav-link">Dashboard</Link>
          <Link to="/quiz" className="nav-link">Quiz</Link>
          {user?.is_admin && <Link to="/admin" className="nav-link">Admin</Link>}
          {user ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginLeft: '1rem' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Hello, {user.name}</span>
              <button onClick={logout} className="btn-secondary" style={{ padding: '0.4rem 1rem', fontSize: '0.85rem' }}>Logout</button>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginLeft: '1rem' }}>
              <Link to="/login" className="nav-link">Login</Link>
              <Link to="/register" className="btn-primary" style={{ padding: '0.4rem 1.2rem', textDecoration: 'none' }}>Register</Link>
            </div>
          )}
        </div>
      </nav>
      <main className="container">
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/search" element={<ProtectedRoute><TopicSearch /></ProtectedRoute>} />
          <Route path="/generate/:jobId" element={<ProtectedRoute><VideoGeneration /></ProtectedRoute>} />
          <Route path="/watch/:jobId" element={<ProtectedRoute><VideoPlayer /></ProtectedRoute>} />
          <Route path="/quiz/:videoId" element={<ProtectedRoute><QuizSession /></ProtectedRoute>} />
          <Route path="/quiz" element={<QuizPage />} />
          <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/admin" element={<ProtectedRoute adminOnly={true}><AdminPanel /></ProtectedRoute>} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
        </Routes>
      </main>
    </div>
  )
}
