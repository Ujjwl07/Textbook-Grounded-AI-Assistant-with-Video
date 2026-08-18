import React, { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useNavigate, Link } from 'react-router-dom'

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      await register(name, email, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed')
    }
  }

  return (
    <div className="flex flex-col items-center justify-center mt-8">
      <div className="glass-panel" style={{ width: '100%', maxWidth: '420px' }}>
        <h2 className="text-center" style={{ marginBottom: '1.5rem', fontSize: '1.8rem' }}>Register</h2>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label className="input-label">Name</label>
            <input className="input-field" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div>
            <label className="input-label">Email</label>
            <input className="input-field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <label className="input-label">Password</label>
            <input className="input-field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <div style={{ color: '#ef4444', fontSize: '0.9rem', textAlign: 'center' }}>{error}</div>}
          <button type="submit" className="btn-primary" style={{ width: '100%', marginTop: '0.5rem' }}>Create Account</button>
        </form>
        <p className="text-center mt-4" style={{ color: 'var(--text-secondary)' }}>
          Already have an account? <Link to="/login" style={{ color: 'var(--accent-primary)', textDecoration: 'none', fontWeight: 600 }}>Login</Link>
        </p>
      </div>
    </div>
  )
}
