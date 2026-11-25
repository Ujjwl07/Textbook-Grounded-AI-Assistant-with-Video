import React, { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import useWebSocket from '../hooks/useWebSocket'
import { getStatus } from '../services/api'

const STAGE_META = {
  initializing: { icon: '⚙️', color: '#0071E3' },
  retrieving: { icon: '📚', color: '#0066CC' },
  scripting: { icon: '✍️', color: '#5E5CE6' },
  segmenting: { icon: '🧩', color: '#8944AB' },
  audio: { icon: '🔊', color: '#C2185B' },
  rendering: { icon: '🎬', color: '#C93400' },
  uploading: { icon: '☁️', color: '#248A3D' },
  complete: { icon: '✅', color: '#248A3D' },
  failed: { icon: '❌', color: '#D70015' },
  topic_not_found: { icon: '🔍', color: '#B25E00' },
}

export default function VideoGeneration() {
  const { jobId } = useParams()
  const [status, setStatus] = useState(null)

  // fallback initial fetch
  useEffect(() => {
    let mounted = true
    async function fetch() {
      try {
        const res = await getStatus(jobId)
        if (!mounted) return
        setStatus(res.data)
      } catch (e) {}
    }
    fetch()
    return () => (mounted = false)
  }, [jobId])

  // subscribe to websocket updates
  useWebSocket(`/ws/${jobId}`, (data) => {
    if (!data) return
    // server may send full JobState or partial updates
    setStatus((prev) => ({ ...(prev || {}), ...data }))
  })

  if (!status) {
    return (
      <div className="gen-page">
        <div className="gen-loading glass-panel">
          <div className="gen-spinner" />
          <p style={{ color: 'var(--text-secondary)', marginTop: '1rem' }}>Connecting to server...</p>
        </div>
      </div>
    )
  }

  const stage = status.stage || 'initializing'
  const progress = status.progress || 0
  const meta = STAGE_META[stage] || STAGE_META.initializing
  const isComplete = status.status === 'completed'
  const isFailed = status.status === 'failed'

  return (
    <div className="gen-page">
      <div className="gen-card glass-panel">
        <h2 className="gen-title">
          {isComplete ? '🎉 Video Ready!' : isFailed ? '⚠️ Generation Failed' : '🎬 Generating Your Video'}
        </h2>

        {status.topic && (
          <p className="gen-topic">Topic: <strong>{status.topic}</strong></p>
        )}

        {/* Progress ring */}
        <div className="gen-ring-wrap">
          <svg viewBox="0 0 120 120" width="160" height="160">
            <circle cx="60" cy="60" r="52" fill="none" style={{ stroke: 'var(--ink-12)' }} strokeWidth="8" />
            <circle
              cx="60" cy="60" r="52" fill="none"
              stroke={meta.color}
              strokeWidth="8" strokeLinecap="round"
              strokeDasharray={`${(progress / 100) * 326.7} 326.7`}
              style={{ transform: 'rotate(-90deg)', transformOrigin: 'center', transition: 'stroke-dasharray 0.6s ease, stroke 0.4s ease' }}
            />
          </svg>
          <div className="gen-ring-label">
            <span className="gen-ring-pct" style={{ color: meta.color }}>{progress}%</span>
            <span className="gen-ring-icon">{meta.icon}</span>
          </div>
        </div>

        {/* Stage label */}
        <div className="gen-stage-label" style={{ color: meta.color }}>
          {stage.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
        </div>
        {status.message && (
          <p className="gen-message">{status.message}</p>
        )}

        {/* Error display */}
        {isFailed && status.error && (
          <div className="gen-error">
            <p>{status.error}</p>
          </div>
        )}

        {/* Completion CTA */}
        {isComplete && (
          <Link to={`/watch/${jobId}`} className="btn-primary" style={{ display: 'inline-block', marginTop: '2rem', textDecoration: 'none', textAlign: 'center', width: '100%' }}>
            ▶ Watch Video
          </Link>
        )}
      </div>
    </div>
  )
}
