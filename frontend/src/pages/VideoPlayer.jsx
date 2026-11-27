import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  API_BASE_URL, askDoubt, generateVideo, getFlashcards, getMediaToken, getVideo, updateLessonProgress,
} from '../services/api'
import { INDEXED_UPTO, NCERT } from '../components/StudyPlan'

const SUBJECT_COLORS = {
  physics: ['#2563eb', '#60a5fa'],
  chemistry: ['#8b5cf6', '#c4b5fd'],
  biology: ['#10b981', '#5eead4'],
}
const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
const SPEEDS = [1, 1.25, 1.5, 2, 0.75]

const partLabel = (part) => {
  const p = String(part || '').replace(/_/g, ' ').trim().toLowerCase()
  if (!p) return 'Scene'
  if (p === 'neet alert') return 'NEET Alert'
  return p.replace(/\b\w/g, (c) => c.toUpperCase())
}
const fmt = (s) => {
  if (!Number.isFinite(s) || s < 0) s = 0
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}
const titleCase = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '')
const classOf = (v) => String(v || '').replace(/\D/g, '')

function buildPlayableUrl(rawUrl, mediaToken, download = false) {
  if (!rawUrl) return ''
  if (/^https?:\/\//i.test(rawUrl)) {
    // Cloudinary serves a file download when fl_attachment is in the path.
    return download ? rawUrl.replace('/upload/', '/upload/fl_attachment/') : rawUrl
  }
  const url = new URL(`${new URL(API_BASE_URL).origin}${rawUrl}`)
  if (mediaToken && rawUrl.startsWith('/api/video-file/')) url.searchParams.set('token', mediaToken)
  if (download) url.searchParams.set('download', 'true')
  return url.toString()
}

// The NCERT chapter this lesson belongs to, and the one after it.
function chapterInfo(lesson) {
  const subject = (lesson.resolved_subject || lesson.subject || '').toLowerCase()
  const cls = classOf(lesson.resolved_class_level || lesson.class_level)
  const book = NCERT[subject]?.[cls]
  let n = parseInt(lesson.chapter_number, 10)
  if (!n && lesson.sources?.length) {
    const counts = {}
    lesson.sources.forEach((s) => { const m = /Ch (\d+)/.exec(s.chapter || ''); if (m) counts[m[1]] = (counts[m[1]] || 0) + 1 })
    const best = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]
    if (best) n = parseInt(best[0], 10)
  }
  if (!n && book) {
    const i = book.findIndex((t) => t.toLowerCase() === String(lesson.topic || '').toLowerCase())
    if (i >= 0) n = i + 1
  }
  if (!n || !book) return { subject, cls, n: n || null, next: null }
  let next = null
  if (n < book.length) next = { subject, cls, n: n + 1, title: book[n] }
  else if (cls === '11' && NCERT[subject]?.['12']) next = { subject, cls: '12', n: 1, title: NCERT[subject]['12'][0] }
  if (next) {
    const limit = INDEXED_UPTO[`${next.subject}-${next.cls}`]
    next.available = !limit || next.n <= limit
  }
  return { subject, cls, n, name: lesson.chapter_name || book[n - 1], next }
}

function Sheet({ title, icon, onClose, children, wide }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="wl-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className={`wl-sheet${wide ? ' wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="wl-sheet-h">
          <span>{icon} {title}</span>
          <button type="button" className="wl-x" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="wl-sheet-b">{children}</div>
      </div>
    </div>
  )
}

const Icon = {
  cards: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="7" width="14" height="12" rx="2" /><path d="M7 3h14v12" /></svg>,
  transcript: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></svg>,
  notes: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>,
  check: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9" /><path d="m8.5 12 2.5 2.5 4.5-5" /></svg>,
  save: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z" /></svg>,
  download: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>,
  share: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="m8.6 13.5 6.8 4M15.4 6.5 8.6 10.5" /></svg>,
  regen: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-3-6.7M21 4v5h-5" /></svg>,
  fs: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M3 16v3a2 2 0 0 0 2 2h3" /></svg>,
  doubt: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><path d="M12 7v.01M12 10c1.5 0 2 1 2 2s-1 1.3-1 2" strokeLinecap="round" /></svg>,
  play: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4l13 8-13 8V4z" /></svg>,
  pause: <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></svg>,
  vol: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M11 5 6 9H3v6h3l5 4V5z" fill="currentColor" /><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" /></svg>,
  mute: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M11 5 6 9H3v6h3l5 4V5z" fill="currentColor" /><path d="m16 9 6 6M22 9l-6 6" /></svg>,
}

export default function VideoPlayer() {
  const { jobId } = useParams()
  const nav = useNavigate()
  const [lesson, setLesson] = useState(null)
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState({ completed: false, saved: false, notes: '' })
  const [sheet, setSheet] = useState(null) // 'doubt' | 'cards' | 'transcript' | 'notes'
  const [toast, setToast] = useState(null)
  const [busy, setBusy] = useState(null) // 'regen' | 'next'

  // player state
  const videoRef = useRef(null)
  const playerRef = useRef(null)
  const [t, setT] = useState(0)
  const [dur, setDur] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [res, setRes] = useState(null)
  const [cc, setCc] = useState(true)
  const [idle, setIdle] = useState(false)
  const idleTimer = useRef(null)

  const flash = useCallback((msg) => {
    setToast(msg)
    clearTimeout(flash.timer)
    flash.timer = setTimeout(() => setToast(null), 2600)
  }, [])

  useEffect(() => {
    let alive = true
    setLesson(null); setError(null); setT(0); setDur(0); setPlaying(false)
    getVideo(jobId)
      .then(async (r) => {
        const needsToken = r.data?.video_url?.startsWith('/api/video-file/')
        const mediaToken = needsToken ? await getMediaToken() : null
        if (!alive) return
        setLesson({ ...r.data, mediaToken })
        setProgress(r.data.progress || { completed: false, saved: false, notes: '' })
      })
      .catch((err) => { if (alive) setError(err.response?.data?.detail || 'Unable to load this lesson') })
    return () => { alive = false }
  }, [jobId])

  // Scenes with start/end on the video's clock. Older videos kept only the
  // scene names, so their scenes are spread evenly over the video.
  const scenes = useMemo(() => {
    if (!lesson) return []
    const total = dur || lesson.duration_seconds || 60
    if (lesson.timeline?.length) {
      return lesson.timeline.map((s, i, all) => ({
        part: s.part, title: s.title, text: s.text, words: s.words || [],
        start: i === 0 ? 0 : s.start,
        end: i === all.length - 1 ? total : all[i + 1].start,
        at: s.start,
      }))
    }
    const parts = lesson.scene_parts?.length ? lesson.scene_parts : ['HOOK']
    const step = total / parts.length
    return parts.map((p, i) => ({
      part: p, title: lesson.scene_titles?.[i] || '', text: '', words: [],
      start: i * step, end: (i + 1) * step, at: i * step,
    }))
  }, [lesson, dur])

  const cur = Math.max(0, scenes.findIndex((s, i) => t >= s.start && (t < s.end || i === scenes.length - 1)))
  const scene = scenes[cur]

  const caption = useMemo(() => {
    const words = scene?.words || []
    let wi = -1
    for (let i = 0; i < words.length; i += 1) { if (words[i][1] <= t) wi = i; else break }
    if (wi < 0) return null
    const from = Math.max(0, wi - 6)
    return words.slice(from, wi + 1).map((w, i) => ({ w: w[0], lit: from + i === wi }))
  }, [scene, t])

  const info = useMemo(() => (lesson ? chapterInfo(lesson) : null), [lesson])

  // ---- player controls ----
  const toggle = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    if (v.paused || v.ended) v.play().catch(() => {}); else v.pause()
  }, [])
  const seek = useCallback((sec, play = false) => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = Math.max(0, Math.min(sec, (v.duration || sec) - 0.05))
    setT(v.currentTime)
    if (play) v.play().catch(() => {})
  }, [])
  const fullscreen = useCallback(() => {
    const p = playerRef.current
    if (!p) return
    if (document.fullscreenElement) document.exitFullscreen?.()
    else (p.requestFullscreen || p.webkitRequestFullscreen)?.call(p)
  }, [])
  const wake = () => {
    setIdle(false)
    clearTimeout(idleTimer.current)
    idleTimer.current = setTimeout(() => setIdle(true), 2600)
  }
  useEffect(() => () => clearTimeout(idleTimer.current), [])

  useEffect(() => {
    const onKey = (e) => {
      if (sheet || /input|textarea|select/i.test(e.target.tagName) || e.target.isContentEditable) return
      if (e.key === ' ' || e.key === 'k') { e.preventDefault(); toggle() }
      else if (e.key === 'ArrowRight') seek((videoRef.current?.currentTime || 0) + 5)
      else if (e.key === 'ArrowLeft') seek((videoRef.current?.currentTime || 0) - 5)
      else if (e.key === 'f') fullscreen()
      else if (e.key === 'm' && videoRef.current) { videoRef.current.muted = !videoRef.current.muted; setMuted(videoRef.current.muted) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sheet, toggle, seek, fullscreen])

  // ---- lesson state (saved on the server) ----
  const saveProgress = useCallback(async (fields, okMsg) => {
    const before = progress
    setProgress((p) => ({ ...p, ...fields }))
    try {
      const r = await updateLessonProgress(jobId, fields)
      setProgress(r.data)
      if (okMsg) flash(okMsg)
    } catch (err) {
      setProgress(before)
      flash(err.response?.data?.detail || 'Couldn’t save that. Try again.')
    }
  }, [jobId, progress, flash])

  const onEnded = () => {
    setPlaying(false)
    if (!progress.completed) saveProgress({ completed: true }, 'Lesson finished: marked complete ✓')
  }

  const share = async () => {
    const url = window.location.href
    const title = `${lesson.topic} · TextbookAI`
    try {
      if (navigator.share) { await navigator.share({ title, url }); return }
      await navigator.clipboard.writeText(url)
      flash('Link copied to clipboard')
    } catch (err) {
      if (err?.name !== 'AbortError') flash('Couldn’t share. Copy the address bar instead.')
    }
  }

  const startLesson = async (payload, kind) => {
    setBusy(kind)
    try {
      const r = await generateVideo({
        duration_seconds: lesson.duration_seconds || 60,
        orientation: lesson.orientation || 'landscape',
        voice_language: lesson.voice_language || 'en-IN',
        caption_language: lesson.caption_language || lesson.voice_language || 'en-IN',
        pace: lesson.pace || 1,
        ...payload,
      })
      nav(`/generate/${r.data.job_id}`)
    } catch (err) {
      setBusy(null)
      flash(err.response?.data?.detail || 'Couldn’t start the lesson. Try again.')
    }
  }
  const regenerate = () => {
    if (!window.confirm(`Make a fresh version of “${lesson.topic}”? This one stays in your library.`)) return
    startLesson({ topic: lesson.topic, subject: lesson.subject || undefined, class_level: lesson.class_level || undefined }, 'regen')
  }
  const playNext = () => {
    const nx = info?.next
    if (!nx?.available) return
    startLesson({ topic: nx.title, subject: nx.subject, class_level: nx.cls }, 'next')
  }

  // ---- render ----
  if (error) {
    return (
      <div className="wl-page">
        <div className="wl-wrap wl-state">
          <span className="wl-state-ic">😔</span>
          <h1>Lesson unavailable</h1>
          <p>{error}</p>
          <Link to="/search" className="wl-btn primary">← Back to Search</Link>
        </div>
      </div>
    )
  }
  if (!lesson) {
    return (
      <div className="wl-page">
        <div className="wl-wrap wl-state"><div className="wl-spinner" /><p>Loading your lesson…</p></div>
      </div>
    )
  }

  const subject = (lesson.resolved_subject || lesson.subject || '').toLowerCase()
  const [acc, acc2] = SUBJECT_COLORS[subject] || ['#e11d33', '#ff8a5c']
  const cls = classOf(lesson.resolved_class_level || lesson.class_level)
  const videoUrl = buildPlayableUrl(lesson.video_url, lesson.mediaToken)
  const downloadUrl = buildPlayableUrl(lesson.video_url, lesson.mediaToken, true)
  const portrait = lesson.orientation === 'portrait'
  const total = dur || lesson.duration_seconds || 60
  const showChrome = !playing || !idle
  const sourceText = lesson.source_label
    || (info?.n ? `NCERT Class ${cls} ${titleCase(subject)} · Chapter ${info.n}${info.name ? ` ${info.name}` : ''}` : `NCERT Class ${cls} ${titleCase(subject)}`)

  return (
    <div className="wl-page" style={{ '--acc': acc, '--acc2': acc2 }}>
      <div className="wl-glow a" /><div className="wl-glow b" />
      <div className="wl-wrap">
        <div className="wl-crumb">
          <Link to="/search">Search</Link> ›{' '}
          {subject && <><Link to={`/search?subject=${subject}${cls ? `&class=${cls}` : ''}`}>{titleCase(subject)}</Link> ›{' '}</>}
          <span className="on">{lesson.topic}</span>
        </div>

        <div className="wl-head">
          <span className="wl-eyebrow">✓ Lesson ready</span>
          <h1>{lesson.topic || 'Video lesson'}</h1>
          <div className="wl-tags">
            {subject && <span className="wl-tag sub">{subject.toUpperCase()}</span>}
            {cls && <span className="wl-tag cls">CLASS {cls}</span>}
            <span className="wl-tag meta">⏱ {fmt(total)}</span>
            <span className="wl-tag meta">🎬 {scenes.length} scene{scenes.length === 1 ? '' : 's'}</span>
            {info?.n && <span className="wl-tag meta">📖 NCERT Ch {info.n}</span>}
            {progress.completed && <span className="wl-tag done">✓ Completed</span>}
          </div>
        </div>

        <div className={`wl-grid${portrait ? ' portrait' : ''}`}>
          <div className="wl-main">
            <div
              ref={playerRef}
              className={`wl-player${portrait ? ' reel' : ''}${playing ? ' playing' : ''}${showChrome ? '' : ' idle'}`}
              onMouseMove={wake}
              onMouseLeave={() => playing && setIdle(true)}
            >
              <video
                ref={videoRef}
                src={videoUrl}
                preload="metadata"
                playsInline
                onClick={toggle}
                onDoubleClick={fullscreen}
                onPlay={() => { setPlaying(true); wake() }}
                onPause={() => setPlaying(false)}
                onEnded={onEnded}
                onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
                onLoadedMetadata={(e) => {
                  const v = e.currentTarget
                  setDur(v.duration || 0)
                  if (v.videoWidth) setRes(Math.min(v.videoWidth, v.videoHeight))
                }}
                onError={() => setError('This video file could not be played. It may have been removed; try Regenerate from Search.')}
              />
              <span className="wl-ptag">{CIRCLED[cur] || cur + 1} {partLabel(scene?.part).toUpperCase()}</span>
              {res && <span className="wl-pres">{res}p<b>{res >= 720 ? '·HD' : ''}</b></span>}
              {!playing && t < 0.2 && <div className="wl-ptitle">{lesson.topic}</div>}
              {!playing && (
                <button type="button" className="wl-pplay" onClick={toggle} aria-label="Play" />
              )}
              <div className="wl-pbottom" onClick={(e) => e.stopPropagation()}>
                {cc && caption && (
                  <div className="wl-subbar">{caption.map((c, i) => <b key={i} className={c.lit ? 'lit' : ''}>{c.w}</b>)}</div>
                )}
                <div className="wl-ctrls">
                  <button type="button" className="wl-cbtn" onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}>{playing ? Icon.pause : Icon.play}</button>
                  <span className="wl-ptime">{fmt(t)} / {fmt(total)}</span>
                  <span className="wl-sp" />
                  <button type="button" className="wl-cbtn txt" onClick={() => { const i = (SPEEDS.indexOf(speed) + 1) % SPEEDS.length; setSpeed(SPEEDS[i]); if (videoRef.current) videoRef.current.playbackRate = SPEEDS[i] }} aria-label="Playback speed">{speed}×</button>
                  <button type="button" className={`wl-cbtn txt${cc ? ' on' : ''}`} onClick={() => setCc((v) => !v)} aria-label="Captions" title={scenes.some((s) => s.words.length) ? 'Captions' : 'Captions are burned into this video'}>CC</button>
                  <button type="button" className="wl-cbtn" onClick={() => { const v = videoRef.current; if (v) { v.muted = !v.muted; setMuted(v.muted) } }} aria-label={muted ? 'Unmute' : 'Mute'}>{muted ? Icon.mute : Icon.vol}</button>
                  <button type="button" className="wl-cbtn" onClick={fullscreen} aria-label="Full screen">{Icon.fs}</button>
                </div>
                <div className="wl-scrub">
                  {scenes.map((s, i) => {
                    const len = Math.max(0.01, s.end - s.start)
                    const fill = Math.max(0, Math.min(1, (t - s.start) / len))
                    return (
                      <div
                        key={i}
                        className={`wl-seg${i === cur ? ' cur' : ''}`}
                        style={{ flex: len }}
                        title={`${partLabel(s.part)} · ${fmt(s.at)}`}
                        onClick={(e) => {
                          const r = e.currentTarget.getBoundingClientRect()
                          seek(s.start + ((e.clientX - r.left) / r.width) * len)
                        }}
                      >
                        <i style={{ transform: `scaleX(${fill})` }} />
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            <div className="wl-actions">
              <Link to={`/quiz/${jobId}`} className="wl-btn primary">📝 Take the Quiz</Link>
              <button type="button" className="wl-btn accent" onClick={() => { videoRef.current?.pause(); setSheet('doubt') }}>{Icon.doubt}Ask a Doubt</button>
            </div>
            <div className="wl-tools">
              <button type="button" className="wl-tool" onClick={() => setSheet('cards')}>{Icon.cards}Flashcards</button>
              <button type="button" className="wl-tool" onClick={() => setSheet('transcript')}>{Icon.transcript}Transcript</button>
              <button type="button" className={`wl-tool${progress.notes ? ' has' : ''}`} onClick={() => setSheet('notes')}>{Icon.notes}My Notes</button>
              <button type="button" className={`wl-tool${progress.completed ? ' on' : ''}`} onClick={() => saveProgress({ completed: !progress.completed }, progress.completed ? 'Marked as not complete' : 'Marked complete ✓')}>{Icon.check}{progress.completed ? 'Completed' : 'Mark complete'}</button>
              <button type="button" className={`wl-tool${progress.saved ? ' saved' : ''}`} onClick={() => saveProgress({ saved: !progress.saved }, progress.saved ? 'Removed from saved' : 'Saved to your library')}>{Icon.save}{progress.saved ? 'Saved' : 'Save'}</button>
              <a className="wl-tool" href={downloadUrl} download={`${lesson.topic || 'lesson'}.mp4`} onClick={() => flash('Download started')}>{Icon.download}Download</a>
              <button type="button" className="wl-tool" onClick={share}>{Icon.share}Share</button>
              <button type="button" className="wl-tool" onClick={regenerate} disabled={!!busy}>{Icon.regen}{busy === 'regen' ? 'Starting…' : 'Regenerate'}</button>
              <button type="button" className="wl-tool" onClick={fullscreen}>{Icon.fs}Full screen</button>
            </div>
          </div>

          <aside className="wl-side">
            <div className="wl-panel">
              <div className="wl-ph">🎬 In this lesson</div>
              <div className="wl-scenes">
                {scenes.map((s, i) => (
                  <button type="button" key={i} className={`wl-scene${i === cur ? ' on' : ''}`} onClick={() => seek(s.at, true)}>
                    <span className="n">{i + 1}</span>
                    <span className="m"><b>{partLabel(s.part)}</b><span>{s.title || '—'}</span></span>
                    <span className="t">{fmt(s.at)}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="wl-panel">
              <div className="wl-ph">📖 Source</div>
              <div className="wl-cite">
                <span className="bk">📘</span>
                <span>Every claim in this video is drawn from <b>{sourceText}</b>, with on-screen chapter citations. Nothing comes from the open web.</span>
              </div>
              {lesson.sources?.length > 0 && (
                <div className="wl-srcs">
                  {lesson.sources.slice(0, 5).map((s, i) => <span key={i}><b>{s.chapter}</b> {s.title}</span>)}
                </div>
              )}
            </div>

            <div className="wl-panel">
              <div className="wl-ph">⏭️ Up next</div>
              {info?.next ? (
                <div className={`wl-next${info.next.available ? '' : ' off'}`}>
                  <div className="th" />
                  <div className="m">
                    <small>{titleCase(info.next.subject)} · Class {info.next.cls} · Ch {info.next.n}</small>
                    <b>{info.next.title}</b>
                    {!info.next.available && <em>Not in the textbook library yet</em>}
                  </div>
                  <button type="button" className="go" onClick={playNext} disabled={!info.next.available || !!busy} aria-label={`Generate a lesson on ${info.next.title}`}>
                    {busy === 'next' ? <span className="wl-mini-spin" /> : <svg viewBox="0 0 24 24" fill="#fff"><path d="M5 3l14 9-14 9V3z" /></svg>}
                  </button>
                </div>
              ) : (
                <div className="wl-next">
                  <div className="m"><small>Keep going</small><b>Pick your next topic</b></div>
                  <Link className="go" to="/search" aria-label="Search for another topic"><svg viewBox="0 0 24 24" fill="#fff"><path d="M5 3l14 9-14 9V3z" /></svg></Link>
                </div>
              )}
            </div>
          </aside>
        </div>
      </div>

      {sheet === 'doubt' && <DoubtSheet lesson={lesson} scene={scene} onClose={() => setSheet(null)} />}
      {sheet === 'cards' && <CardsSheet jobId={jobId} initial={lesson.flashcards} onClose={() => setSheet(null)} />}
      {sheet === 'transcript' && (
        <Sheet title="Transcript" icon="📄" onClose={() => setSheet(null)} wide>
          {scenes.some((s) => s.text) ? (
            <div className="wl-trans">
              {scenes.map((s, i) => (
                <button type="button" key={i} className={`wl-tr${i === cur ? ' on' : ''}`} onClick={() => seek(s.at, true)}>
                  <span className="wl-tr-h"><b>{partLabel(s.part)}</b>{s.title && <> · {s.title}</>}<em>{fmt(s.at)}</em></span>
                  <span className="wl-tr-p">{s.text}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="wl-empty">This lesson was made before transcripts were saved. Use <b>Regenerate</b> to make a fresh version with a full transcript.</p>
          )}
        </Sheet>
      )}
      {sheet === 'notes' && (
        <NotesSheet
          initial={progress.notes}
          now={fmt(t)}
          onSave={async (notes) => {
            const r = await updateLessonProgress(jobId, { notes })
            setProgress(r.data)
          }}
          onClose={() => setSheet(null)}
        />
      )}
      {toast && <div className="wl-toast" role="status">{toast}</div>}
    </div>
  )
}

// Just enough Markdown for tutor answers: headings, bold, bullets, quotes.
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) return <b key={i}>{part.slice(2, -2)}</b>
    if (/^`[^`]+`$/.test(part)) return <code key={i}>{part.slice(1, -1)}</code>
    return part.replace(/(^|\s)\*([^*\s][^*]*)\*/g, '$1$2')
  })
}
function RichText({ text }) {
  const blocks = []
  let list = null
  String(text || '').split('\n').forEach((raw, i) => {
    const line = raw.trimEnd()
    const bullet = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line)
    if (bullet) {
      if (!list) { list = []; blocks.push(<ul key={`u${i}`}>{list}</ul>) }
      list.push(<li key={i}>{inline(bullet[1])}</li>)
      return
    }
    list = null
    if (!line.trim()) return
    const heading = /^#{1,6}\s+(.*)$/.exec(line)
    if (heading) blocks.push(<p key={i} className="h">{inline(heading[1].replace(/\*\*/g, ''))}</p>)
    else if (line.startsWith('>')) blocks.push(<blockquote key={i}>{inline(line.replace(/^>\s?/, ''))}</blockquote>)
    else if (/^-{3,}$/.test(line.trim())) blocks.push(<hr key={i} />)
    else blocks.push(<p key={i}>{inline(line)}</p>)
  })
  return <div className="wl-rich">{blocks}</div>
}

function DoubtSheet({ lesson, scene, onClose }) {
  const [q, setQ] = useState('')
  const [thread, setThread] = useState([])
  const [loading, setLoading] = useState(false)
  const endRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }) }, [thread, loading])

  const ask = async (e) => {
    e.preventDefault()
    const question = q.trim()
    if (question.length < 2 || loading) return
    setQ(''); setLoading(true)
    try {
      const r = await askDoubt({
        query: `${question} (topic: ${lesson.topic})`,
        subject: lesson.resolved_subject || lesson.subject || undefined,
        class_level: classOf(lesson.resolved_class_level || lesson.class_level) || undefined,
      })
      const answer = r.data.answer || 'I couldn’t find this in the textbook. Try asking it differently.'
      const chapters = [...new Map((r.data.chunks || [])
        .filter((c) => c.chapter_number || c.chapter_name)
        .map((c) => [`${c.chapter_number}`, `Ch ${c.chapter_number}${c.chapter_name ? ` · ${c.chapter_name}` : ''}`])).values()].slice(0, 3)
      setThread((th) => [...th, { q: question, a: answer, chapters, error: answer.startsWith('Error:') }])
    } catch (err) {
      setThread((th) => [...th, { q: question, a: err.response?.data?.detail || 'Couldn’t reach the tutor. Try again.', error: true }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <Sheet title="Ask a doubt" icon="💬" onClose={onClose} wide>
      <div className="wl-chat">
        {thread.length === 0 && !loading && (
          <div className="wl-empty">
            Ask anything about <b>{lesson.topic}</b>. Answers come only from your NCERT textbook.
            <div className="wl-sugs">
              {[`Explain ${partLabel(scene?.part).toLowerCase()} again in simple words`, 'What do NEET questions ask from this?', 'Give me a real-life example'].map((s) => (
                <button type="button" key={s} onClick={() => setQ(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {thread.map((m, i) => (
          <div key={i} className="wl-qa">
            <div className="wl-q">{m.q}</div>
            <div className={`wl-a${m.error ? ' err' : ''}`}><RichText text={m.a} />
              {m.chapters?.length > 0 && <div className="wl-a-src">📖 {m.chapters.join('  ·  ')}</div>}
            </div>
          </div>
        ))}
        {loading && <div className="wl-a wl-typing"><i /><i /><i /></div>}
        <div ref={endRef} />
      </div>
      <form className="wl-ask" onSubmit={ask}>
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type your doubt…" maxLength={400} />
        <button type="submit" className="wl-btn primary" disabled={loading || q.trim().length < 2}>Ask</button>
      </form>
    </Sheet>
  )
}

function CardsSheet({ jobId, initial, onClose }) {
  const [cards, setCards] = useState(initial || [])
  const [i, setI] = useState(0)
  const [flip, setFlip] = useState(false)
  const [loading, setLoading] = useState(!(initial && initial.length))
  const [err, setErr] = useState(null)

  const load = useCallback(async (refresh) => {
    setLoading(true); setErr(null)
    try {
      const r = await getFlashcards(jobId, refresh)
      setCards(r.data.cards); setI(0); setFlip(false)
    } catch (e) {
      setErr(e.response?.data?.detail || 'Couldn’t make flashcards right now.')
    } finally {
      setLoading(false)
    }
  }, [jobId])
  const started = useRef(false)
  useEffect(() => {
    // Once per open (StrictMode runs effects twice in development).
    if (started.current || (initial && initial.length)) return
    started.current = true
    load(false)
  }, [initial, load])

  const go = (d) => { setFlip(false); setI((x) => (x + d + cards.length) % cards.length) }
  useEffect(() => {
    const onKey = (e) => {
      if (!cards.length) return
      if (e.key === 'ArrowRight') go(1)
      else if (e.key === 'ArrowLeft') go(-1)
      else if (e.key === ' ') { e.preventDefault(); setFlip((f) => !f) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const card = cards[i]
  return (
    <Sheet title="Flashcards" icon="🃏" onClose={onClose}>
      {loading ? (
        <div className="wl-empty"><div className="wl-spinner" />Writing flashcards from this lesson…</div>
      ) : err ? (
        <div className="wl-empty">{err}<button type="button" className="wl-btn" onClick={() => load(false)}>Try again</button></div>
      ) : card ? (
        <>
          <button type="button" className={`wl-card${flip ? ' flip' : ''}`} onClick={() => setFlip((f) => !f)}>
            <span className="face front"><small>Question</small>{card.front}<em>Tap to reveal</em></span>
            <span className="face back"><small>Answer</small>{card.back}</span>
          </button>
          <div className="wl-card-nav">
            <button type="button" className="wl-btn" onClick={() => go(-1)}>←</button>
            <span>{i + 1} / {cards.length}</span>
            <button type="button" className="wl-btn" onClick={() => go(1)}>→</button>
          </div>
          <button type="button" className="wl-link" onClick={() => load(true)}>↻ Make a new set</button>
        </>
      ) : null}
    </Sheet>
  )
}

function NotesSheet({ initial, now, onSave, onClose }) {
  const [text, setText] = useState(initial || '')
  const [state, setState] = useState('saved') // saved | dirty | saving | error
  const ref = useRef(null)
  const latest = useRef(text)
  latest.current = text

  const save = useCallback(async () => {
    setState('saving')
    try { await onSave(latest.current); setState('saved') } catch { setState('error') }
  }, [onSave])

  useEffect(() => {
    if (state !== 'dirty') return undefined
    const id = setTimeout(save, 900)
    return () => clearTimeout(id)
  }, [text, state, save])

  const close = () => { if (state === 'dirty' || state === 'error') save(); onClose() }
  const stamp = () => {
    const el = ref.current
    const at = el ? el.selectionStart : text.length
    const ins = `${at && text[at - 1] !== '\n' ? '\n' : ''}[${now}] `
    const next = text.slice(0, at) + ins + text.slice(at)
    setText(next); setState('dirty')
    requestAnimationFrame(() => { if (el) { el.focus(); el.selectionStart = el.selectionEnd = at + ins.length } })
  }

  return (
    <Sheet title="My notes" icon="✏️" onClose={close} wide>
      <textarea
        ref={ref}
        className="wl-notes"
        autoFocus
        value={text}
        onChange={(e) => { setText(e.target.value); setState('dirty') }}
        placeholder="Write what you want to remember from this lesson…"
        maxLength={20000}
      />
      <div className="wl-notes-f">
        <button type="button" className="wl-btn" onClick={stamp}>⏱ Add timestamp {now}</button>
        <span className={`wl-notes-s ${state}`}>
          {state === 'saving' ? 'Saving…' : state === 'dirty' ? 'Editing…' : state === 'error' ? 'Not saved. Retrying on close' : 'Saved ✓'}
        </span>
      </div>
    </Sheet>
  )
}
