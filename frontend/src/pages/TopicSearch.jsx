import React, { useState } from 'react'
import { generateVideo } from '../services/api'
import { useNavigate } from 'react-router-dom'

const SUBJECTS = [
  { value: 'physics', label: 'Physics', color: '#818cf8', icon: '⚛️' },
  { value: 'biology', label: 'Biology', color: '#34d399', icon: '🧬' },
  { value: 'chemistry', label: 'Chemistry', color: '#fbbf24', icon: '🧪' },
]

const CLASS_LEVELS = [
  { value: '11', label: 'Class 11' },
  { value: '12', label: 'Class 12' },
]

export default function TopicSearch() {
  const [topic, setTopic] = useState('')
  const [subject, setSubject] = useState('physics')
  const [classLevel, setClassLevel] = useState('11')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const nav = useNavigate()

  async function onGenerate() {
    if (!topic.trim()) return
    setLoading(true)
    setError(null)
    try {
      const res = await generateVideo({ topic: topic.trim(), subject, class_level: classLevel })
      nav(`/generate/${res.data.job_id}`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start generation')
      setLoading(false)
    }
  }

  const activeSub = SUBJECTS.find((s) => s.value === subject)

  return (
    <div className="search-page">
      <div className="search-hero">
        <h1 className="search-title">
          <span style={{ fontSize: '2rem', display: 'block', marginBottom: '0.25rem' }}>🔍</span>
          Generate a <span className="hero-highlight">Video Lesson</span>
        </h1>
        <p className="search-subtitle">
          Enter any NCERT topic and we'll create a personalized microlearning video grounded in your textbook.
        </p>
      </div>

      <div className="search-card glass-panel">
        {/* Subject selector */}
        <label className="input-label">Subject</label>
        <div className="search-subjects">
          {SUBJECTS.map((s) => (
            <button
              key={s.value}
              className={`search-subject-btn ${subject === s.value ? 'active' : ''}`}
              onClick={() => setSubject(s.value)}
              style={subject === s.value ? { borderColor: s.color, background: `${s.color}18` } : {}}
            >
              <span className="search-subject-icon">{s.icon}</span>
              <span>{s.label}</span>
            </button>
          ))}
        </div>

        {/* Class selector */}
        <label className="input-label" style={{ marginTop: '1.5rem' }}>Class Level</label>
        <div className="search-classes">
          {CLASS_LEVELS.map((c) => (
            <button
              key={c.value}
              className={`search-class-btn ${classLevel === c.value ? 'active' : ''}`}
              onClick={() => setClassLevel(c.value)}
            >
              {c.label}
            </button>
          ))}
        </div>

        {/* Topic input */}
        <label className="input-label" style={{ marginTop: '1.5rem' }}>Topic</label>
        <div className="search-input-row">
          <input
            className="input-field"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder={`e.g. ${subject === 'physics' ? "Newton's Laws of Motion" : subject === 'biology' ? 'Photosynthesis' : 'Chemical Bonding'}`}
            onKeyDown={(e) => e.key === 'Enter' && onGenerate()}
            style={{ marginBottom: 0 }}
          />
        </div>

        {error && (
          <div className="search-error">
            <span>⚠️</span> {error}
          </div>
        )}

        <button
          className="btn-primary"
          onClick={onGenerate}
          disabled={!topic.trim() || loading}
          style={{ width: '100%', marginTop: '1.5rem', padding: '1rem' }}
        >
          {loading ? (
            <span className="search-loading">Generating...</span>
          ) : (
            <>Generate Video for {activeSub?.label}</>
          )}
        </button>
      </div>
    </div>
  )
}
