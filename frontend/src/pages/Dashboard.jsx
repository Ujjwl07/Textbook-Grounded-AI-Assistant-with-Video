import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useUser } from '@clerk/react'
import { useAuth } from '../contexts/AuthContext'
import { generateVideo, getDashboard, getQuizHistory, listVideos } from '../services/api'
import AuthIcons from '../components/AuthIcons'

const SUBJECTS = [
  { value: 'physics', label: 'Physics', color: 'var(--db-phys)' },
  { value: 'chemistry', label: 'Chemistry', color: 'var(--db-chem)' },
  { value: 'biology', label: 'Biology', color: 'var(--db-bio)' },
]
const subjectColor = (s) => SUBJECTS.find((x) => x.value === (s || '').toLowerCase())?.color || 'var(--ink-50)'
const DAY_LETTERS = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const RING = 132 // circumference of the ability ring (r = 21)
const SUBJECT_SHORT = { physics: 'PHY', chemistry: 'CHE', biology: 'BIO' }
const DIFF_SHORT = { EASY: 'Easy', MEDIUM: 'Med', HARD: 'Hard' }
const MISTAKES = [
  { key: 'conceptual', label: 'Conceptual', color: 'var(--db-concept)', tip: 'The idea itself needs another look.' },
  { key: 'calculation', label: 'Calculation', color: 'var(--db-calc)', tip: 'The concept was there; the slip was in the working.' },
  { key: 'silly', label: 'Silly', color: 'var(--db-silly)', tip: 'An easy one you likely knew. Slow down on keywords.' },
]
// Backend timestamps are UTC without a zone marker.
const parseUtc = (raw) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(String(raw)) ? raw : `${raw}Z`)
const OkIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
const NoIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>

// Ability comes from the adaptive engine on a -3…3 scale; show it out of 10.
const abilityOutOf10 = (a) => (a == null ? 0 : Math.max(0, Math.min(10, ((a + 3) / 6) * 10)))

// Counts up from 0 to the target once, for the stat tiles.
function CountUp({ value, decimals = 0 }) {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setShown(value); return undefined }
    let raf
    const t0 = performance.now()
    const step = (now) => {
      const p = Math.min((now - t0) / 900, 1)
      setShown(value * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [value])
  return <>{shown.toFixed(decimals)}</>
}

function StatusBadge({ status }) {
  if (status === 'completed') {
    return (
      <span className="db-status done">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>Completed
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="db-status fail">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>Failed
      </span>
    )
  }
  return (
    <span className="db-status proc">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
      {status === 'queued' ? 'Queued' : 'Processing'}
    </span>
  )
}

function FloatingScience() {
  return (
    <div aria-hidden="true">
      <div className="gl-sci p1">
        <svg viewBox="0 0 48 48" fill="none">
          <g className="gl-spin">
            <ellipse cx="24" cy="24" rx="17" ry="7" stroke="#a78bfa" strokeWidth="2.2" />
            <ellipse cx="24" cy="24" rx="17" ry="7" stroke="#8b5cf6" strokeWidth="2.2" transform="rotate(60 24 24)" />
            <ellipse cx="24" cy="24" rx="17" ry="7" stroke="#c4b5fd" strokeWidth="2.2" transform="rotate(120 24 24)" />
          </g>
          <circle cx="24" cy="24" r="5" fill="url(#au-gNuc)" />
        </svg>
      </div>
      <div className="gl-sci p2"><svg><use href="#au-ic-flask" /></svg></div>
      <div className="gl-sci p3"><svg><use href="#au-ic-dna" /></svg></div>
      <div className="gl-sci p4"><svg><use href="#au-ic-cell" /></svg></div>
      <div className="gl-sci p5"><svg><use href="#au-ic-play" /></svg></div>
      <div className="gl-sci p6"><svg><use href="#au-ic-book" /></svg></div>
      <span className="gl-spark s1">✦</span>
      <span className="gl-spark s2">✦</span>
      <span className="gl-spark s3">✦</span>
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const { user: clerkUser } = useUser()
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [videos, setVideos] = useState([])
  const [attempts, setAttempts] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(null)
  const [retrying, setRetrying] = useState(null)
  const [grown, setGrown] = useState(false) // bars animate from 0 after first paint

  useEffect(() => {
    if (!user) return
    Promise.all([getDashboard(user.id), listVideos(), getQuizHistory(user.id).catch(() => ({ data: { attempts: [] } }))])
      .then(([dashboardRes, videosRes, historyRes]) => {
        setData(dashboardRes.data)
        setVideos(videosRes.data.videos || [])
        setAttempts(historyRes.data.attempts || [])
        setError(null)
      })
      .catch((err) => { setError(err.response?.data?.detail || err.message); setData(null) })
      .finally(() => {
        setLoaded(true)
        requestAnimationFrame(() => requestAnimationFrame(() => setGrown(true)))
      })
  }, [user])

  const firstName = (user?.name || clerkUser?.firstName || 'Student').split(' ')[0]
  const completed = videos.filter((v) => v.status === 'completed').length
  const ability = abilityOutOf10(data?.ability)
  const streak = user?.streak_days || 0

  // Mastery per subject: average mastery of the topics you've made videos for in that subject.
  const mastery = useMemo(() => {
    const byTopic = data?.mastery_by_topic || {}
    return SUBJECTS.map((s) => {
      const mine = videos.filter((v) => (v.subject || '').toLowerCase() === s.value)
      const topics = [...new Set(mine.map((v) => v.topic).filter(Boolean))]
      const scores = topics.map((t) => byTopic[t]).filter((x) => typeof x === 'number')
      const pct = scores.length ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 100) : 0
      const classes = [...new Set(mine.map((v) => v.class_level).filter(Boolean))].sort()
      const sub = mine.length
        ? `Class ${classes.join(' & ') || '11'} · ${mine.length} lesson${mine.length === 1 ? '' : 's'} started`
        : 'Not started yet'
      return { ...s, pct, sub }
    })
  }, [data, videos])

  // Lessons generated on each of the last 7 days (today last).
  const week = useMemo(() => {
    const days = []
    const today = new Date()
    for (let i = 6; i >= 0; i -= 1) {
      const d = new Date(today)
      d.setDate(today.getDate() - i)
      days.push({ key: d.toDateString(), letter: DAY_LETTERS[d.getDay()], count: 0, today: i === 0, label: d.toLocaleDateString(undefined, { weekday: 'long' }) })
    }
    videos.forEach((v) => {
      if (!v.created_at) return
      // Backend stores UTC without a zone marker; treat it as UTC.
      const raw = String(v.created_at)
      const when = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(raw) ? raw : `${raw}Z`)
      const day = days.find((x) => x.key === when.toDateString())
      if (day) day.count += 1
    })
    return days
  }, [videos])
  const weekMax = Math.max(1, ...week.map((d) => d.count))
  const todayCount = week[6].count

  // ---- Quiz performance (one bar per quiz, oldest → newest, last 6) ----
  const quizzes = useMemo(() => {
    const byQuiz = new Map()
    ;[...attempts].reverse().forEach((a) => {
      const id = a.quiz_id || a.topic
      if (!byQuiz.has(id)) byQuiz.set(id, { id, topic: a.topic, correct: 0, total: 0 })
      const q = byQuiz.get(id)
      q.total += 1
      if (a.correct) q.correct += 1
    })
    return [...byQuiz.values()].map((q) => ({ ...q, pct: Math.round((q.correct / q.total) * 100) }))
  }, [attempts])
  const shownQuizzes = quizzes.slice(-6)
  const avg = quizzes.length ? Math.round(quizzes.reduce((s, q) => s + q.pct, 0) / quizzes.length) : 0
  const best = quizzes.length ? Math.max(...quizzes.map((q) => q.pct)) : 0
  const trend = (() => {
    if (quizzes.length < 2) return { sym: '–', label: 'Trend' }
    const half = Math.floor(quizzes.length / 2)
    const mean = (arr) => arr.reduce((s, q) => s + q.pct, 0) / arr.length
    const diff = mean(quizzes.slice(half)) - mean(quizzes.slice(0, half))
    return diff > 3 ? { sym: '↑', label: 'Trending up', cls: 'up' } : diff < -3 ? { sym: '↓', label: 'Trending down', cls: 'down' } : { sym: '→', label: 'Steady' }
  })()

  // ---- Mistakes ----
  const wrong = attempts.filter((a) => !a.correct)
  const mistakeCounts = MISTAKES.map((m) => ({ ...m, count: wrong.filter((a) => (a.mistake_type || 'conceptual') === m.key).length }))
  const latestVideoFor = (topic) => videos.find((v) => v.status === 'completed' && (v.topic || '').toLowerCase() === (topic || '').toLowerCase())

  async function retry(v) {
    setRetrying(v.job_id)
    try {
      const res = await generateVideo({ topic: v.topic, subject: v.subject, class_level: v.class_level || '11' })
      nav(`/generate/${res.data.job_id}`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not restart that video')
      setRetrying(null)
    }
  }

  return (
    <div className="db-page">
      <AuthIcons />
      <div className="gl-glow a" aria-hidden="true" />
      <div className="db-glow-b" aria-hidden="true" />
      <FloatingScience />

      <div className="db-wrap">
        <h1 className="gl-h1 db-h1">
          Welcome back,{' '}
          <span className="gl-u">
            <span className="gl-g">{firstName}</span>
            <svg viewBox="0 0 300 16" preserveAspectRatio="none" aria-hidden="true"><path pathLength="1" d="M3 11C80 3 230 3 297 9" /></svg>
          </span>
        </h1>
        <p className="gl-lede">Your learning progress at a glance.</p>

        {error && <div className="search-error db-error" role="alert"><span>⚠️</span> {error}</div>}

        {/* Stat tiles */}
        <div className="db-kpis">
          <div className="db-tile" style={{ '--tc': 'var(--gl-red, #e11d33)' }}>
            <div className="db-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="5" width="20" height="14" rx="2" /><path d="m10 9 5 3-5 3V9z" fill="currentColor" stroke="none" /></svg></div>
            <div className="db-num"><CountUp value={videos.length} /></div>
            <div className="db-lab">Total videos</div>
          </div>
          <div className="db-tile" style={{ '--tc': 'var(--db-good)' }}>
            <div className="db-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6 9 17l-5-5" /></svg></div>
            <div className="db-num"><CountUp value={completed} /></div>
            <div className="db-lab">Completed</div>
          </div>
          <div className="db-tile" style={{ '--tc': 'var(--db-phys)' }}>
            <svg className="db-ring" viewBox="0 0 50 50" aria-hidden="true">
              <circle cx="25" cy="25" r="21" fill="none" stroke="var(--db-track)" strokeWidth="6" />
              <circle
                cx="25" cy="25" r="21" fill="none" stroke="var(--db-phys)" strokeWidth="6" strokeLinecap="round"
                strokeDasharray={RING} strokeDashoffset={grown ? RING - (ability / 10) * RING : RING}
                transform="rotate(-90 25 25)" className="db-ring-fill"
              />
            </svg>
            <div className="db-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 3v18h18" /><rect x="7" y="12" width="3" height="6" /><rect x="12" y="8" width="3" height="10" /><rect x="17" y="5" width="3" height="13" /></svg></div>
            <div className="db-num">{data ? <CountUp value={ability} decimals={1} /> : '—'}<small>/10</small></div>
            <div className="db-lab">Ability score</div>
          </div>
          <div className="db-tile" style={{ '--tc': '#f59e0b' }}>
            <div className="db-ico"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2c1 3-1 4-2 6s0 4 2 4 2-2 1-4c3 1 5 4 5 7a6 6 0 0 1-12 0c0-4 4-6 6-13z" /></svg></div>
            <div className="db-num"><CountUp value={streak} /></div>
            <div className="db-lab">Day streak</div>
          </div>
        </div>

        <div className="db-cols">
          <section className="db-panel" aria-labelledby="db-mastery">
            <h2 className="db-ph" id="db-mastery">📊 Subject mastery</h2>
            {mastery.map((m) => (
              <div key={m.value} className="db-mrow" style={{ '--mc': m.color }}>
                <div className="db-mtop"><span className="db-nm"><i />{m.label}</span><span className="db-pct">{m.pct}%</span></div>
                <div className="db-mtrack" role="progressbar" aria-label={`${m.label} mastery`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={m.pct}>
                  <div className="db-mfill" style={{ width: grown ? `${Math.max(m.pct, 2)}%` : 0 }} />
                </div>
                <div className="db-msub">{m.sub}</div>
              </div>
            ))}
            <p className="db-note">Mastery grows as you answer quiz questions on a topic.</p>
          </section>

          <section className="db-panel" aria-labelledby="db-week">
            <h2 className="db-ph" id="db-week">🔥 This week</h2>
            <div className="db-week">
              {week.map((d) => (
                <div key={d.key} className={`db-day${d.today ? ' today' : ''}`} title={`${d.label}: ${d.count} lesson${d.count === 1 ? '' : 's'}`}>
                  <div className="db-bar" style={{ height: grown ? `${Math.max(6, (d.count / weekMax) * 100)}%` : '6%' }} />
                  <span className="db-dl">{d.letter}</span>
                </div>
              ))}
            </div>
            <p className="db-msub db-week-note">
              {todayCount > 0
                ? <>You generated <b>{todayCount} lesson{todayCount === 1 ? '' : 's'}</b> today. Keep your streak alive! 🔥</>
                : <>No lessons yet today. <Link to="/search">Generate one</Link> to keep your streak alive.</>}
            </p>
          </section>
        </div>

        {/* Performance + recent questions */}
        <div className="db-two">
          <section className="db-panel" aria-labelledby="db-perf">
            <h2 className="db-ph" id="db-perf">📈 Performance report</h2>
            {quizzes.length === 0 ? (
              <div className="db-mini-empty">
                <p>Your quiz scores will appear here.</p>
                <Link to="/quiz" className="db-act">Take a quiz →</Link>
              </div>
            ) : (
              <>
                <div className="db-scores">
                  {shownQuizzes.map((q) => (
                    <div key={q.id} className="db-scol" title={`${q.topic}: ${q.correct}/${q.total} correct`}>
                      <div className={`db-sb${q.pct < 60 ? ' low' : ''}`} style={{ height: grown ? `${Math.max(q.pct, 4)}%` : 0 }}>
                        <span className="db-sv">{q.pct}%</span>
                      </div>
                      <span className="db-sl">{q.topic}</span>
                    </div>
                  ))}
                </div>
                <div className="db-srow">
                  <div className="db-schip"><b>{avg}%</b><span>Avg score</span></div>
                  <div className="db-schip"><b>{best}%</b><span>Best</span></div>
                  <div className="db-schip"><b>{quizzes.length}</b><span>Quizzes</span></div>
                  <div className={`db-schip ${trend.cls || ''}`}><b>{trend.sym}</b><span>{trend.label}</span></div>
                </div>
              </>
            )}
          </section>

          <section className="db-panel" aria-labelledby="db-recent">
            <h2 className="db-ph" id="db-recent">🕑 Recent questions</h2>
            {attempts.length === 0 ? (
              <div className="db-mini-empty"><p>Questions you answer will be listed here.</p></div>
            ) : (
              <div className="db-hist">
                {attempts.slice(0, 6).map((a) => {
                  const subj = (a.subject || '').toLowerCase()
                  return (
                    <div key={a.attempt_id} className="db-hitem">
                      <span className="db-hpill" style={{ background: subjectColor(subj) }}>{SUBJECT_SHORT[subj] || 'Q'}</span>
                      <span className="db-hq" title={a.question || a.topic}>{a.question || a.topic}</span>
                      <span className="db-hd">{DIFF_SHORT[a.difficulty] || a.difficulty}</span>
                      <span className={`db-hr ${a.correct ? 'ok' : 'no'}`} aria-label={a.correct ? 'Correct' : 'Wrong'}>{a.correct ? <OkIcon /> : <NoIcon />}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        </div>

        {/* Mistake analysis */}
        <section className="db-panel db-mistakes" aria-labelledby="db-mist">
          <h2 className="db-ph" id="db-mist">🔎 Mistake analysis</h2>
          {wrong.length === 0 ? (
            <div className="db-mini-empty">
              <p>{attempts.length ? 'No mistakes yet. Nice work! 🎯' : 'Once you take a quiz, wrong answers are sorted here by kind so you know what to revise.'}</p>
            </div>
          ) : (
            <>
              <div className="db-segbar" role="img" aria-label={mistakeCounts.map((m) => `${m.label}: ${m.count}`).join(', ')}>
                {mistakeCounts.filter((m) => m.count).map((m) => (
                  <div key={m.key} className="db-seg" style={{ background: m.color, width: grown ? `${(m.count / wrong.length) * 100}%` : 0 }}>{m.count}</div>
                ))}
              </div>
              <div className="db-leg">
                {mistakeCounts.map((m) => (
                  <span key={m.key} className="db-li"><i style={{ background: m.color }} />{m.label} <small>· {m.count} error{m.count === 1 ? '' : 's'}</small></span>
                ))}
              </div>
              <div className="db-mist">
                {wrong.slice(0, 3).map((a) => {
                  const kind = MISTAKES.find((m) => m.key === (a.mistake_type || 'conceptual'))
                  const video = latestVideoFor(a.topic)
                  const subj = (a.subject || '').toLowerCase()
                  return (
                    <div key={a.attempt_id} className="db-mcard" style={{ '--ec': kind.color }}>
                      <div className="db-mhead">
                        <span className="db-etag">{kind.label}</span>
                        <span className="db-msub2">{subj ? `${subj[0].toUpperCase()}${subj.slice(1)} · ` : ''}{a.topic}</span>
                      </div>
                      <div className="db-mq">{a.question || a.topic}</div>
                      <div className="db-mwhy">
                        {a.selected_text ? <>You picked <b>“{a.selected_text}”</b>; the answer is <b>“{a.correct_text}”</b>. </> : null}
                        {a.mistake_reason || a.explanation || kind.tip}
                        {a.mistake_source && a.mistake_source !== 'rule' && <span className="db-ai" title={`Classified by ${a.mistake_source}`}>✦ AI</span>}
                      </div>
                      {video ? (
                        <Link to={`/watch/${video.job_id}`} className="db-rewatch">
                          <span className="db-rth" aria-hidden="true" />
                          <span className="db-rtx">Rewatch · {video.topic}<small>Open your lesson video</small></span>
                        </Link>
                      ) : (
                        <Link to={`/search?${new URLSearchParams({ topic: a.topic, ...(subj ? { subject: subj } : {}) })}`} className="db-rewatch">
                          <span className="db-rth" aria-hidden="true" />
                          <span className="db-rtx">Make a video · {a.topic}<small>Learn it again, then retry the quiz</small></span>
                        </Link>
                      )}
                    </div>
                  )
                })}
              </div>
              <p className="db-note">An AI model (Groq, OpenRouter or Gemini, whichever is available) reads each wrong answer and decides whether it was a conceptual, calculation or silly mistake. If none is available, a simple rule labels it instead.</p>
            </>
          )}
        </section>

        <section className="db-panel db-videos" aria-labelledby="db-vids">
          <h2 className="db-ph" id="db-vids">🎬 Your videos</h2>
          {loaded && videos.length === 0 ? (
            <div className="db-empty">
              <span aria-hidden="true">📹</span>
              <p>No videos yet. Start by searching a topic!</p>
              <Link to="/search" className="gl-gen db-empty-btn"><span>Search topics</span></Link>
            </div>
          ) : (
            <div className="db-vids">
              {videos.map((v) => {
                const subj = (v.subject || 'general').toLowerCase()
                const live = v.status === 'running' || v.status === 'queued'
                const to = v.status === 'completed' ? `/watch/${v.job_id}` : live ? `/generate/${v.job_id}` : null
                const Title = to ? Link : 'div'
                return (
                  <div key={v.job_id} className="db-vid" style={{ '--vc': subjectColor(subj) }}>
                    <div className="db-thumb" aria-hidden="true"><div className="db-tg" /><span className="db-pr" /></div>
                    <div className="db-vmeta">
                      <span className="db-pill">{subj.toUpperCase()}{v.class_level ? ` · CLASS ${v.class_level}` : ''}</span>
                      <Title className="db-vtitle" {...(to ? { to } : {})}>{v.topic || 'Untitled'}</Title>
                      {v.status === 'failed' && v.message && <div className="db-verr" title={v.error || v.message}>{v.message}</div>}
                    </div>
                    <div className="db-vright">
                      <StatusBadge status={v.status} />
                      {v.status === 'completed' && <Link to={`/watch/${v.job_id}`} className="db-act">▶ Watch</Link>}
                      {live && <Link to={`/generate/${v.job_id}`} className="db-act">View progress</Link>}
                      {v.status === 'failed' && (
                        <button type="button" className="db-act" onClick={() => retry(v)} disabled={retrying === v.job_id}>
                          {retrying === v.job_id ? '↻ Retrying…' : '↻ Retry'}
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
