import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { useAuth as useClerkAuth, useClerk } from '@clerk/react'
import api from '../services/api'

// Clerk handles sign-in. This context adds the app's own user record from
// GET /auth/me (id used by quizzes/dashboard, is_admin, etc.), keeping the same
// { user, loading, logout } shape the pages already use.
const AuthContext = createContext(null)
const RETRY_DELAYS_MS = [1000, 2000, 4000]

export function AuthProvider({ children }) {
  const { isLoaded, isSignedIn, userId } = useClerkAuth()
  const { signOut } = useClerk()
  const [user, setUser] = useState(null)
  const [userLoading, setUserLoading] = useState(false)
  const [error, setError] = useState(null)

  // Bumped by refresh() to re-run the fetch (e.g. the "Try again" button).
  const [attempt, setAttempt] = useState(0)
  const refresh = useCallback(() => setAttempt((n) => n + 1), [])

  useEffect(() => {
    if (!isLoaded) return
    if (!isSignedIn) {
      setUser(null)
      setError(null)
      return
    }
    let cancelled = false
    let retryTimer = null
    setUserLoading(true)
    setError(null)

    // Retry a few times when the server can't be reached (e.g. the API is
    // restarting); auth/permission errors fail straight away.
    const load = (tries) => {
      api
        .get('/auth/me')
        .then((res) => {
          if (cancelled) return
          setUser(res.data)
          setError(null)
          setUserLoading(false)
        })
        .catch((err) => {
          if (cancelled) return
          const unreachable = !err.response || err.response.status >= 500
          if (unreachable && tries < RETRY_DELAYS_MS.length) {
            retryTimer = setTimeout(() => load(tries + 1), RETRY_DELAYS_MS[tries])
            return
          }
          setUser(null)
          setError(
            !err.response
              ? "The TextbookAI server isn't responding. Make sure the backend is running, then try again."
              : err.response.data?.detail || 'Could not load your account from the server'
          )
          setUserLoading(false)
        })
    }
    load(0)

    return () => {
      cancelled = true
      clearTimeout(retryTimer)
    }
  }, [isLoaded, isSignedIn, userId, attempt])

  const logout = () => signOut({ redirectUrl: '/' })

  const loading = !isLoaded || (isSignedIn && !user && !error) || userLoading

  return (
    <AuthContext.Provider value={{ user, loading, error, isSignedIn: !!isSignedIn, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}

export default AuthContext
