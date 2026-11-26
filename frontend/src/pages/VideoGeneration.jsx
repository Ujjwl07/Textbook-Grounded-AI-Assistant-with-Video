import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import useWebSocket from '../hooks/useWebSocket'
import { generateVideo, getStatus } from '../services/api'
import AuthIcons from '../components/AuthIcons'

// The five steps the backend reports (job.step), in order.
const STEPS = [
  {
    key: 'retrieve', label: 'Retrieve', verb: 'Retrieving',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>,
  },
  {
    key: 'script', label: 'Script', verb: 'Scripting',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4h16v16H4z" /><path d="M8 4v16M4 9h4M4 15h4" /></svg>,
  },
  {
    key: 'narrate', label: 'Narrate', verb: 'Narrating',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 12h2l2-6 4 14 3-9 2 3h5" /></svg>,
  },
  {
    key: 'render', label: 'Render', verb: 'Rendering',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="14" rx="2" /><path d="M3 15l5-4 4 3 3-3 6 5" /></svg>,
  },
  {
    key: 'encode', label: 'Encode', verb: 'Encoding',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="5" width="20" height="14" rx="2" /><path d="m10 9 5 3-5 3V9z" fill="currentColor" stroke="none" /></svg>,
  },
]
const STEP_KEYS = STEPS.map((s) => s.key)

// Scene plan per length, mirroring the backend, for before the script exists.
const PLAN = {
  30: ['HOOK', 'CONCEPT', 'NEET_ALERT'],
  60: ['HOOK', 'CONCEPT', 'EXAMPLE', 'MEMORY', 'NEET_ALERT'],
  120: ['HOOK', 'CONCEPT', 'EXAMPLE', 'MEMORY', 'NEET_ALERT'],
  300: ['HOOK', 'CONCEPT', 'CONCEPT', 'EXAMPLE', 'CONCEPT', 'EXAMPLE', 'MEMORY', 'NEET_ALERT'],
}
const SUBJECT_ICON = { physics: '⚛️', chemistry: '🧪', biology: '🧬' }
const RING_R = 104
const RING_C = 2 * Math.PI * RING_R

const partLabel = (p) => (p === 'NEET_ALERT' ? 'NEET Alert' : (p || '').charAt(0) + (p || '').slice(1).toLowerCase())
const fmtSecs = (s) => (s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${s.toFixed(1)}s`)
const lengthLabel = (sec) => (sec < 60 ? `${sec} sec` : `${sec / 60} min`)
// Backend timestamps are UTC without a zone marker.
const utc = (raw) => (raw ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(String(raw)) ? raw : `${raw}Z`).getTime() : null)

function Confetti() {
  const pieces = useMemo(() => Array.from({ length: 24 }, (_, i) => {
    const angle = Math.random() * Math.PI * 2
    const dist = 120 + Math.random() * 220
    return {
      color: ['#E11D33', '#10b981', '#2563eb', '#f59e0b', '#8b5cf6'][i % 5],
      x: Math.cos(angle) * dist, y: Math.sin(angle) * dist + 200,
      rot: Math.random() * 720, dur: 1400 + Math.random() * 700,
    }
  }), [])
  return (
    <div className="vg-confetti" aria-hidden="true">
      {pieces.map((p, i) => (
        <span key={i} style={{ background: p.color, '--x': `${p.x}px`, '--y': `${p.y}px`, '--r': `${p.rot}deg`, animationDuration: `${p.dur}ms` }} />
      ))}
    </div>
  )
}

export default function VideoGeneration() {
  const { jobId } = useParams()
  const nav = useNavigate()
  const [status, setStatus] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [retrying, setRetrying] = useState(false)
  const [loadError, setLoadError] = useState(null)
  const doneRef = useRef(false)

  // First load, then a slow poll as a safety net in case the live socket drops.
  useEffect(() => {
    let alive = true
    const load = () => getStatus(jobId)
      .then((res) => { if (alive) { setStatus((prev) => ({ ...(prev || {}), ...res.data })); setLoadError(null) } })
      .catch((err) => { if (alive && !status) setLoadError(err.response?.data?.detail || 'Could not load this video job.') })
    load()
    const poll = setInterval(() => { if (!doneRef.current) load() }, 4000)
    return () => { alive = false; clearInterval(poll) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  // Live updates over the websocket.
  useWebSocket(`/ws/${jobId}`, (data) => {
    if (data && typeof data === 'object') setStatus((prev) => ({ ...(prev || {}), ...data }))
  })

  const finished = status?.status === 'completed'
  const failed = status?.status === 'failed'
  doneRef.current = finished || failed

  // Tick for the elapsed timers while the job runs.
  useEffect(() => {
    if (finished || failed) return undefined
    const t = setInterval(() => setNow(Date.now()), 100)
    return () => clearInterval(t)
  }, [finished, failed])

  if (loadError && !status) {
    return (
      <div className="vg-page">
        <div className="vg-wrap"><div className="vg-panel vg-state"><h1>Couldn’t load this video</h1><p>{loadError}</p><Link to="/search" className="gl-gen vg-cta-link"><span>Back to Search</span></Link></div></div>
      </div>
    )
  }

  const progress = Math.max(0, Math.min(100, status?.progress ?? 0))
  const step = status?.step
  const stepTimes = status?.step_times || {}
  const stepIdx = STEP_KEYS.indexOf(step)
  const started = utc(status?.created_at)
  const total = finished
    ? Object.values(stepTimes).reduce((a, b) => a + b, 0)
    : started ? Math.max(0, (now - started) / 1000) : 0
  const currentStepSecs = status?.step_started_at ? Math.max(0, (now - utc(status.step_started_at)) / 1000) : 0

  const subject = (status?.resolved_subject || status?.subject || '').toLowerCase()
  const classLevel = status?.resolved_class_level || status?.class_level
  const duration = status?.duration_seconds || 60
  const portrait = status?.orientation === 'portrait'
  const parts = status?.scene_parts?.length ? status.scene_parts : (PLAN[duration] || PLAN[60])
  const titles = status?.scene_titles || []
  const lit = finished || stepIdx >= STEP_KEYS.indexOf('render') ? parts.length
    : step === 'narrate' ? (status?.scenes_done || 0) : 0

  const stepState = (key, i) => {
    if (finished) return 'done'
    if (key === step) return 'active'
    if (stepTimes[key] != null && (stepIdx === -1 || i < stepIdx)) return 'done'
    return ''
  }

  const headline = finished ? 'Your video is ready! 🎉'
    : failed ? (status?.stage === 'topic_not_found' ? 'Topic not found in NCERT' : 'Something went wrong')
    : step ? STEPS[stepIdx]?.verb : status?.stage === 'uploading' ? 'Saving' : 'Starting'
  const subline = finished
    ? `${lengthLabel(duration)} ${portrait ? 'reel' : 'video'} · grounded in NCERT`
    : status?.message || 'Connecting…'

  const angle = ((progress / 100) * 360 - 90) * (Math.PI / 180)

  // Left rail: the real passages retrieved; right rail: the scenes being made.
  const sources = status?.sources?.length ? status.sources : null
  const leftItems = sources ? [...sources, ...sources, ...sources].slice(0, Math.max(6, sources.length * 2)) : null
  const rightItems = parts.map((p, i) => ({ part: p, title: titles[i] }))

  async function retry() {
    setRetrying(true)
    try {
      const res = await generateVideo({
        topic: status.topic, subject: status.subject || undefined, class_level: status.class_level || undefined,
        duration_seconds: status.duration_seconds || 60, orientation: status.orientation || 'landscape',
      })
      nav(`/generate/${res.data.job_id}`)
    } catch {
      setRetrying(false)
    }
  }

  return (
    <div className={`vg-page${finished ? ' finished' : ''}`}>
      <AuthIcons />
      <div className="gl-glow a" aria-hidden="true" />
      <div className="vg-glow-b" aria-hidden="true" />

      {/* Side rails: NCERT passages flowing in, lesson frames flowing out */}
      <div className="vg-railcap left" aria-hidden="true">📚 NCERT corpus<span>→</span></div>
      <div className="vg-rail left" aria-hidden="true">
        <div className="vg-stream">
          {(leftItems || Array.from({ length: 8 }, () => null)).concat(leftItems || Array.from({ length: 8 }, () => null)).map((c, i) => (
            <div key={i} className={`vg-chunk${c ? '' : ' ghost'}`}>
              <span className="vg-cp">{c ? `NCERT · ${c.chapter}` : 'Searching…'}</span>
              <div className="vg-ct">{c ? c.title : ''}</div>
              <div className="vg-ln g" /><div className="vg-ln" /><div className="vg-ln s" />
            </div>
          ))}
        </div>
      </div>
      <div className="vg-railcap right" aria-hidden="true">🎬 Your lesson<span>→</span></div>
      <div className="vg-rail right" aria-hidden="true">
        <div className="vg-stream">
          {[...rightItems, ...rightItems, ...rightItems, ...rightItems].map((f, i) => (
            <div key={i} className={`vg-frame${portrait ? ' reel' : ''}`}>
              <span className="vg-holes l" /><span className="vg-holes r" />
              <span className="vg-pl" />
              <span className="vg-lbl">{(i % rightItems.length) + 1} · {partLabel(f.part)}</span>
              <span className="vg-sub" />
            </div>
          ))}
        </div>
      </div>

      <div className="vg-wrap">
        <div className="vg-panel">
          <div className="vg-head">
            <h1>{finished ? '🎬 Your Video Is Ready' : failed ? '🎬 Generation Stopped' : '🎬 Generating Your Video'}</h1>
            <div className="vg-chips">
              <span className="vg-chip">Topic: <b>{status?.topic || '…'}</b></span>
              {subject && <span className="vg-chip sub">{SUBJECT_ICON[subject] || '📘'} {subject.charAt(0).toUpperCase() + subject.slice(1)}{classLevel ? ` · Class ${classLevel}` : ''}</span>}
              <span className="vg-chip">{portrait ? '📱 9:16' : '📺 16:9'} · {lengthLabel(duration)}</span>
            </div>
          </div>

          <div className="vg-stage">
            <div className="vg-ring" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-label="Video generation progress">
              <span className="vg-sat s1"><i /></span><span className="vg-sat s2"><i /></span><span className="vg-sat s3"><i /></span>
              <svg width="230" height="230" viewBox="0 0 230 230" aria-hidden="true">
                <defs>
                  <linearGradient id="vgRingG" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#ff6b7f" /><stop offset="55%" stopColor="#E11D33" /><stop offset="100%" stopColor="#ff8a4d" />
                  </linearGradient>
                </defs>
                <circle cx="115" cy="115" r={RING_R} fill="none" stroke="var(--db-track)" strokeWidth="12" />
                <circle
                  className="vg-prog" cx="115" cy="115" r={RING_R} fill="none"
                  stroke={failed ? 'var(--db-crit)' : finished ? 'url(#vgRingG)' : 'url(#vgRingG)'}
                  strokeWidth="12" strokeLinecap="round"
                  strokeDasharray={RING_C} strokeDashoffset={RING_C - (progress / 100) * RING_C}
                />
              </svg>
              {!failed && (
                <span className="vg-glowdot" aria-hidden="true">
                  <i style={{ transform: `translate(${Math.cos(angle) * RING_R}px, ${Math.sin(angle) * RING_R}px)` }} />
                </span>
              )}
              <span className="vg-pct">{failed ? '!' : `${progress}%`}</span>
            </div>
            <div className="vg-slabel">{headline}</div>
            <div className="vg-ssub" aria-live="polite">{failed ? (status?.error || status?.message) : subline}</div>
            <div className="vg-elapsed">⏱ <b>{fmtSecs(total)}</b> {finished ? 'total' : 'elapsed'}</div>
          </div>

          {!failed && (
            <>
              <div className="vg-steps">
                <div className="vg-fillline" style={{ transform: `scaleX(${progress / 100})` }} />
                {STEPS.map((s, i) => {
                  const st = stepState(s.key, i)
                  const secs = st === 'active' ? currentStepSecs : stepTimes[s.key]
                  return (
                    <div key={s.key} className={`vg-stp ${st}`}>
                      <div className="vg-dot" aria-hidden="true">{s.icon}</div>
                      <span className="vg-nm">{s.label}</span>
                      <span className="vg-tm">{secs != null && (st || stepTimes[s.key] != null) ? fmtSecs(secs) : '—'}</span>
                    </div>
                  )
                })}
              </div>

              <div className="vg-board" aria-label="Scenes">
                {parts.map((p, i) => (
                  <div key={i} className={`vg-sc${i < lit ? ' lit' : ''}`} title={titles[i] || partLabel(p)}>{partLabel(p)}</div>
                ))}
              </div>
            </>
          )}

          {finished && (
            <div className="vg-total">
              <div className="vg-th"><b>✅ Completed in</b><span>{fmtSecs(total)}</span></div>
              <div className="vg-brk">
                {STEPS.map((s) => <span key={s.key} className="vg-bi">{s.label} <b>{fmtSecs(stepTimes[s.key] || 0)}</b></span>)}
              </div>
            </div>
          )}

          {!finished && !failed && (
            <div className="vg-cite">
              <span aria-hidden="true">📖</span>
              <span>{status?.source_label ? <>Grounded in <b>{status.source_label}</b> · every claim cited.</> : 'Finding the right NCERT chapter…'}</span>
            </div>
          )}

          {finished && (
            <Link to={`/watch/${jobId}`} className="vg-done-cta">
              <svg viewBox="0 0 24 24" fill="#fff" aria-hidden="true"><path d="M5 3l14 9-14 9V3z" /></svg>
              Watch your lesson
            </Link>
          )}

          {failed && (
            <div className="vg-fail-actions">
              {status?.stage !== 'topic_not_found' && (
                <button type="button" className="gl-gen" onClick={retry} disabled={retrying}><span>{retrying ? 'Restarting…' : '↻ Try again'}</span></button>
              )}
              <Link to="/search" className="qz-secondary">Choose another topic</Link>
            </div>
          )}
        </div>
      </div>

      {finished && <Confetti />}
    </div>
  )
}
