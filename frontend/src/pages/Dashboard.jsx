import React, { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { getDashboard, listVideos } from '../services/api'
import { Link } from 'react-router-dom'

const STATUS_STYLES = {
  completed: { color: '#34d399', label: 'Completed', icon: '✅' },
  running: { color: '#fbbf24', label: 'Running', icon: '⏳' },
  queued: { color: '#818cf8', label: 'Queued', icon: '🔜' },
  failed: { color: '#f87171', label: 'Failed', icon: '❌' },
}

function getSubjectColor(subject) {
  switch ((subject || '').toLowerCase()) {
    case 'physics': return '#818cf8'
    case 'biology': return '#34d399'
    case 'chemistry': return '#fbbf24'
    default: return '#94a3b8'
  }
}

export default function Dashboard() {
  const { user } = useAuth()
  const [data, setData] = useState(null)
  const [videos, setVideos] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!user) return
    Promise.all([getDashboard(user.id), listVideos()])
      .then(([dashboardRes, videosRes]) => {
        setData(dashboardRes.data)
        setVideos(videosRes.data.videos || [])
        setError(null)
      })
      .catch((err) => { setError(err.response?.data?.detail || err.message); setData(null) })
  }, [user])

  return (
    <div className="dash-page">
      <div className="dash-header">
        <h1 className="dash-title">
          Welcome back, <span className="hero-highlight">{user?.name || 'Student'}</span>
        </h1>
        <p className="dash-subtitle">Your learning progress at a glance</p>
      </div>

      {error && (
        <div className="dash-error glass-panel">
          <span>⚠️</span> {error}
        </div>
      )}

      {/* Stats cards */}
      <div className="dash-stats">
        <div className="dash-stat glass-panel">
          <div className="dash-stat-icon">🎬</div>
          <div className="dash-stat-value">{videos.length}</div>
          <div className="dash-stat-label">Total Videos</div>
        </div>
        <div className="dash-stat glass-panel">
          <div className="dash-stat-icon">✅</div>
          <div className="dash-stat-value">{videos.filter((v) => v.status === 'completed').length}</div>
          <div className="dash-stat-label">Completed</div>
        </div>
        <div className="dash-stat glass-panel">
          <div className="dash-stat-icon">📊</div>
          <div className="dash-stat-value">{data?.ability != null ? data.ability.toFixed(1) : '—'}</div>
          <div className="dash-stat-label">Ability Score</div>
        </div>
      </div>

      {/* Topic mastery */}
      {data?.topic_mastery && Object.keys(data.topic_mastery).length > 0 && (
        <div className="dash-section">
          <h2 className="dash-section-title">📈 Topic Mastery</h2>
          <div className="dash-mastery-grid">
            {Object.entries(data.topic_mastery).map(([topic, val]) => (
              <div key={topic} className="dash-mastery-item glass-panel">
                <span className="dash-mastery-topic">{topic}</span>
                <div className="dash-mastery-bar-track">
                  <div
                    className="dash-mastery-bar-fill"
                    style={{ width: `${Math.min(val * 100, 100)}%` }}
                  />
                </div>
                <span className="dash-mastery-pct">{Math.round(val * 100)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Video list */}
      <div className="dash-section">
        <h2 className="dash-section-title">🎬 Your Videos</h2>
        {videos.length === 0 ? (
          <div className="dash-empty glass-panel">
            <span style={{ fontSize: '3rem' }}>📹</span>
            <p style={{ marginTop: '1rem', color: 'var(--text-secondary)' }}>No videos yet. Start by searching a topic!</p>
            <Link to="/search" className="btn-primary" style={{ marginTop: '1rem', textDecoration: 'none' }}>
              Search Topics
            </Link>
          </div>
        ) : (
          <div className="dash-video-list">
            {videos.map((video) => {
              const st = STATUS_STYLES[video.status] || STATUS_STYLES.queued
              return (
                <div key={video.job_id} className="dash-video-row glass-panel">
                  <div className="dash-video-info">
                    <span className="dash-video-subject" style={{ background: getSubjectColor(video.subject) }}>
                      {(video.subject || 'General').charAt(0).toUpperCase() + (video.subject || 'general').slice(1)}
                    </span>
                    <span className="dash-video-topic">{video.topic || 'Untitled'}</span>
                  </div>
                  <div className="dash-video-actions">
                    <span className="dash-video-status" style={{ color: st.color }}>{st.icon} {st.label}</span>
                    {video.status === 'completed' && (
                      <Link to={`/watch/${video.job_id}`} className="btn-secondary" style={{ padding: '0.3rem 1rem', fontSize: '0.85rem', textDecoration: 'none' }}>
                        ▶ Watch
                      </Link>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
