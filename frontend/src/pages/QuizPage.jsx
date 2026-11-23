import React, { useState } from 'react'

const DEMO_QUESTIONS = [
  {
    id: 1,
    subject: 'Physics',
    topic: "Newton's Laws of Motion",
    question: 'A body of mass 5 kg is acted upon by two perpendicular forces 8 N and 6 N. The magnitude of the acceleration is:',
    options: { A: '2.0 m/s²', B: '2.8 m/s²', C: '1.4 m/s²', D: '3.6 m/s²' },
    correct: 'A',
    explanation: 'Net force = √(8² + 6²) = √(100) = 10 N. Acceleration = F/m = 10/5 = 2.0 m/s².',
  },
  {
    id: 2,
    subject: 'Biology',
    topic: 'Cell Division',
    question: 'During which phase of mitosis do chromosomes align at the metaphase plate?',
    options: { A: 'Prophase', B: 'Metaphase', C: 'Anaphase', D: 'Telophase' },
    correct: 'B',
    explanation: `During Metaphase, chromosomes line up at the cell's equatorial plate (metaphase plate) attached to spindle fibres at kinetochores.`,
  },
  {
    id: 3,
    subject: 'Chemistry',
    topic: 'Chemical Bonding',
    question: 'The shape of the SF₆ molecule is:',
    options: { A: 'Tetrahedral', B: 'Square planar', C: 'Octahedral', D: 'Trigonal bipyramidal' },
    correct: 'C',
    explanation: 'SF₆ has 6 bonding pairs and no lone pairs around the central S atom, giving it a regular octahedral geometry (sp³d² hybridization).',
  },
  {
    id: 4,
    subject: 'Physics',
    topic: 'Ray Optics',
    question: 'An object is placed at the centre of curvature of a concave mirror. The image formed is:',
    options: { A: 'Virtual and magnified', B: 'Real, inverted and of same size', C: 'Real, inverted and diminished', D: 'Virtual and diminished' },
    correct: 'B',
    explanation: 'When an object is at C (centre of curvature), a concave mirror produces a real, inverted image of the same size at C itself.',
  },
  {
    id: 5,
    subject: 'Biology',
    topic: 'Photosynthesis',
    question: 'Which pigment absorbs light most efficiently in the red and blue-violet regions?',
    options: { A: 'Chlorophyll b', B: 'Carotenoids', C: 'Chlorophyll a', D: 'Xanthophyll' },
    correct: 'C',
    explanation: 'Chlorophyll a has absorption peaks in the blue-violet (430 nm) and red (662 nm) regions and is the primary photosynthetic pigment.',
  },
]

const SUBJECT_COLORS = {
  Physics: '#818cf8',
  Biology: '#34d399',
  Chemistry: '#fbbf24',
}

export default function QuizPage() {
  const [current, setCurrent] = useState(0)
  const [selected, setSelected] = useState(null)
  const [confirmed, setConfirmed] = useState(false)
  const [score, setScore] = useState(0)
  const [finished, setFinished] = useState(false)
  const [answers, setAnswers] = useState([])

  const q = DEMO_QUESTIONS[current]

  function handleConfirm() {
    if (selected === null) return
    const isCorrect = selected === q.correct
    if (isCorrect) setScore((s) => s + 1)
    setAnswers((prev) => [...prev, { questionId: q.id, selected, correct: q.correct, isCorrect }])
    setConfirmed(true)
  }

  function handleNext() {
    if (current + 1 >= DEMO_QUESTIONS.length) {
      setFinished(true)
    } else {
      setCurrent((c) => c + 1)
      setSelected(null)
      setConfirmed(false)
    }
  }

  function handleRestart() {
    setCurrent(0)
    setSelected(null)
    setConfirmed(false)
    setScore(0)
    setFinished(false)
    setAnswers([])
  }

  if (finished) {
    const pct = Math.round((score / DEMO_QUESTIONS.length) * 100)
    return (
      <div className="quiz-page">
        <div className="quiz-result-card glass-panel">
          <div className="quiz-result-icon">{pct >= 60 ? '🎉' : '📚'}</div>
          <h2 className="quiz-result-title">Quiz Complete!</h2>
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
            <span className="quiz-score-text">{score}/{DEMO_QUESTIONS.length}</span>
          </div>
          <p className="quiz-score-label">{pct}% — {pct >= 80 ? 'Excellent!' : pct >= 60 ? 'Good job!' : 'Keep practising!'}</p>

          <div className="quiz-review">
            {answers.map((a, i) => (
              <div key={i} className={`quiz-review-row ${a.isCorrect ? 'correct' : 'wrong'}`}>
                <span className="quiz-review-num">Q{i + 1}</span>
                <span className="quiz-review-topic">{DEMO_QUESTIONS[i].topic}</span>
                <span className={`quiz-review-badge ${a.isCorrect ? 'correct' : 'wrong'}`}>
                  {a.isCorrect ? '✓ Correct' : `✗ ${a.correct}`}
                </span>
              </div>
            ))}
          </div>

          <button onClick={handleRestart} className="btn-primary" style={{ marginTop: '2rem', width: '100%' }}>
            Retry Quiz
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="quiz-page">
      {/* Progress header */}
      <div className="quiz-header">
        <div className="quiz-progress-bar-track">
          <div
            className="quiz-progress-bar-fill"
            style={{ width: `${((current) / DEMO_QUESTIONS.length) * 100}%` }}
          />
        </div>
        <div className="quiz-header-info">
          <span className="quiz-counter">Question {current + 1} of {DEMO_QUESTIONS.length}</span>
          <span className="quiz-score-live">Score: {score}</span>
        </div>
      </div>

      {/* Question card */}
      <div className="quiz-card glass-panel">
        <div className="quiz-meta">
          <span className="quiz-subject-badge" style={{ background: SUBJECT_COLORS[q.subject] || '#818cf8' }}>
            {q.subject}
          </span>
          <span className="quiz-topic-label">{q.topic}</span>
        </div>

        <h2 className="quiz-question">{q.question}</h2>

        <div className="quiz-options">
          {Object.entries(q.options).map(([key, val]) => {
            let cls = 'quiz-option'
            if (confirmed) {
              if (key === q.correct) cls += ' correct'
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
            <div className="quiz-explanation-icon">{selected === q.correct ? '✅' : '❌'}</div>
            <p>{q.explanation}</p>
          </div>
        )}

        <div className="quiz-actions">
          {!confirmed ? (
            <button className="btn-primary" onClick={handleConfirm} disabled={selected === null} style={{ width: '100%' }}>
              Confirm Answer
            </button>
          ) : (
            <button className="btn-primary" onClick={handleNext} style={{ width: '100%' }}>
              {current + 1 >= DEMO_QUESTIONS.length ? 'See Results' : 'Next Question →'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
