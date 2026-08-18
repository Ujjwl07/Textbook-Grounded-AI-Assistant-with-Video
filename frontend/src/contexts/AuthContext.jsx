import React, { createContext, useContext, useEffect, useState } from 'react'
import api, { login as apiLogin, register as apiRegister } from '../services/api'
import { useNavigate } from 'react-router-dom'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    async function fetchMe() {
      const token = localStorage.getItem('access_token')
      if (!token) {
        setLoading(false)
        return
      }
      try {
        const res = await api.get('/auth/me')
        setUser(res.data)
      } catch (e) {
        localStorage.removeItem('access_token')
        setUser(null)
      } finally {
        setLoading(false)
      }
    }
    fetchMe()
  }, [])

  const login = async (email, password) => {
    const res = await apiLogin(email, password)
    const token = res.data.access_token
    localStorage.setItem('access_token', token)
    setUser(res.data.user)
    return res.data
  }

  const register = async (name, email, password) => {
    const res = await apiRegister(name, email, password)
    const token = res.data.access_token
    localStorage.setItem('access_token', token)
    setUser(res.data.user)
    return res.data
  }

  const logout = () => {
    localStorage.removeItem('access_token')
    setUser(null)
    navigate('/')
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}

export default AuthContext
