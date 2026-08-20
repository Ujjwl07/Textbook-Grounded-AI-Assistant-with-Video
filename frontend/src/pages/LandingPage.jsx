import React from 'react'
import { useNavigate } from 'react-router-dom'

export default function LandingPage() {
  const nav = useNavigate()
  return (
    <div className="flex flex-col items-center justify-center text-center" style={{ minHeight: '80vh' }}>
      <h1 className="hero-title animate-float">
        Textbook-Grounded <br/>
        <span className="hero-highlight">AI Video Assistant</span>
      </h1>
      <p className="hero-subtitle mt-4">
        Instantly transform dense NCERT textbook chapters into beautiful, bite-sized microlearning videos tailored for NEET preparation.
      </p>
      
      <div className="glass-panel mt-8" style={{ display: 'inline-block', maxWidth: '600px' }}>
        <h3 style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem', fontWeight: 600 }}>Get Started</h3>
        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'center' }}>
          <button onClick={() => nav('/search')} className="btn-primary">
            Search Topics
          </button>
          <button onClick={() => nav('/dashboard')} className="btn-secondary">
            View My Progress
          </button>
        </div>
      </div>
    </div>
  )
}
