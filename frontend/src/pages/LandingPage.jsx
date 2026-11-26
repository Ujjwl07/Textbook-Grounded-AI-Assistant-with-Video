import React, { useCallback, useEffect, useRef, useState } from 'react'
import IntroLoader from '../components/IntroLoader'
import StudyPlan from '../components/StudyPlan'
import { Link, useNavigate } from 'react-router-dom'

// Length of the sample clip in seconds (shown as 3:10 on the timeline).
const DURATION = 10
const SHOWN_SECONDS = 190
const CAPTION = 'ATP and NADPH are made on the thylakoid membranes, then the Calvin cycle uses both to fix CO₂.'.split(' ')
const OPTIONS = ['Stroma', 'Thylakoid membranes', 'Mitochondrial matrix', 'Outer envelope']
const CORRECT = 1
const ATP_COUNT = 6

const clamp = (x) => Math.max(0, Math.min(1, x))
const fmt = (sec) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`

function SampleVideo() {
  const [playing, setPlaying] = useState(true)
  const [answer, setAnswer] = useState(null)
  const [t, setT] = useState(0)

  const tRef = useRef(0)
  const playingRef = useRef(true)
  const restartTimer = useRef(null)
  const trackRef = useRef(null)

  const setTime = (v) => {
    tRef.current = v
    setT(v)
  }

  const restart = () => {
    clearTimeout(restartTimer.current)
    setAnswer(null)
    playingRef.current = true
    setPlaying(true)
    setTime(0)
  }

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      playingRef.current = false
      setPlaying(false)
      setTime(DURATION - 0.2)
      return undefined
    }
    let raf
    let last = performance.now()
    const frame = (now) => {
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now
      if (playingRef.current) {
        let next = tRef.current + dt
        if (next >= DURATION) {
          next = DURATION
          playingRef.current = false
          setPlaying(false)
          clearTimeout(restartTimer.current)
          restartTimer.current = setTimeout(restart, 12000)
        }
        setTime(next)
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(restartTimer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const togglePlay = () => {
    if (tRef.current >= DURATION) return restart()
    playingRef.current = !playingRef.current
    setPlaying(playingRef.current)
  }

  const seekTo = (v) => {
    clearTimeout(restartTimer.current)
    if (v < DURATION - 0.05) setAnswer(null)
    setTime(v)
  }

  const onTrackClick = (e) => {
    const b = trackRef.current.getBoundingClientRect()
    seekTo(clamp((e.clientX - b.left) / b.width) * DURATION)
  }

  const onTrackKey = (e) => {
    if (e.key === 'ArrowRight') seekTo(Math.min(DURATION, tRef.current + 0.5))
    else if (e.key === 'ArrowLeft') seekTo(Math.max(0, tRef.current - 0.5))
  }

  const choose = (i) => {
    if (answer !== null) return
    setAnswer(i)
    clearTimeout(restartTimer.current)
    restartTimer.current = setTimeout(restart, 6000)
  }

  // Derived animation state
  const ratio = t / DURATION
  const atpShow = clamp((t - 2.5) / 0.6)
  const wordIdx = Math.floor((t - 1) / (8 / CAPTION.length))
  const quizShown = t >= DURATION - 0.05

  const wordClass = (i) => {
    if (t < 1) return ''
    if (i < wordIdx) return 'done'
    if (i === wordIdx) return t < 9 ? 'on' : 'done'
    return ''
  }

  return (
    <div className="sh-stage">
      <div className="sh-note">
        Source: NCERT Biology, Class 11
        <small>Photosynthesis in Higher Plants</small>
      </div>

      <div className="sh-device">
        <div className="sh-screen">
          <svg viewBox="0 0 640 400" role="img" aria-label="Animated diagram: light hits thylakoid discs and ATP moves to the stroma">
            <defs>
              <linearGradient id="sh-tg" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#6d7cff" />
                <stop offset="1" stopColor="#2fd0f0" />
              </linearGradient>
            </defs>
            <rect width="640" height="400" fill="#12141d" />
            <g stroke="#ffd95e" strokeWidth="6" strokeLinecap="round" opacity={clamp((t - 0.3) / 0.8)}>
              <path d="M60 40l64 64M104 20l64 64M148 4l64 64" />
            </g>
            <g fill="url(#sh-tg)" opacity={clamp((t - 0.8) / 0.8)}>
              {[100, 138, 176, 214].map((y) => (
                <rect key={y} x="250" y={y} width="190" height="26" rx="13" />
              ))}
            </g>
            <text x="345" y="268" fill="#9ea3c4" fontSize="15" textAnchor="middle" fontFamily="Inter,sans-serif">
              thylakoid membranes
            </text>
            <ellipse
              pathLength="1" cx="345" cy="170" rx="122" ry="86" fill="none"
              stroke="#ff566c" strokeWidth="5" strokeLinecap="round" strokeDasharray="1"
              strokeDashoffset={1 - clamp((t - 4.2) / 1.2)}
              transform="rotate(-4 345 170)"
            />
            <g fill="#ff7b93">
              {Array.from({ length: ATP_COUNT }, (_, i) => {
                const p = (t * 0.45 + i / ATP_COUNT) % 1
                return (
                  <circle key={i} r="9" cx={430 + p * 95} cy={112 + (i % 4) * 38}
                    opacity={atpShow * Math.sin(Math.PI * p)} />
                )
              })}
            </g>
            <text x="545" y="150" fill="#9ea3c4" fontSize="14" textAnchor="middle" fontFamily="Inter,sans-serif" opacity={atpShow}>
              Stroma:
            </text>
            <text x="545" y="168" fill="#fff" fontSize="14" fontWeight="700" textAnchor="middle" fontFamily="Inter,sans-serif" opacity={atpShow}>
              Calvin cycle
            </text>
          </svg>
          <div className="sh-caps" aria-hidden="true">
            {CAPTION.map((w, i) => (
              <React.Fragment key={i}>
                <b className={wordClass(i)}>{w}</b>{' '}
              </React.Fragment>
            ))}
          </div>
        </div>

        <div className="sh-ctl">
          <button type="button" className="sh-pp" onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? '❚❚' : '▶'}
          </button>
          <div
            ref={trackRef} className="sh-trk" role="slider" tabIndex={0}
            aria-label="Video position" aria-valuemin={0} aria-valuemax={100}
            aria-valuenow={Math.round(ratio * 100)}
            onClick={onTrackClick} onKeyDown={onTrackKey}
          >
            <div><i style={{ width: `${ratio * 100}%` }} /></div>
          </div>
          <span className="sh-time">{fmt(Math.round(ratio * SHOWN_SECONDS))} / {fmt(SHOWN_SECONDS)}</span>
        </div>
        <div className="sh-chap">
          <strong>How the light reactions make ATP</strong>
          Biology · Class 11 · Video 3 of 8
        </div>
      </div>

      <div className={`sh-quiz${quizShown ? ' show' : ''}`} aria-live="polite" aria-hidden={!quizShown}>
        <p>Quick check</p>
        <h4>Where in the chloroplast do the light reactions take place?</h4>
        {OPTIONS.map((txt, i) => {
          let cls = 'sh-opt'
          if (answer !== null && i === CORRECT) cls += ' right'
          if (answer === i && i !== CORRECT) cls += ' wrong'
          return (
            <button key={txt} type="button" className={cls} disabled={answer !== null || !quizShown} onClick={() => choose(i)}>
              {txt}
            </button>
          )
        })}
        <div className="sh-fb">
          {answer === null ? '' : answer === CORRECT
            ? 'Correct. ATP and NADPH form here.'
            : 'Not quite. The stroma runs the Calvin cycle. Rewatch at 0:42.'}
        </div>
      </div>
    </div>
  )
}


/* ------------------------------------------------------------------ */
/* Content                                                             */
/* ------------------------------------------------------------------ */
const STATS = [
  ['1,200', '+', 'explainer videos'],
  ['230', '', 'NCERT chapters'],
  ['100', '%', 'cited to the book'],
  ['48k', '', 'aspirants learning'],
]

const STEPS = [
  ['01', 'Choose', 'Choose your topic', 'Search any NCERT chapter: Biology, Physics or Chemistry, Class 11 and 12.', 'pick a chapter →'],
  ['02', 'Watch', 'Watch the explainer', 'A 3-minute annotated video breaks the concept down, with every line cited.', 'watch →'],
  ['03', 'Prove', 'Test with a quiz', 'NEET-style MCQs with instant explanations, then it tracks your mastery.', 'lock it in'],
]

const QUIZ_OPTIONS = ['On the thylakoid membranes', 'In the stroma', 'In the mitochondrial matrix', 'On the outer chloroplast membrane']
const QUIZ_CORRECT = 0

const FAQ = [
  ['Is the content really from NCERT?', 'Yes. Every video and answer is generated from, and cited to, the official NCERT textbooks for Class 11 and 12. You can open the exact source line any time.'],
  ['Which subjects are covered?', 'Biology, Physics and Chemistry: the full NEET syllabus across Class 11 and 12, with new chapters added weekly.'],
  ['How long are the videos?', 'Most explainers run 2 to 4 minutes and focus on a single concept, so you can revise a whole chapter in one sitting.'],
  ['Can I use it for free?', 'Yes. Three chapters a month are free.'],
]

const PANELS = ['Intro', 'Thesis', 'Grounded', 'How it works', 'Features', 'Study Plan', 'Quiz', 'Progress', 'FAQ']


/* ------------------------------------------------------------------ */
/* Small pieces                                                        */
/* ------------------------------------------------------------------ */
function Marker({ children }) {
  return (
    <span className="hs-marker">
      {children}
      <svg viewBox="0 0 300 20" preserveAspectRatio="none" aria-hidden="true">
        <path pathLength="1" d="M4 12 C90 5 210 5 296 10" />
      </svg>
    </span>
  )
}

function Eyebrow({ children }) {
  return <p className="hs-eyebrow">{children}</p>
}

function QuizPanel() {
  const [picked, setPicked] = useState(null)
  return (
    <div className="hs-quizcard rv">
      <div className="hs-quizhead"><span>Biology · Photosynthesis</span><span>Q3 / 10</span></div>
      <h3>In higher plants, where exactly are ATP and NADPH made during the light reaction?</h3>
      <div className="hs-quizopts">
        {QUIZ_OPTIONS.map((txt, i) => {
          let cls = 'hs-qopt'
          if (picked !== null) {
            if (i === QUIZ_CORRECT) cls += ' right'
            else if (i === picked) cls += ' wrong'
            else cls += ' dim'
          }
          return (
            <button key={txt} type="button" className={cls} disabled={picked !== null} onClick={() => setPicked(i)}>
              <span className="hs-qletter">{'ABCD'[i]}</span>
              <span>{txt}</span>
            </button>
          )
        })}
      </div>
      <div className="hs-quizexp" aria-live="polite">
        {picked !== null && (
          <>
            <strong>{picked === QUIZ_CORRECT ? 'Correct.' : 'Not quite.'}</strong> The light reactions happen on the thylakoid
            membranes, where ATP and NADPH are made. The stroma is where the Calvin cycle then uses them.
            <em> (NCERT Biology, Class 11, Ch. 11)</em>{' '}
            <button type="button" className="hs-link" onClick={() => setPicked(null)}>Try again</button>
          </>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Horizontal scroll: vertical scrolling moves a row of full-height    */
/* panels sideways. Below 1024px wide (or very short screens) the      */
/* panels simply stack and the page scrolls normally.                  */
/* ------------------------------------------------------------------ */
const WIDE_QUERY = '(min-width: 1024px) and (min-height: 560px)'

function useHorizontalScroll(outerRef, frameRef, trackRef, barRef, onIndex) {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE_QUERY).matches)

  useEffect(() => {
    const mq = window.matchMedia(WIDE_QUERY)
    const onChange = () => setWide(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    const outer = outerRef.current
    const frame = frameRef.current
    const track = trackRef.current
    if (!outer || !frame || !track) return undefined

    if (!wide) {
      outer.style.height = ''
      track.style.transform = ''
      return undefined
    }

    let dist = 0
    let start = 0
    let raf = 0
    let lastIdx = -1
    const panels = () => [...track.children]

    const measure = () => {
      const header = document.querySelector('.navbar')
      const hdr = header ? header.offsetHeight : 0
      frame.style.top = `${hdr}px`
      frame.style.height = `calc(100dvh - ${hdr}px)`
      dist = Math.max(0, track.scrollWidth - frame.clientWidth)
      outer.style.height = `${dist + frame.clientHeight}px`
      start = outer.getBoundingClientRect().top + window.scrollY - hdr
      update()
    }

    const update = () => {
      raf = 0
      const y = Math.min(dist, Math.max(0, window.scrollY - start))
      track.style.transform = `translate3d(${-y}px, 0, 0)`
      if (barRef.current) barRef.current.style.transform = `scaleX(${dist ? y / dist : 0})`
      // Reveal panels as they slide in; active panel = the one under the middle of the screen.
      const w = frame.clientWidth
      panels().forEach((el) => {
        if (el.offsetLeft < y + w * 0.8 && el.offsetLeft + el.offsetWidth > y) el.classList.add('seen')
      })
      const mid = y + w / 2
      const idx = panels().findIndex((el) => el.offsetLeft <= mid && el.offsetLeft + el.offsetWidth > mid)
      if (idx !== -1 && idx !== lastIdx) {
        lastIdx = idx
        onIndex(idx)
      }
    }

    const onScroll = () => { if (!raf) raf = requestAnimationFrame(update) }

    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(track)
    ro.observe(frame)
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', measure)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', measure)
    }
  }, [wide, outerRef, frameRef, trackRef, barRef, onIndex])

  return wide
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */
export default function LandingPage() {
  const nav = useNavigate()
  const [active, setActive] = useState(0)

  const outerRef = useRef(null)
  const frameRef = useRef(null)
  const trackRef = useRef(null)
  const barRef = useRef(null)
  const onIndex = useCallback((i) => setActive(i), [])
  const wide = useHorizontalScroll(outerRef, frameRef, trackRef, barRef, onIndex)

  // Stacked layout: fade content in as each panel scrolls into view.
  // (The sideways layout reveals panels from its scroll handler instead.)
  useEffect(() => {
    if (wide) return undefined
    const els = trackRef.current ? [...trackRef.current.children] : []
    if (!('IntersectionObserver' in window)) {
      els.forEach((el) => el.classList.add('seen'))
      return undefined
    }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add('seen')
          io.unobserve(e.target)
        }
      }),
      { threshold: 0.12 },
    )
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [wide])

  // Jump to a panel from the dots in the bottom bar.
  const goToPanel = (i) => {
    const el = trackRef.current?.children[i]
    if (!el) return
    if (wide) {
      const hdr = document.querySelector('.navbar')?.offsetHeight || 0
      const start = outerRef.current.getBoundingClientRect().top + window.scrollY - hdr
      window.scrollTo({ top: start + el.offsetLeft, behavior: 'smooth' })
    } else {
      el.scrollIntoView({ behavior: 'smooth' })
    }
  }

  return (
    <>
      <IntroLoader />
      <div className={`hs${wide ? ' hs-wide' : ''}`} ref={outerRef}>
        <div className="hs-frame" ref={frameRef}>
          <div className="hs-track" ref={trackRef}>
            {/* 01 · Intro (unchanged split hero) */}
            <section className="hp hp-hero" aria-label="Intro">
              <div className="sh">
                <div className="sh-left">
                  <p className="sh-kicker">NCERT · Class 11 &amp; 12 · NEET</p>
                  <h1 className="sh-title">
                    <span>Textbook-grounded</span>
                    <span>
                      <em className="sh-ul">
                        AI video
                        <svg viewBox="0 0 300 20" preserveAspectRatio="none" aria-hidden="true">
                          <path pathLength="1" d="M3 14 C70 4 150 6 297 8 M12 17 C90 9 190 13 285 10" />
                        </svg>
                      </em>{' '}
                      assistant.
                    </span>
                  </h1>
                  <p className="sh-lede">
                    Turn dense NCERT textbook chapters into short, clear explainer videos and quizzes for NEET preparation.
                  </p>
                  <div className="sh-cta">
                    <button type="button" onClick={() => nav('/search')} className="btn-primary sh-btn">
                      Search topics
                    </button>
                    <Link to="/dashboard" className="sh-alt">View my progress →</Link>
                  </div>
                </div>
                <div className="sh-right" aria-label="Sample video">
                  <SampleVideo />
                </div>
              </div>
            </section>

            {/* 02 · Thesis */}
            <section className="hp hp-dark hp-thesis" aria-label="What TextbookAI does">
              <div className="hp-in">
                <p className="hs-statement rv">
                  Every sentence a video says maps to a specific line in NCERT. Tap any claim to jump to the page it came
                  from, so what you learn is <Marker>exactly what the exam tests.</Marker>
                </p>
                <div className="hs-stats rv">
                  {STATS.map(([n, suf, label], i) => (
                    <div key={label} className="hs-stat">
                      <span className={`hs-stat-n${i === 0 ? ' boxed' : ''}`}>{n}<b>{suf}</b></span>
                      <span className="hs-stat-l">{label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            {/* 03 · Grounded */}
            <section className="hp hp-grounded" aria-label="The grounded difference">
              <div className="hp-in hp-split">
                <div className="rv">
                  <Eyebrow>The grounded difference</Eyebrow>
                  <h2 className="hs-h2">No hallucinations.<br />Just your textbook, explained.</h2>
                  <ul className="hs-ticks">
                    <li>Inline citations on every statement</li>
                    <li>Side-by-side book view with highlights</li>
                    <li>Flagged when something goes beyond the syllabus</li>
                  </ul>
                </div>
                <div className="hs-cite rv">
                  <p>
                    In the light reactions, water is split to release <mark>oxygen</mark>, and the energy carriers{' '}
                    <mark>ATP</mark> and <mark>NADPH</mark> are produced for the Calvin cycle.
                  </p>
                  <div className="hs-cite-src">
                    <span className="hs-check" aria-hidden="true">✓</span>
                    <div>
                      <strong>Traced to NCERT Biology · Ch. 11</strong>
                      <span>“Photosynthesis in Higher Plants”, p. 172. Line highlighted in your book view.</span>
                    </div>
                  </div>
                  <span className="hs-hand">every claim ✓</span>
                </div>
              </div>
            </section>

            {/* 04 · How it works: three tall stripes */}
            <section className="hp hp-steps" aria-label="How it works">
              <div className="hs-steps-head hp-dark">
                <Eyebrow>How it works</Eyebrow>
                <h2 className="hs-h2">From chapter to confident <Marker>in minutes</Marker></h2>
              </div>
              {STEPS.map(([num, word, title, body, note], i) => (
                <div key={num} className={`hs-stripe${i % 2 ? '' : ' hp-dark'}`}>
                  <span className="hs-stripe-word" aria-hidden="true">{word}</span>
                  <div className="hs-stripe-body">
                    <span className="hs-stripe-num">{num}</span>
                    <h3>{title}</h3>
                    <p>{body}</p>
                    <span className="hs-hand">{note}</span>
                  </div>
                </div>
              ))}
            </section>

            {/* 05 · Features bento */}
            <section className="hp hp-features" aria-label="Features">
              <div className="hp-in">
                <div className="rv">
                  <Eyebrow>Everything in one place</Eyebrow>
                  <h2 className="hs-h2">Built for how you actually revise</h2>
                </div>
                <div className="hs-bento rv">
                  <div className="hs-tile hs-tile-big">
                    <span className="hs-sticky">p.172 ✓</span>
                    <div>
                      <span className="hs-tag">Grounded</span>
                      <h3>Every fact carries its citation</h3>
                      <p>Tap any sentence to open the exact NCERT line in a side-by-side reader. Trust what you memorise.</p>
                    </div>
                    <div className="hs-chips"><span>ATP · p.172</span><span>Calvin cycle · p.175</span><span>NADPH · p.173</span></div>
                  </div>
                  <div className="hs-tile"><span className="hs-ico">▶</span><div><h3>Short explainers</h3><p>3-minute videos, not 40-minute lectures.</p></div></div>
                  <div className="hs-tile"><span className="hs-ico">✓</span><div><h3>Adaptive quizzes</h3><p>Harder where you’re weak.</p></div></div>
                  <div className="hs-tile hs-tile-streak"><span className="hs-ico-lg">🔥</span><div><h3>Streaks &amp; XP</h3><p>Daily goals that stick.</p></div></div>
                  <div className="hs-tile"><span className="hs-ico">▮▮</span><div><h3>Progress tracking</h3><p>Mastery per chapter.</p></div></div>
                  <div className="hs-tile"><span className="hs-ico">?</span><div><h3>Ask-a-doubt</h3><p>Answers cite the book too.</p></div></div>
                </div>
              </div>
            </section>

            {/* 06 · Study plan: NCERT chapter trajectory */}
            <section className="hp hp-plan" aria-label="Study plan">
              <StudyPlan />
            </section>

            {/* 07 · Quiz */}
            <section className="hp hp-quiz" aria-label="Try a question">
              <div className="hp-in hp-split">
                <div className="rv">
                  <Eyebrow>Try a question</Eyebrow>
                  <h2 className="hs-h2">Learn it, then <Marker>prove it</Marker></h2>
                  <p className="hs-lede">NEET-style MCQs with instant, cited explanations. Every attempt feeds your mastery map, so you always know what to revise next.</p>
                  <p className="hs-hand hs-hand-lg">↓ go on, tap an answer</p>
                </div>
                <QuizPanel />
              </div>
            </section>

            {/* 08 · Progress */}
            <section className="hp hp-dark hp-progress" aria-label="Your progress">
              <div className="hp-in">
                <div className="rv">
                  <Eyebrow>Your progress</Eyebrow>
                  <h2 className="hs-h2">A dashboard that keeps you honest</h2>
                </div>
                <div className="hs-dash rv">
                  <div className="hs-dcard">
                    <p className="hs-dlabel">Current streak</p>
                    <div className="hs-streak-n">7 <span>🔥</span></div>
                    <div className="hs-days">{Array.from({ length: 8 }, (_, i) => <span key={i} className={i < 7 ? 'on' : ''} />)}</div>
                    <p className="hs-dnote">Mon–Sun · 1 more for an 8-day streak</p>
                  </div>
                  <div className="hs-dcard">
                    <p className="hs-dlabel">Subject mastery</p>
                    {[['Biology', 82], ['Chemistry', 64], ['Physics', 48]].map(([s, v]) => (
                      <div key={s} className="hs-meter">
                        <div><span>{s}</span><b>{v}%</b></div>
                        <i><em style={{ width: `${v}%` }} /></i>
                      </div>
                    ))}
                  </div>
                  <div className="hs-dcard">
                    <p className="hs-dlabel">This week</p>
                    <div className="hs-bars">{[40, 65, 30, 90, 70, 55, 25].map((h, i) => <span key={i} style={{ height: `${h}%`, opacity: 0.3 + h / 140 }} />)}</div>
                    <p className="hs-dnote"><b>320 XP</b> earned · 18 videos · 6 quizzes</p>
                  </div>
                </div>
                <Link to="/dashboard" className="hs-arrow-link rv">Open my dashboard →</Link>
              </div>
            </section>

            {/* 09 · FAQ + sign-off */}
            <section className="hp hp-faq" aria-label="Questions">
              <div className="hp-in hp-split">
                <div className="rv">
                  <h2 className="hs-h2">Questions, answered</h2>
                  <p className="hs-lede">Textbook-grounded explainer videos and quizzes for NEET. Made for NCERT Class 11 and 12.</p>
                  <p className="hs-hand hs-hand-lg">keep that streak alive 🔥</p>
                  <p className="hs-copy">© 2026 TextbookAI · Built for NEET 2026</p>
                </div>
                <div className="hs-faq rv">
                  {FAQ.map(([q, a]) => (
                    <details key={q}>
                      <summary>{q}<span aria-hidden="true">+</span></summary>
                      <p>{a}</p>
                    </details>
                  ))}
                </div>
              </div>
            </section>
          </div>

          {wide && (
            <div className="hs-bar">
              <Link to="/search" className="hs-bar-cta">Search topics <span aria-hidden="true">⟶</span></Link>
              <div className="hs-bar-dots" role="navigation" aria-label="Sections">
                {PANELS.map((label, i) => (
                  <button
                    key={label} type="button" className={i === active ? 'on' : ''}
                    aria-label={label} aria-current={i === active ? 'true' : undefined} title={label}
                    onClick={() => goToPanel(i)}
                  />
                ))}
              </div>
              <span className="hs-bar-count">
                <b>{String(active + 1).padStart(2, '0')}</b>/{String(PANELS.length).padStart(2, '0')}
                <span className="hs-bar-label">{PANELS[active]}</span>
                <span className="hs-bar-hint">{active === PANELS.length - 1 ? 'End' : 'Scroll ↓'}</span>
              </span>
              <span className="hs-bar-progress"><i ref={barRef} /></span>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
