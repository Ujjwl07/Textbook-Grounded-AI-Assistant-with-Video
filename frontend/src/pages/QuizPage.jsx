import React, { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { generateQuiz, getNextQuestion, submitQuiz } from '../services/api'

const SUBJECT_COLORS = {
  physics: '#818cf8',
  biology: '#34d399',
  chemistry: '#fbbf24',
}

const DIFFICULTY_LABEL = { EASY: 'Easy', MEDIUM: 'Medium', HARD: 'Hard' }

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
    start({ topic: topic.trim(), num_questions: count })
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
    start(jobId ? { job_id: jobId, num_questions: count } : { topic: quiz.topic, num_questions: count })
  }

  // ---- setup -------------------------------------------------------------
  if (phase === 'setup') {
    return (
      <div className="search-page">
        <div className="search-hero">
          <h1 className="search-title">
            <span style={{ fontSize: '2rem', display: 'block', marginBottom: '0.25rem' }}>📝</span>
            Take a <span className="hero-highlight">Quiz</span>
          </h1>
          <p className="search-subtitle">
            Enter any NCERT topic. Questions come from your textbook and adapt to how you are doing.
            You do not need to watch a video first.
          </p>
        </div>

        <form className="search-card glass-panel" onSubmit={handleStart}>
          <label className="input-label">Topic</label>
          <input
            className="input-field"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Photosynthesis, Laws of Motion, Chemical Kinetics"
            style={{ marginBottom: 0 }}
          />

          <label className="input-label" style={{ marginTop: '1.5rem' }}>Number of questions</label>
          <div className="search-classes">
            {[3, 5, 8, 10].map((n) => (
              <button
                type="button"
                key={n}
                className={`search-class-btn ${count === n ? 'active' : ''}`}
                onClick={() => setCount(n)}
              >
                {n}
              </button>
            ))}
          </div>

          {error && (
            <div className="search-error">
              <span>⚠️</span> {error}
            </div>
          )}

          <button
            className="btn-primary"
            type="submit"
            disabled={topic.trim().length < 2}
            style={{ width: '100%', marginTop: '1.5rem', padding: '1rem' }}
          >
            Start Quiz
          </button>
        </form>
      </div>
    )
  }

  // ---- loading / error ---------------------------------------------------
  if (phase === 'loading') {
    return (
      <div className="quiz-page">
        <div className="gen-loading glass-panel">
          <div className="gen-spinner" />
          <p style={{ color: 'var(--text-secondary)', marginTop: '1rem' }}>
            Building your quiz from the textbook… this can take up to half a minute.
          </p>
        </div>
      </div>
    )
  }

  if (phase === 'error') {
    return (
      <div className="quiz-page">
        <div className="quiz-result-card glass-panel">
          <div className="quiz-result-icon">😕</div>
          <h2 className="quiz-result-title">No quiz this time</h2>
          <p style={{ color: 'var(--text-secondary)', marginTop: '0.5rem' }}>{error}</p>
          <button onClick={again} className="btn-primary" style={{ marginTop: '1.5rem', width: '100%' }}>
            Try Again
          </button>
          <Link to="/quiz" className="btn-secondary" style={{ marginTop: '0.75rem', textDecoration: 'none', display: 'block' }}>
            Quiz on another topic
          </Link>
        </div>
      </div>
    )
  }

  // ---- result ------------------------------------------------------------
  if (phase === 'result') {
    const summary = step.summary
    const pct = summary.total ? Math.round((summary.correct / summary.total) * 100) : 0
    return (
      <div className="quiz-page">
        <div className="quiz-result-card glass-panel">
          <div className="quiz-result-icon">{pct >= 60 ? '🎉' : '📚'}</div>
          <h2 className="quiz-result-title">Quiz Complete!</h2>
          <p style={{ color: 'var(--text-secondary)' }}>{quiz.topic}</p>
          <div className="quiz-score-ring">
            <svg viewBox="0 0 120 120" width="140" height="140">
              <circle cx="60" cy="60" r="52" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="8" />
              <circle
                cx="60" cy="60" r="52" fill="none"
                stroke={pct >= 60 ? '#34d399' : '#f87171'}
                strokeWidth="8" strokeLinecap="round"
                strokeDasharray={`${(pct / 100) * 326.7} 326.7`}
                style={{ transform: 'rotate(-90deg)', transformOrigin: 'center', transition: 'stroke-dasharray 1s ease' }}
              />
            </svg>
            <span className="quiz-score-text">{summary.correct}/{summary.total}</span>
          </div>
          <p className="quiz-score-label">
            {pct}% — {pct >= 80 ? 'Excellent!' : pct >= 60 ? 'Good job!' : 'Keep practising!'}
          </p>

          <div className="quiz-review">
            <div className="quiz-review-row">
              <span className="quiz-review-topic">Your ability estimate</span>
              <span className="quiz-review-badge correct">{summary.ability.toFixed(2)}</span>
            </div>
            {summary.mastery != null && (
              <div className="quiz-review-row">
                <span className="quiz-review-topic">Mastery of this topic</span>
                <span className="quiz-review-badge correct">{Math.round(summary.mastery * 100)}%</span>
              </div>
            )}
            {summary.next_topic && (
              <div className="quiz-review-row">
                <span className="quiz-review-topic">Revise next: {summary.next_topic}</span>
                <Link to="/search" className="quiz-review-badge wrong" style={{ textDecoration: 'none' }}>
                  Make a video
                </Link>
              </div>
            )}
          </div>

          <button onClick={again} className="btn-primary" style={{ marginTop: '2rem', width: '100%' }}>
            New Questions on This Topic
          </button>
          <Link
            to="/quiz"
            className="btn-secondary"
            style={{ marginTop: '0.75rem', textDecoration: 'none', display: 'block' }}
          >
            Quiz on another topic
          </Link>
        </div>
      </div>
    )
  }

  // ---- question ----------------------------------------------------------
  const q = step.question
  const subjectColor = SUBJECT_COLORS[(quiz.subject || '').toLowerCase()] || '#818cf8'
  const confirmed = Boolean(feedback)
  const isLast = step.answered + 1 >= step.total

  return (
    <div className="quiz-page">
      <div className="quiz-header">
        <div className="quiz-progress-bar-track">
          <div
            className="quiz-progress-bar-fill"
            style={{ width: `${(step.answered / step.total) * 100}%` }}
          />
        </div>
        <div className="quiz-header-info">
          <span className="quiz-counter">Question {step.answered + 1} of {step.total}</span>
          <span className="quiz-score-live">Score: {score}</span>
        </div>
      </div>

      <div className="quiz-card glass-panel">
        <div className="quiz-meta">
          {quiz.subject && (
            <span className="quiz-subject-badge" style={{ background: subjectColor }}>
              {quiz.subject.charAt(0).toUpperCase() + quiz.subject.slice(1)}
            </span>
          )}
          <span className="quiz-topic-label">{quiz.topic}</span>
          <span className="quiz-topic-label" style={{ marginLeft: 'auto' }}>
            {DIFFICULTY_LABEL[q.difficulty] || q.difficulty}
          </span>
        </div>

        <h2 className="quiz-question">{q.question}</h2>

        <div className="quiz-options">
          {Object.entries(q.options).map(([key, val]) => {
            let cls = 'quiz-option'
            if (confirmed) {
              if (key === feedback.correct_option) cls += ' correct'
              else if (key === selected) cls += ' wrong'
            } else if (key === selected) {
              cls += ' selected'
            }
            return (
              <button
                key={key}
                className={cls}
                onClick={() => !confirmed && setSelected(key)}
                disabled={confirmed}
              >
                <span className="quiz-option-key">{key}</span>
                <span className="quiz-option-text">{val}</span>
              </button>
            )
          })}
        </div>

        {confirmed && (
          <div className="quiz-explanation">
            <div className="quiz-explanation-icon">{feedback.correct ? '✅' : '❌'}</div>
            <p>{feedback.explanation}</p>
          </div>
        )}

        {error && (
          <div className="search-error">
            <span>⚠️</span> {error}
          </div>
        )}

        <div className="quiz-actions">
          {!confirmed ? (
            <button
              className="btn-primary"
              onClick={handleConfirm}
              disabled={selected === null || busy}
              style={{ width: '100%' }}
            >
              {busy ? 'Checking…' : 'Confirm Answer'}
            </button>
          ) : (
            <button className="btn-primary" onClick={handleNext} disabled={busy} style={{ width: '100%' }}>
              {isLast ? 'See Results' : 'Next Question →'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
