import React, { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { API_BASE_URL, getVideo } from '../services/api'

export default function VideoPlayer() {
  const { jobId } = useParams()
  const [video, setVideo] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getVideo(jobId)
      .then((r) => {
        setVideo(r.data)
        setError(null)
      })
      .catch((err) => {
        setVideo(null)
        setError(err.response?.data?.detail || 'Unable to load video')
      })
  }, [jobId])

  if (error) {
    return (
      <div className="player-page">
        <div className="glass-panel player-error">
          <span style={{ fontSize: '3rem' }}>😔</span>
          <h2 style={{ marginTop: '1rem' }}>Video Unavailable</h2>
          <p style={{ color: 'var(--text-secondary)', marginTop: '0.5rem' }}>{error}</p>
          <Link to="/search" className="btn-primary" style={{ marginTop: '1.5rem', textDecoration: 'none' }}>
            ← Back to Search
          </Link>
        </div>
      </div>
    )
  }

  if (!video) {
    return (
      <div className="player-page">
        <div className="gen-loading glass-panel">
          <div className="gen-spinner" />
          <p style={{ color: 'var(--text-secondary)', marginTop: '1rem' }}>Loading video...</p>
        </div>
      </div>
    )
  }

  const videoUrl = buildPlayableUrl(video.video_url)

  return (
    <div className="player-page">
      {/* Video info header */}
      <div className="player-header">
        <h1 className="player-title">{video.topic || 'Video Lesson'}</h1>
        <div className="player-meta">
          {video.subject && (
            <span className="player-badge" style={{ background: getSubjectColor(video.subject) }}>
              {video.subject.charAt(0).toUpperCase() + video.subject.slice(1)}
            </span>
          )}
          {video.class_level && (
            <span className="player-badge" style={{ background: 'rgba(255,255,255,0.1)' }}>
              Class {video.class_level}
            </span>
          )}
        </div>
      </div>

      {/* Video container */}
      <div className="player-video-wrap glass-panel" style={{ padding: 0, overflow: 'hidden' }}>
        <video controls width="100%" src={videoUrl} style={{ display: 'block', borderRadius: 'var(--radius-lg)' }}>
          Your browser does not support the video tag.
        </video>
      </div>

      {/* Actions */}
      <div className="player-actions">
        <a href={videoUrl} target="_blank" rel="noreferrer" className="btn-secondary" style={{ textDecoration: 'none' }}>
          🔗 Open in New Tab
        </a>
        <Link to="/search" className="btn-secondary" style={{ textDecoration: 'none' }}>
          ← Generate Another
        </Link>
      </div>
    </div>
  )
}

function getSubjectColor(subject) {
  switch ((subject || '').toLowerCase()) {
    case 'physics': return '#818cf8'
    case 'biology': return '#34d399'
    case 'chemistry': return '#fbbf24'
    default: return '#94a3b8'
  }
}

function buildPlayableUrl(rawUrl) {
  if (!rawUrl) return ''
  if (/^https?:\/\//i.test(rawUrl)) return rawUrl

  const apiOrigin = new URL(API_BASE_URL).origin
  const url = `${apiOrigin}${rawUrl}`
  const token = localStorage.getItem('access_token')
  if (!token || !rawUrl.startsWith('/api/video-file/')) return url

  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}token=${encodeURIComponent(token)}`
}
