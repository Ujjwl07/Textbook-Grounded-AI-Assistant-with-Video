import React, { useEffect, useRef, useState } from 'react'

// Intro: a hand-drawn book doodle draws itself while a big counter
// runs 0 → 100, then the screen lifts away. Skippable, and not shown at all to people who prefer reduced motion.
// It plays on every page load (including refresh), but not again when
// someone clicks back to Home inside the app during the same visit.
const COUNT_MS = 2200
let playedThisLoad = false

function shouldShow() {
  if (playedThisLoad) return false
  try {
    return !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return true
  }
}

export default function IntroLoader() {
  const [show, setShow] = useState(shouldShow)
  const [leaving, setLeaving] = useState(false)
  const countRef = useRef(null)
  const doneRef = useRef(false)

  const finish = () => {
    if (doneRef.current) return
    doneRef.current = true
    playedThisLoad = true
    setLeaving(true)
    setTimeout(() => setShow(false), 750)
  }

  useEffect(() => {
    if (!show) return undefined
    document.documentElement.classList.add('intro-lock')
    const start = performance.now()
    let raf
    let hold
    const tick = (now) => {
      const p = Math.min(1, (now - start) / COUNT_MS)
      const eased = 1 - Math.pow(1 - p, 3)
      if (countRef.current) countRef.current.textContent = String(Math.round(eased * 100))
      if (p < 1) raf = requestAnimationFrame(tick)
      else hold = setTimeout(finish, 350)
    }
    raf = requestAnimationFrame(tick)
    const onKey = (e) => (e.key === 'Escape' || e.key === 'Enter') && finish()
    window.addEventListener('keydown', onKey)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(hold)
      window.removeEventListener('keydown', onKey)
      document.documentElement.classList.remove('intro-lock')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show])

  if (!show) return null

  return (
    <div className={`intro${leaving ? ' leaving' : ''}`} role="status" aria-label="Loading TextbookAI">
      <span className="intro-tl">TextbookAI</span>
      <span className="intro-tr">NEET ’26</span>

      <svg className="intro-doodle" viewBox="0 0 540 420" aria-hidden="true">
        <g className="intro-spray" fill="none" strokeLinecap="round">
          <path pathLength="1" d="M372 92 C400 70 438 64 470 76" strokeWidth="11" />
          <path pathLength="1" d="M388 124 C418 110 452 110 486 122" strokeWidth="11" />
          <path pathLength="1" d="M478 40 L504 26" strokeWidth="10" />
          <path pathLength="1" d="M500 160 L526 172" strokeWidth="10" />
        </g>
        <g className="intro-ink" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <path className="intro-page" pathLength="1" strokeWidth="13"
            d="M266 150 C222 124 160 118 104 134 C100 200 98 270 102 344 C160 330 222 336 266 362 Z" />
          <path className="intro-page" pathLength="1" strokeWidth="13"
            d="M266 150 C310 124 372 118 428 134 C432 200 434 270 430 344 C372 330 310 336 266 362 Z" />
          <path pathLength="1" strokeWidth="9" d="M136 178 C170 170 206 172 236 184" />
          <path pathLength="1" strokeWidth="9" d="M136 212 C168 206 196 208 218 216" />
          <path pathLength="1" strokeWidth="9" d="M296 184 C326 172 362 170 396 178" />
          <path pathLength="1" strokeWidth="9" d="M314 216 C336 208 364 206 396 212" />
        </g>
        <circle className="intro-badge" cx="266" cy="276" r="64" strokeWidth="13" />
        <path className="intro-play" d="M246 244 L246 308 L300 276 Z" />
      </svg>

      <div className="intro-count" aria-hidden="true"><span ref={countRef}>0</span></div>

      <button type="button" className="intro-skip" onClick={finish}>Skip</button>
    </div>
  )
}
