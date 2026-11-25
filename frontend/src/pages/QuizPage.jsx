import React, { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { generateQuiz, getNextQuestion, submitQuiz } from '../services/api'
import AuthIcons from '../components/AuthIcons'

const DIFFICULTY = {
  EASY: { label: 'Easy', dot: '#16a34a', text: '#15803d' },
  MEDIUM: { label: 'Medium', dot: '#f59e0b', text: '#b45309' },
  HARD: { label: 'Hard', dot: '#dc2626', text: '#b91c1c' },
}

const COUNTS = [[3, 'Quick'], [5, 'Standard'], [8, 'Deep'], [10, 'Full']]
const SUBJECT_CHOICES = [['', 'Any'], ['physics', 'Physics'], ['chemistry', 'Chemistry'], ['biology', 'Biology']]
const SUGGESTED = ['Laws of Motion', 'Photosynthesis', 'Chemical Kinetics', 'Human Eye', 'The Mole Concept', 'Genetics']

// Sample questions that cycle in the preview panel.
const SAMPLE = [
  { q: "A body continues in its state of rest or uniform motion unless acted on by an external force. This is Newton's —", o: ['Third Law of Motion', 'First Law of Motion', 'Law of Gravitation', 'Second Law of Motion'], a: 1, d: 'MEDIUM', s: 'PHYSICS' },
  { q: 'The green pigment in plants that captures light energy for photosynthesis is —', o: ['Haemoglobin', 'Chlorophyll', 'Carotene', 'Melanin'], a: 1, d: 'EASY', s: 'BIOLOGY' },
  { q: 'The rate constant of a first-order reaction has the units —', o: ['mol L⁻¹ s⁻¹', 's⁻¹', 'L mol⁻¹ s⁻¹', 'mol s⁻¹'], a: 1, d: 'HARD', s: 'CHEMISTRY' },
]

function DiffTag({ level, subject }) {
  const d = DIFFICULTY[level] || DIFFICULTY.MEDIUM
  return (
    <span className="qz-difftag" style={{ '--dc': d.dot, '--dt': d.text }}>
      <i />{d.label.toUpperCase()}{subject ? ` · ${subject.toUpperCase()}` : ''}
    </span>
  )
}

function Backdrop() {
  return (
    <>
      <AuthIcons />
      <div className="gl-glow a" aria-hidden="true" />
      <div className="qz-glow-b" aria-hidden="true" />
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
    </>
  )
}

function QuizPreview({ count }) {
  const [i, setI] = useState(0)
  const [reveal, setReveal] = useState(false)
  const [cycle, setCycle] = useState(0)
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setReveal(true); return undefined }
    const t = setInterval(() => { setI((x) => (x + 1) % SAMPLE.length); setCycle((c) => c + 1) }, 3400)
    return () => clearInterval(t)
  }, [])
  useEffect(() => {
    setReveal(false)
    const t = setTimeout(() => setReveal(true), 700)
    return () => clearTimeout(t)
  }, [i])
  const item = SAMPLE[i]
  return (
    <div className="gl-panel qz-panel" aria-label="Sample quiz question">
      <div className="gl-pv-head">
        <span className="gl-label gl-label-tight">Quiz preview</span>
        <span className="qz-live"><i /> adapts live</span>
      </div>
      <div className="qz-top">
        <div className="qz-prog">
          <div className="qz-pl"><span>Question 1 of {count}</span><span>{Math.round(100 / count)}%</span></div>
          <div className="qz-bar"><i style={{ width: `${100 / count}%` }} /></div>
        </div>
        <svg className="qz-timer" viewBox="0 0 46 46" aria-hidden="true">
          <circle cx="23" cy="23" r="19" fill="none" stroke="var(--db-track, #eceef3)" strokeWidth="5" />
          <circle key={cycle} className="qz-timer-ring" cx="23" cy="23" r="19" fill="none" stroke="var(--gl-red)" strokeWidth="5" strokeLinecap="round" strokeDasharray="119" transform="rotate(-90 23 23)" />
        </svg>
      </div>
      <DiffTag level={item.d} subject={item.s} />
      <div className="qz-question">{item.q}</div>
      <div className="qz-opts">
        {item.o.map((txt, k) => (
          <div key={txt} className={`qz-opt${reveal && k === item.a ? ' correct' : ''}`}>
            <span className="qz-k">{'ABCD'[k]}</span><span className="qz-tx">{txt}</span><span className="qz-mark">✓</span>
          </div>
        ))}
      </div>
      <div className="qz-foot"><span aria-hidden="true">🎯</span><span>Difficulty <b>adapts to your answers</b> · every question comes from <b>your NCERT textbook</b>.</span></div>
    </div>
  )
}

function errorText(err, fallback) {
  const detail = err.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

/**
 * Quiz on a topic, with or without a video.
 *   /quiz          -> pick any topic
 *   /quiz/:jobId   -> quiz on the lesson that video was made from
 * Questions are chosen one at a time by the server according to the student's
 * ability, so the quiz adapts as they answer.
 */
export default function QuizPage() {
  const { jobId } = useParams()

  const [phase, setPhase] = useState(jobId ? 'loading' : 'setup')
  const [topic, setTopic] = useState('')
  const [count, setCount] = useState(5)
  const [subject, setSubject] = useState('')
  const [quiz, setQuiz] = useState(null)
  const [step, setStep] = useState(null)
  const [selected, setSelected] = useState(null)
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [score, setScore] = useState(0)
  const startedFor = useRef(null)

  async function start(payload) {
    setPhase('loading')
    setError(null)
    setScore(0)
    setSelected(null)
    setFeedback(null)
    try {
      const res = await generateQuiz(payload)
      setQuiz(res.data)
      await loadNext(res.data.quiz_id)
    } catch (err) {
      setError(errorText(err, 'Could not build a quiz. Please try again.'))
      setPhase(jobId ? 'error' : 'setup')
    }
  }

  async function loadNext(quizId) {
    const res = await getNextQuestion(quizId)
    setStep(res.data)
    setSelected(null)
    setFeedback(null)
    setPhase(res.data.done ? 'result' : 'question')
  }

  // A quiz opened from a video starts by itself. The ref stops React's
  // development double-render from generating two quizzes.
  useEffect(() => {
    if (jobId && startedFor.current !== jobId) {
      startedFor.current = jobId
      start({ job_id: jobId, num_questions: count })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  function handleStart(e) {
    e.preventDefault()
    if (topic.trim().length < 2) return
    start({ topic: topic.trim(), num_questions: count, ...(subject ? { subject } : {}) })
  }

  async function handleConfirm() {
    if (!selected || busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await submitQuiz({ question_id: step.question.question_id, selected_option: selected })
      setFeedback(res.data)
      if (res.data.correct) setScore((s) => s + 1)
    } catch (err) {
      setError(errorText(err, 'Could not record your answer.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleNext() {
    setBusy(true)
    try {
      await loadNext(quiz.quiz_id)
    } catch (err) {
      setError(errorText(err, 'Could not load the next question.'))
    } finally {
      setBusy(false)
    }
  }

  function again() {
    start(jobId ? { job_id: jobId, num_questions: count } : { topic: quiz.topic, num_questions: count, ...(quiz.subject ? { subject: quiz.subject } : {}) })
  }

  // ---- setup -------------------------------------------------------------
  if (phase === 'setup') {
    return (
      <div className="gl-page qz-page">
        <Backdrop />
        <div className="gl-wrap">
          <div className="gl-eyebrow">🧠 Adaptive · grounded in NCERT</div>
          <h1 className="gl-h1">
            Take a{' '}
            <span className="gl-u">
              <span className="gl-g">Quiz</span>
              <svg viewBox="0 0 160 16" preserveAspectRatio="none" aria-hidden="true"><path pathLength="1" d="M3 11C40 3 120 3 157 9" /></svg>
            </span>
          </h1>
          <p className="gl-lede">Enter any NCERT topic. Questions come straight from your textbook and adapt to how you’re doing. No video needed first.</p>

          <div className="gl-grid">
            <form className="gl-panel qz-panel" onSubmit={handleStart}>
              <label className="gl-label" htmlFor="qz-topic">Topic</label>
              <div className="gl-topicwrap">
                <svg className="gl-ti" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
                <input
                  id="qz-topic" className="gl-topic qz-topic" value={topic} autoComplete="off"
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="e.g. Photosynthesis, Laws of Motion, Chemical Kinetics"
                />
              </div>
              <div className="gl-chips" aria-label="Suggested topics">
                {SUGGESTED.map((t) => (
                  <button key={t} type="button" className={`gl-chip qz-chip${topic === t ? ' on' : ''}`} onClick={() => setTopic(t)}>{t}</button>
                ))}
              </div>

              <span className="gl-label gl-mt" id="qz-count-label">Number of questions</span>
              <div className="qz-counts" role="radiogroup" aria-labelledby="qz-count-label">
                {COUNTS.map(([n, label]) => (
                  <button key={n} type="button" role="radio" aria-checked={count === n} className={`qz-cnt${count === n ? ' on' : ''}`} onClick={() => setCount(n)}>
                    <span>{n}</span><small>{label}</small>
                  </button>
                ))}
              </div>

              <span className="gl-label gl-mt" id="qz-subj-label">Subject <em className="qz-opt-note">optional</em></span>
              <div className="qz-diffs" role="radiogroup" aria-labelledby="qz-subj-label">
                {SUBJECT_CHOICES.map(([v, label]) => (
                  <button key={label} type="button" role="radio" aria-checked={subject === v} className={`qz-diff${subject === v ? ' on' : ''}`} onClick={() => setSubject(v)}>
                    {label}
                  </button>
                ))}
              </div>

              {error && <div className="search-error" role="alert"><span>⚠️</span> {error}</div>}

              <button type="submit" className="gl-gen" disabled={topic.trim().length < 2}>
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 3l14 9-14 9V3z" fill="#fff" /></svg>
                <span>Start {count}-Question Quiz</span>
              </button>
              <p className="gl-hint">Questions start at your current level and get harder or easier as you answer.</p>
            </form>

            <QuizPreview count={count} />
          </div>
        </div>
      </div>
    )
  }

  // ---- loading / error ---------------------------------------------------
  if (phase === 'loading') {
    return (
      <div className="gl-page qz-page">
        <Backdrop />
        <div className="qz-center">
          <div className="gl-panel qz-panel qz-state" role="status">
            <div className="qz-spinner" aria-hidden="true" />
            <h2>Building your quiz…</h2>
            <p>Picking questions from your textbook. This can take up to half a minute.</p>
          </div>
        </div>
      </div>
    )
  }

  if (phase === 'error') {
    return (
      <div className="gl-page qz-page">
        <Backdrop />
        <div className="qz-center">
          <div className="gl-panel qz-panel qz-state">
            <div className="qz-big" aria-hidden="true">😕</div>
            <h2>No quiz this time</h2>
            <p>{error}</p>
            <button type="button" onClick={again} className="gl-gen"><span>Try again</span></button>
            <Link to="/quiz" className="qz-secondary">Quiz on another topic</Link>
          </div>
        </div>
      </div>
    )
  }

  // ---- result ------------------------------------------------------------
  if (phase === 'result') {
    const summary = step.summary
    const pct = summary.total ? Math.round((summary.correct / summary.total) * 100) : 0
    const good = pct >= 60
    return (
      <div className="gl-page qz-page">
        <Backdrop />
        <div className="qz-center">
          <div className="gl-panel qz-panel qz-state qz-result">
            <div className="qz-big" aria-hidden="true">{good ? '🎉' : '📚'}</div>
            <h2>Quiz complete!</h2>
            <p className="qz-result-topic">{quiz.topic}</p>
            <div className="qz-score">
              <svg viewBox="0 0 120 120" aria-hidden="true">
                <circle cx="60" cy="60" r="52" fill="none" stroke="var(--db-track, #eceef3)" strokeWidth="9" />
                <circle
                  cx="60" cy="60" r="52" fill="none" stroke={good ? '#16a34a' : 'var(--gl-red)'} strokeWidth="9" strokeLinecap="round"
                  strokeDasharray={`${(pct / 100) * 326.7} 326.7`} transform="rotate(-90 60 60)" className="qz-score-ring"
                />
              </svg>
              <span>{summary.correct}/{summary.total}</span>
            </div>
            <p className="qz-score-label">{pct}% · {pct >= 80 ? 'Excellent!' : good ? 'Good job!' : 'Keep practising!'}</p>

            <div className="qz-rows">
              <div className="qz-row"><span>Your ability estimate</span><b className="qz-badge ok">{summary.ability.toFixed(2)}</b></div>
              {summary.mastery != null && (
                <div className="qz-row"><span>Mastery of this topic</span><b className="qz-badge ok">{Math.round(summary.mastery * 100)}%</b></div>
              )}
              {summary.next_topic && (
                <div className="qz-row"><span>Revise next: {summary.next_topic}</span><Link to={`/search?topic=${encodeURIComponent(summary.next_topic)}`} className="qz-badge warn">Make a video</Link></div>
              )}
            </div>

            <button type="button" onClick={again} className="gl-gen"><span>New questions on this topic</span></button>
            <Link to="/quiz" className="qz-secondary">Quiz on another topic</Link>
          </div>
        </div>
      </div>
    )
  }

  // ---- question ----------------------------------------------------------
  const q = step.question
  const confirmed = Boolean(feedback)
  const isLast = step.answered + 1 >= step.total
  const progress = ((step.answered + (confirmed ? 1 : 0)) / step.total) * 100

  return (
    <div className="gl-page qz-page">
      <Backdrop />
      <div className="qz-center">
        <div className="gl-panel qz-panel qz-live-card">
          <div className="qz-top">
            <div className="qz-prog">
              <div className="qz-pl"><span>Question {step.answered + 1} of {step.total}</span><span>Score {score}</span></div>
              <div className="qz-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)}><i style={{ width: `${progress}%` }} /></div>
            </div>
          </div>

          <div className="qz-meta">
            <DiffTag level={q.difficulty} subject={quiz.subject} />
            <span className="qz-topicname">{quiz.topic}</span>
          </div>

          <h2 className="qz-question qz-question-lg">{q.question}</h2>

          <div className="qz-opts" role="radiogroup" aria-label="Answer options">
            {Object.entries(q.options).map(([key, val]) => {
              let cls = 'qz-opt qz-choice'
              if (confirmed) {
                if (key === feedback.correct_option) cls += ' correct'
                else if (key === selected) cls += ' wrong'
              } else if (key === selected) cls += ' selected'
              return (
                <button key={key} type="button" role="radio" aria-checked={selected === key} className={cls} onClick={() => !confirmed && setSelected(key)} disabled={confirmed}>
                  <span className="qz-k">{key}</span><span className="qz-tx">{val}</span>
                  <span className="qz-mark">{confirmed && key === feedback.correct_option ? '✓' : confirmed && key === selected ? '✗' : ''}</span>
                </button>
              )
            })}
          </div>

          {confirmed && (
            <div className={`qz-foot qz-explain ${feedback.correct ? 'ok' : 'bad'}`} aria-live="polite">
              <span aria-hidden="true">{feedback.correct ? '✅' : '❌'}</span>
              <span><b>{feedback.correct ? 'Correct.' : 'Not quite.'}</b> {feedback.explanation}</span>
            </div>
          )}

          {error && <div className="search-error" role="alert"><span>⚠️</span> {error}</div>}

          {!confirmed ? (
            <button type="button" className="gl-gen" onClick={handleConfirm} disabled={selected === null || busy}>
              <span>{busy ? 'Checking…' : 'Confirm answer'}</span>
            </button>
          ) : (
            <button type="button" className="gl-gen" onClick={handleNext} disabled={busy}>
              <span>{isLast ? 'See results' : 'Next question →'}</span>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
