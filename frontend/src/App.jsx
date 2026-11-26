import React, { useCallback, useEffect, useState } from 'react'
import { Routes, Route, Link, NavLink, useLocation } from 'react-router-dom'
import { Show, UserButton, useUser } from '@clerk/react'
import LandingPage from './pages/LandingPage'
import TopicSearch from './pages/TopicSearch'
import VideoGeneration from './pages/VideoGeneration'
import VideoPlayer from './pages/VideoPlayer'
import QuizPage from './pages/QuizPage'
import Dashboard from './pages/Dashboard'
import AdminPanel from './pages/AdminPanel'
import Login from './pages/Login'
import Register from './pages/Register'
import { useAuth } from './contexts/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import LogoLockup from './components/LogoLockup'
import HeaderSearch from './components/HeaderSearch'
import { useTheme } from './contexts/ThemeContext'

const SearchIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3.6-3.6" />
  </svg>
)

const ThemeIcon = ({ dark }) => (
  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    {dark ? (
      // Sun: click to go light
      <>
        <circle cx="12" cy="12" r="4.2" />
        <path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6" />
      </>
    ) : (
      // Moon: click to go dark
      <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
    )}
  </svg>
)

const FlameIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="currentColor">
    <path d="M12 2c.6 3.2-1 5-2.6 6.8C7.8 10.6 6 12.4 6 15.2 6 18.9 8.7 22 12 22s6-3 6-6.6c0-2.6-1.3-4.3-2.6-5.6.1 1.6-.5 2.9-1.7 3.4.4-3.9-.9-8.6-1.7-11.2z" />
  </svg>
)

export default function App() {
  const { user } = useAuth()
  const { user: clerkUser } = useUser()
  const { theme, toggleTheme } = useTheme()
  const [menuOpen, setMenuOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const location = useLocation()
  const closeSearch = useCallback(() => setSearchOpen(false), [])

  // Close the mobile menu and search panel whenever the page changes.
  useEffect(() => {
    setMenuOpen(false)
    setSearchOpen(false)
  }, [location.pathname, location.search])

  const firstName = (user?.name || clerkUser?.firstName || clerkUser?.username || '').split(' ')[0]
  const streak = user?.streak_days || 0
  const isDark = theme === 'dark'

  return (
    <div>
      <header className="navbar">
        <Link to="/" className="brand" aria-label="TextbookAI home">
          <LogoLockup className="brand-lockup" />
        </Link>

        <nav id="primary-nav" aria-label="Main" className={`nav-links${menuOpen ? ' open' : ''}`}>
          <div className="nav-pills">
            <NavLink to="/" end className="nav-pill">Home</NavLink>
            <NavLink to="/search" className="nav-pill">Search</NavLink>
            <NavLink to="/quiz" className="nav-pill">Quiz</NavLink>
            <NavLink to="/dashboard" className="nav-pill">Dashboard</NavLink>
            {user?.is_admin && <NavLink to="/admin" className="nav-pill">Admin</NavLink>}
          </div>
          <Show when="signed-out">
            <div className="nav-auth nav-auth-menu">
              <NavLink to="/login" className="nav-pill">Sign in</NavLink>
              <Link to="/register" className="nav-signup">Sign up</Link>
            </div>
          </Show>
        </nav>

        <div className="nav-actions">
          <button
            type="button"
            className={`nav-icon-btn nav-search-btn${searchOpen ? ' active' : ''}`}
            aria-label="Search topics"
            aria-expanded={searchOpen}
            aria-controls="header-search"
            onClick={() => setSearchOpen((o) => !o)}
          >
            <SearchIcon />
          </button>
          <button
            type="button"
            className="nav-icon-btn"
            aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            title={isDark ? 'Light mode' : 'Dark mode'}
            onClick={toggleTheme}
          >
            <ThemeIcon dark={isDark} />
          </button>

          <Show when="signed-in">
            {streak > 0 && (
              <div className="nav-streak" title={`You've opened TextbookAI ${streak} day${streak === 1 ? '' : 's'} in a row`}>
                <FlameIcon />
                <span className="nav-streak-text">
                  <strong>{streak}-day</strong> streak
                </span>
              </div>
            )}
            <div className="nav-user-chip">
              {firstName && (
                <span className="nav-hello">
                  Hello,<strong>{firstName}</strong>
                </span>
              )}
              <UserButton />
            </div>
          </Show>

          <Show when="signed-out">
            <div className="nav-auth nav-auth-bar">
              <NavLink to="/login" className="nav-pill">Sign in</NavLink>
              <Link to="/register" className="nav-signup">Sign up</Link>
            </div>
          </Show>

          <button
            type="button"
            className="nav-toggle"
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={menuOpen}
            aria-controls="primary-nav"
            onClick={() => setMenuOpen((o) => !o)}
          >
            <span className="nav-toggle-bars" />
          </button>
        </div>

        {searchOpen && <HeaderSearch onClose={closeSearch} />}
      </header>
      <main className={location.pathname === '/' || /^\/(login|register|generate)/.test(location.pathname) ? 'container-full' : 'container'}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/search" element={<ProtectedRoute><TopicSearch /></ProtectedRoute>} />
          <Route path="/generate/:jobId" element={<ProtectedRoute><VideoGeneration /></ProtectedRoute>} />
          <Route path="/watch/:jobId" element={<ProtectedRoute><VideoPlayer /></ProtectedRoute>} />
          <Route path="/quiz/:jobId" element={<ProtectedRoute><QuizPage /></ProtectedRoute>} />
          <Route path="/quiz" element={<ProtectedRoute><QuizPage /></ProtectedRoute>} />
          <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/admin" element={<ProtectedRoute adminOnly={true}><AdminPanel /></ProtectedRoute>} />
          <Route path="/login/*" element={<Login />} />
          <Route path="/register/*" element={<Register />} />
        </Routes>
      </main>
    </div>
  )
}
