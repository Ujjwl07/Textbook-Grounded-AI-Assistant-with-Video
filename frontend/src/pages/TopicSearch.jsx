import React, { useEffect, useState } from 'react'
import { generateVideo } from '../services/api'
import { useNavigate, useSearchParams } from 'react-router-dom'
import AuthIcons from '../components/AuthIcons'

// Each subject tints the page (top bar of the panels, focus ring, chips, preview scenes).
const SUBJECTS = [
  { value: 'physics', label: 'Physics', c: '#2563eb', c2: '#60a5fa' },
  { value: 'biology', label: 'Biology', c: '#10b981', c2: '#5eead4' },
  { value: 'chemistry', label: 'Chemistry', c: '#8b5cf6', c2: '#c4b5fd' },
]

const CLASS_LEVELS = [
  { value: '11', label: 'Class 11' },
  { value: '12', label: 'Class 12' },
]

const SUGGESTIONS = {
  physics: ["Newton's Laws of Motion", 'Work, Energy & Power', 'Electrostatics', 'Thermodynamics'],
  biology: ['Cell: The Unit of Life', 'Human Digestive System', 'Photosynthesis', 'Genetics & Evolution'],
  chemistry: ['Chemical Bonding', 'The p-Block Elements', 'Mole Concept', 'Chemical Kinetics'],
}

// Sample narration shown word by word in the preview.
const NARRATION = {
  physics: 'Ever wondered why you lurch forward when a bus stops suddenly? That is inertia, Newton’s First Law in action.',
  biology: 'Every living thing is built from cells, the basic unit of life. Let’s look inside one.',
  chemistry: 'Why do atoms bond at all? To reach a stable octet, they share or transfer electrons.',
}

// The five parts every generated lesson is built from.
const SCENES = ['Hook', 'Concept', 'Example', 'Memory', 'NEET Alert']
const CIRCLED = ['①', '②', '③', '④', '⑤']

function SubjectIcon({ subject, on }) {
  if (subject === 'physics') {
    const s = on ? '#fff' : '#2563eb'
    return (
      <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
        <ellipse cx="24" cy="24" rx="17" ry="7" stroke={s} strokeWidth="2.2" />
        <ellipse cx="24" cy="24" rx="17" ry="7" stroke={s} strokeWidth="2.2" transform="rotate(60 24 24)" />
        <ellipse cx="24" cy="24" rx="17" ry="7" stroke={s} strokeWidth="2.2" transform="rotate(120 24 24)" />
        <circle cx="24" cy="24" r="5" fill={s} />
      </svg>
    )
  }
  if (subject === 'biology') {
    return (
      <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
        <path d="M16 10c0 9 16 10 16 19s-16 10-16 19" stroke={on ? '#fff' : '#10b981'} strokeWidth="2.8" strokeLinecap="round" />
        <path d="M32 10c0 9-16 10-16 19s16 10 16 19" stroke={on ? '#d1fae5' : '#2563eb'} strokeWidth="2.8" strokeLinecap="round" />
        <path d="M18 15h12M19 23h10M19 31h10M18 38h12" stroke={on ? 'rgba(255,255,255,.7)' : '#5aa6d6'} strokeWidth="2" strokeLinecap="round" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <path d="M20 9h8v10l7 15a4 4 0 0 1-3.7 5.6H16.7A4 4 0 0 1 13 34l7-15V9z" fill="url(#au-gGlass)" stroke={on ? '#fff' : '#8b5cf6'} strokeWidth="2" />
      <path d="M15.5 28h17l2.5 5.4A4 4 0 0 1 31.3 39H16.7A4 4 0 0 1 13 33.4z" fill="url(#au-gLiq)" />
      <rect x="18" y="7" width="12" height="3" rx="1.5" fill={on ? '#fff' : '#8b5cf6'} />
    </svg>
  )
}

function PreviewDiagram({ subject }) {
  if (subject === 'biology') {
    return (
      <svg className="gl-diagram" viewBox="0 0 48 48" fill="none" aria-hidden="true">
        <circle cx="24" cy="24" r="19" stroke="#fff" strokeWidth="2" />
        <circle cx="21" cy="23" r="8" stroke="#fff" strokeWidth="2" />
        <circle cx="21" cy="23" r="3" fill="#fff" />
        <circle cx="33" cy="31" r="2.5" fill="#fff" />
      </svg>
    )
  }
  if (subject === 'chemistry') {
    return (
      <svg className="gl-diagram" viewBox="0 0 48 48" fill="none" aria-hidden="true">
        <path d="M24 8l14 8v16l-14 8-14-8V16z" stroke="#fff" strokeWidth="2" />
        <circle cx="24" cy="8" r="3" fill="#fff" /><circle cx="38" cy="32" r="3" fill="#fff" /><circle cx="10" cy="32" r="3" fill="#fff" />
      </svg>
    )
  }
  return (
    <svg className="gl-diagram" viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <ellipse cx="24" cy="24" rx="17" ry="7" stroke="#fff" strokeWidth="2" />
      <ellipse cx="24" cy="24" rx="17" ry="7" stroke="#fff" strokeWidth="2" transform="rotate(60 24 24)" />
      <ellipse cx="24" cy="24" rx="17" ry="7" stroke="#fff" strokeWidth="2" transform="rotate(120 24 24)" />
      <circle cx="24" cy="24" r="4.5" fill="#fff" />
    </svg>
  )
}

// Decorative tiles that float in the page margins on wide screens.
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
      <div className="gl-sci p5">
        <svg viewBox="0 0 48 48" fill="none">
          <g className="gl-spin">
            <circle cx="24" cy="24" r="15" fill="url(#au-gMetal)" />
            <circle cx="24" cy="24" r="4" fill="url(#au-gRed)" />
            <circle cx="24" cy="13" r="2.4" fill="#0b0b0f" /><circle cx="24" cy="35" r="2.4" fill="#0b0b0f" />
            <circle cx="13" cy="24" r="2.4" fill="#0b0b0f" /><circle cx="35" cy="24" r="2.4" fill="#0b0b0f" />
          </g>
        </svg>
      </div>
      <div className="gl-sci p6"><svg><use href="#au-ic-book" /></svg></div>
      <span className="gl-spark s1">✦</span>
      <span className="gl-spark s2">✦</span>
      <span className="gl-spark s3">✦</span>
    </div>
  )
}

function LessonPreview({ subject, classLevel, title }) {
  const [scene, setScene] = useState(0)
  const [word, setWord] = useState(0)
  const words = NARRATION[subject].split(' ')
  const sub = SUBJECTS.find((s) => s.value === subject)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined
    const a = setInterval(() => setScene((i) => (i + 1) % SCENES.length), 2600)
    const b = setInterval(() => setWord((i) => i + 1), 420)
    return () => { clearInterval(a); clearInterval(b) }
  }, [])

  useEffect(() => setWord(0), [subject])

  const wi = word % words.length
  const shown = words.slice(Math.max(0, wi - 5), wi + 1)

  return (
    <div className="gl-panel gl-preview">
      <div className="gl-pv-head">
        <span className="gl-label gl-label-tight">Lesson preview</span>
        <span className="gl-live"><i /> live sample</span>
      </div>
      <div className="gl-screen" aria-label={`Sample preview of a ${sub.label} lesson on ${title}`}>
        <span className="gl-scene-tag">{CIRCLED[scene]} {SCENES[scene].toUpperCase()}</span>
        <PreviewDiagram subject={subject} />
        <div className="gl-pv-title">{title}</div>
        <div className="gl-play" aria-hidden="true" />
        <span className="gl-pt" style={{ left: '20%', bottom: 60, animationDelay: '0s' }} />
        <span className="gl-pt" style={{ left: '42%', bottom: 50, animationDelay: '1.4s' }} />
        <span className="gl-pt" style={{ left: '63%', bottom: 62, animationDelay: '2.6s' }} />
        <span className="gl-pt" style={{ left: '80%', bottom: 54, animationDelay: '3.6s' }} />
        <div className="gl-subs" aria-hidden="true">
          <div className="gl-subbar">
            <div className="gl-k">
              {shown.map((w, i) => <b key={`${wi}-${i}`} className={i === shown.length - 1 ? 'lit' : ''}>{w}</b>)}
            </div>
          </div>
          <div className="gl-scrub"><i /></div>
        </div>
      </div>
      <div className="gl-scenes">
        {SCENES.map((s, i) => <div key={s} className={`gl-sc${i === scene ? ' on' : ''}`}>{s}</div>)}
      </div>
      <div className="gl-cite">
        <span className="gl-bk" aria-hidden="true">📖</span>
        <span>Grounded in <b>NCERT Class {classLevel} {sub.label}</b> · every claim carries its chapter citation.</span>
      </div>
    </div>
  )
}

export default function TopicSearch() {
  // The header search can open this page with ?topic=&subject=&class= filled in.
  const [params] = useSearchParams()
  const paramSubject = params.get('subject')
  const paramClass = params.get('class')
  const [topic, setTopic] = useState(params.get('topic') || '')
  const [subject, setSubject] = useState(SUBJECTS.some((s) => s.value === paramSubject) ? paramSubject : 'physics')
  const [classLevel, setClassLevel] = useState(CLASS_LEVELS.some((c) => c.value === paramClass) ? paramClass : '11')

  // Pick up new values when the header search is used while already on this page.
  useEffect(() => {
    if (params.get('topic')) setTopic(params.get('topic'))
    if (SUBJECTS.some((s) => s.value === paramSubject)) setSubject(paramSubject)
    if (CLASS_LEVELS.some((c) => c.value === paramClass)) setClassLevel(paramClass)
  }, [params, paramSubject, paramClass])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const nav = useNavigate()

  async function onGenerate() {
    if (!topic.trim() || loading) return
    setLoading(true)
    setError(null)
    try {
      const res = await generateVideo({ topic: topic.trim(), subject, class_level: classLevel })
      if (!res.data?.job_id) throw new Error('The server did not return a job.')
      nav(`/generate/${res.data.job_id}`)
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(
        typeof detail === 'string' ? detail
          : !err.response ? 'Couldn’t reach the TextbookAI server. Make sure the backend is running, then try again.'
          : `Failed to start generation (error ${err.response.status}).`,
      )
      setLoading(false)
    }
  }

  const activeSub = SUBJECTS.find((s) => s.value === subject)
  const previewTitle = topic.trim() || SUGGESTIONS[subject][0]

  return (
    <div className="gl-page" style={{ '--accent': activeSub.c, '--accent-2': activeSub.c2 }}>
      <AuthIcons />
      <div className="gl-glow a" aria-hidden="true" />
      <div className="gl-glow b" aria-hidden="true" />
      <FloatingScience />

      <div className="gl-wrap">
        <div className="gl-eyebrow">⚡ AI-powered · grounded in NCERT</div>
        <h1 className="gl-h1">
          Generate a{' '}
          <span className="gl-u">
            <span className="gl-g">Video Lesson</span>
            <svg viewBox="0 0 300 16" preserveAspectRatio="none" aria-hidden="true">
              <path pathLength="1" d="M3 11C70 3 230 3 297 9" />
            </svg>
          </span>
        </h1>
        <p className="gl-lede">
          Enter any NCERT topic and we’ll build a personalised microlearning video, with every fact drawn straight from your textbook.
        </p>

        <div className="gl-grid">
          <form className="gl-panel" onSubmit={(e) => { e.preventDefault(); onGenerate() }}>
            <span className="gl-label" id="gl-subject-label">Subject</span>
            <div className="gl-subjects" role="radiogroup" aria-labelledby="gl-subject-label">
              {SUBJECTS.map((s) => {
                const on = subject === s.value
                return (
                  <button
                    key={s.value} type="button" role="radio" aria-checked={on}
                    className={`gl-subj${on ? ' on' : ''}`}
                    style={{ '--sc': s.c, '--sc2': s.c2 }}
                    onClick={() => setSubject(s.value)}
                  >
                    <span className="gl-check" aria-hidden="true">✓</span>
                    <SubjectIcon subject={s.value} on={on} />
                    <span className="gl-subj-name">{s.label}</span>
                  </button>
                )
              })}
            </div>

            <span className="gl-label gl-mt" id="gl-class-label">Class level</span>
            <div className="gl-classes" role="radiogroup" aria-labelledby="gl-class-label">
              {CLASS_LEVELS.map((c) => (
                <button
                  key={c.value} type="button" role="radio" aria-checked={classLevel === c.value}
                  className={`gl-cls${classLevel === c.value ? ' on' : ''}`}
                  onClick={() => setClassLevel(c.value)}
                >
                  {c.label}
                </button>
              ))}
            </div>

            <label className="gl-label gl-mt" htmlFor="gl-topic">Topic</label>
            <div className="gl-topicwrap">
              <svg className="gl-ti" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
              </svg>
              <input
                id="gl-topic"
                className="gl-topic"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder={`e.g. ${SUGGESTIONS[subject][0]}`}
                autoComplete="off"
              />
            </div>
            <div className="gl-chips" aria-label="Suggested topics">
              {SUGGESTIONS[subject].map((t) => (
                <button key={t} type="button" className={`gl-chip${topic === t ? ' on' : ''}`} onClick={() => setTopic(t)}>{t}</button>
              ))}
            </div>

            {error && (
              <div className="search-error" role="alert"><span>⚠️</span> {error}</div>
            )}

            <button type="submit" className="gl-gen" disabled={!topic.trim() || loading}>
              <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" aria-hidden="true">
                <path d="m22 8-6 4 6 4V8z" /><rect x="2" y="6" width="14" height="12" rx="2" />
              </svg>
              <span>{loading ? `Building your ${activeSub.label} lesson…` : `Generate Video for ${activeSub.label}`}</span>
            </button>
            {!topic.trim() && <p className="gl-hint">Type a topic or pick one above to start.</p>}
          </form>

          <LessonPreview subject={subject} classLevel={classLevel} title={previewTitle} />
        </div>
      </div>
    </div>
  )
}
