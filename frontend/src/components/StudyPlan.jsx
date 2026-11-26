import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

// Official NCERT chapter order (rationalised syllabus). Titles match the books
// indexed in the textbook library, so "Start this chapter" finds them.
export const NCERT = {
  physics: {
    label: 'Physics',
    '11': ['Units and Measurement', 'Motion in a Straight Line', 'Motion in a Plane', 'Laws of Motion', 'Work, Energy and Power',
      'System of Particles and Rotational Motion', 'Gravitation', 'Mechanical Properties of Solids', 'Mechanical Properties of Fluids',
      'Thermal Properties of Matter', 'Thermodynamics', 'Kinetic Theory', 'Oscillations', 'Waves'],
    '12': ['Electric Charges and Fields', 'Electrostatic Potential and Capacitance', 'Current Electricity', 'Moving Charges and Magnetism',
      'Magnetism and Matter', 'Electromagnetic Induction', 'Alternating Current', 'Electromagnetic Waves', 'Ray Optics and Optical Instruments',
      'Wave Optics', 'Dual Nature of Radiation and Matter', 'Atoms', 'Nuclei', 'Semiconductor Electronics'],
  },
  chemistry: {
    label: 'Chemistry',
    '11': ['Some Basic Concepts of Chemistry', 'Structure of Atom', 'Classification of Elements and Periodicity in Properties',
      'Chemical Bonding and Molecular Structure', 'Thermodynamics', 'Equilibrium', 'Redox Reactions',
      'Organic Chemistry - Some Basic Principles and Techniques', 'Hydrocarbons'],
    '12': ['Solutions', 'Electrochemistry', 'Chemical Kinetics', 'The d- and f-Block Elements', 'Coordination Compounds',
      'Haloalkanes and Haloarenes', 'Alcohols, Phenols and Ethers', 'Aldehydes, Ketones and Carboxylic Acids', 'Amines', 'Biomolecules'],
  },
  biology: {
    label: 'Biology',
    '11': ['The Living World', 'Biological Classification', 'Plant Kingdom', 'Animal Kingdom', 'Morphology of Flowering Plants',
      'Anatomy of Flowering Plants', 'Structural Organisation in Animals', 'Cell: The Unit of Life', 'Biomolecules', 'Cell Cycle and Cell Division',
      'Photosynthesis in Higher Plants', 'Respiration in Plants', 'Plant Growth and Development', 'Breathing and Exchange of Gases',
      'Body Fluids and Circulation', 'Excretory Products and their Elimination', 'Locomotion and Movement', 'Neural Control and Coordination',
      'Chemical Coordination and Integration'],
    '12': ['Sexual Reproduction in Flowering Plants', 'Human Reproduction', 'Reproductive Health', 'Principles of Inheritance and Variation',
      'Molecular Basis of Inheritance', 'Evolution', 'Human Health and Disease', 'Microbes in Human Welfare', 'Biotechnology: Principles and Processes',
      'Biotechnology and its Applications', 'Organisms and Populations', 'Ecosystem', 'Biodiversity and Conservation'],
  },
}
// Chapters the textbook library has indexed (videos and quizzes work for these).
// Physics Class 12 Part 2 (chapters 9-14) is not in the library yet.
export const INDEXED_UPTO = { 'physics-12': 8 }

const SUBJECT_ICONS = {
  physics: <svg viewBox="0 0 48 48" fill="none"><ellipse cx="24" cy="24" rx="16" ry="6.5" stroke="currentColor" strokeWidth="2.4" /><ellipse cx="24" cy="24" rx="16" ry="6.5" stroke="currentColor" strokeWidth="2.4" transform="rotate(60 24 24)" /><ellipse cx="24" cy="24" rx="16" ry="6.5" stroke="currentColor" strokeWidth="2.4" transform="rotate(120 24 24)" /><circle cx="24" cy="24" r="4" fill="currentColor" /></svg>,
  chemistry: <svg viewBox="0 0 48 48" fill="none"><path d="M20 9h8v10l6 13a3.5 3.5 0 0 1-3.2 4.9H17.2A3.5 3.5 0 0 1 14 32l6-13V9z" stroke="currentColor" strokeWidth="2.4" /><path d="M17 28h14" stroke="currentColor" strokeWidth="2.4" /></svg>,
  biology: <svg viewBox="0 0 48 48" fill="none"><path d="M16 10c0 9 16 10 16 19s-16 10-16 19" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" /><path d="M32 10c0 9-16 10-16 19s16 10 16 19" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" /><path d="M18 15h12M19 23h10M19 31h10M18 38h12" stroke="currentColor" strokeWidth="2" /></svg>,
}

const GAP = 360      // px between chapter pins
const PAD = 120      // px before the first pin
const AMP = 48       // wave height
const BASE_Y = 0.36  // line height as a fraction of the track
const STORE = 'textbookai-study-plan'

function readSaved() {
  try {
    const v = JSON.parse(localStorage.getItem(STORE) || 'null')
    return v && NCERT[v.subject] && (v.cls === '11' || v.cls === '12') ? v : null
  } catch {
    return null
  }
}

export default function StudyPlan() {
  const saved = readSaved()
  const [cls, setCls] = useState(saved?.cls || null)
  const [subject, setSubject] = useState(saved?.subject || null)
  const [plan, setPlan] = useState(null) // { subject, cls } once drawn
  const [height, setHeight] = useState(0)
  const [active, setActive] = useState(0)
  const [shown, setShown] = useState(() => new Set([0]))
  const viewportRef = useRef(null)
  const pathRef = useRef(null)
  const fillRef = useRef(null)
  const lengthRef = useRef(1)

  const chapters = plan ? NCERT[plan.subject][plan.cls] : []
  const n = chapters.length
  const width = n ? PAD * 2 + (n - 1) * GAP + 340 : 0
  const lineY = height * BASE_Y
  const yAt = (x) => lineY + AMP * Math.sin(x / 430)
  const indexedUpto = plan ? INDEXED_UPTO[`${plan.subject}-${plan.cls}`] ?? n : n

  let d = ''
  if (n && height) {
    for (let x = 0; x <= width; x += 18) d += `${x === 0 ? 'M' : 'L'} ${x} ${yAt(x).toFixed(1)} `
  }

  // Track height follows the panel.
  useLayoutEffect(() => {
    const el = viewportRef.current
    if (!el) return undefined
    const ro = new ResizeObserver(() => setHeight(el.clientHeight))
    ro.observe(el)
    setHeight(el.clientHeight)
    return () => ro.disconnect()
  }, [plan])

  // Scroll position -> active chapter, line drawn up to just past it, progress bar.
  const update = useCallback(() => {
    const vp = viewportRef.current
    if (!vp || !n) return
    // The "you are here" point moves from the first pin (scrolled to the
    // start) to the last pin (scrolled to the end), so both ends are reachable.
    const maxScroll = Math.max(1, vp.scrollWidth - vp.clientWidth)
    const progress = Math.min(1, vp.scrollLeft / maxScroll)
    const focus = vp.scrollLeft + PAD + progress * (vp.clientWidth - PAD * 2)
    let best = 0
    let bestDist = Infinity
    for (let i = 0; i < n; i += 1) {
      const dist = Math.abs(PAD + i * GAP - focus)
      if (dist < bestDist) { bestDist = dist; best = i }
    }
    setActive(best)
    // Reveal every chapter that has come into view (they stay revealed).
    const right = vp.scrollLeft + vp.clientWidth * 0.94
    setShown((prev) => {
      let changed = false
      const next = new Set(prev)
      for (let i = 0; i < n; i += 1) if (PAD + i * GAP < right && !next.has(i)) { next.add(i); changed = true }
      return changed ? next : prev
    })
    const path = pathRef.current
    if (path) {
      const headX = Math.min(PAD + best * GAP + GAP * 0.45, width)
      const frac = Math.max(0.03, Math.min(headX / width, 1))
      path.style.strokeDashoffset = String(lengthRef.current * (1 - frac))
    }
    const max = vp.scrollWidth - vp.clientWidth
    if (fillRef.current) fillRef.current.style.transform = `scaleX(${max > 0 ? vp.scrollLeft / max : 0})`
  }, [n, width])

  // After the path is drawn, measure it for the dash animation.
  useLayoutEffect(() => {
    const path = pathRef.current
    if (!path) return
    const len = path.getTotalLength() || 1
    lengthRef.current = len
    path.style.strokeDasharray = String(len)
    path.style.strokeDashoffset = String(len)
    requestAnimationFrame(update)
  }, [d, update])

  // Scrolling: the wheel moves along the trajectory while it can. At either end
  // the event is left alone, so the home page keeps scrolling past this panel.
  useEffect(() => {
    const vp = viewportRef.current
    if (!vp || !plan) return undefined
    let raf = 0
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; update() }) }
    const onWheel = (e) => {
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY
      const max = vp.scrollWidth - vp.clientWidth
      const canMove = (delta > 0 && vp.scrollLeft < max - 1) || (delta < 0 && vp.scrollLeft > 1)
      if (!canMove) return
      e.preventDefault()
      e.stopPropagation()
      vp.scrollLeft += delta
    }
    // Drag to scroll with a mouse.
    let down = false
    let startX = 0
    let startLeft = 0
    const onDown = (e) => {
      if (e.pointerType !== 'mouse' || e.target.closest('a,button')) return
      down = true; startX = e.clientX; startLeft = vp.scrollLeft; vp.classList.add('dragging')
    }
    const onMove = (e) => { if (down) vp.scrollLeft = startLeft - (e.clientX - startX) }
    const onUp = () => { down = false; vp.classList.remove('dragging') }
    vp.addEventListener('scroll', onScroll, { passive: true })
    vp.addEventListener('wheel', onWheel, { passive: false })
    vp.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      cancelAnimationFrame(raf)
      vp.removeEventListener('scroll', onScroll)
      vp.removeEventListener('wheel', onWheel)
      vp.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [plan, update])

  function draw() {
    if (!cls || !subject) return
    try { localStorage.setItem(STORE, JSON.stringify({ cls, subject })) } catch { /* fine: just not remembered */ }
    setActive(0)
    setShown(new Set([0]))
    setPlan({ cls, subject })
    requestAnimationFrame(() => { if (viewportRef.current) viewportRef.current.scrollLeft = 0 })
  }

  const subjectKey = plan?.subject || subject || 'physics'

  return (
    <div className={`sp sp-${subjectKey}${plan ? ' started' : ''}`}>
      <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
        <defs>
          <filter id="sp-rough">
            <feTurbulence type="fractalNoise" baseFrequency="0.012" numOctaves="2" result="n" />
            <feDisplacementMap in="SourceGraphic" in2="n" scale="6" />
          </filter>
        </defs>
      </svg>

      {/* Trajectory */}
      <div className="sp-stage" aria-hidden={!plan}>
        <div className="sp-head">
          <h2 className="sp-title">
            Study Plan
            <svg className="sp-u" viewBox="0 0 400 22" preserveAspectRatio="none" aria-hidden="true">
              <path d="M4 14C120 5 300 6 396 12" filter="url(#sp-rough)" />
            </svg>
          </h2>
          <div className="sp-subrow">
            <span className="sp-chip"><span className="sp-sw" />{plan ? `${NCERT[plan.subject].label} · Class ${plan.cls}` : ''}</span>
            <span className="sp-count">{n ? `${n} chapters · NCERT order` : ''}</span>
            <button type="button" className="sp-change" onClick={() => setPlan(null)}>change</button>
          </div>
        </div>

        <div className="sp-vwrap">
          <div className="sp-viewport" ref={viewportRef} tabIndex={plan ? 0 : -1} aria-label="Chapter trajectory: scroll sideways">
            <div className="sp-track" style={{ width: width || '100%' }}>
              {n > 0 && height > 0 && (
                <svg className="sp-line" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
                  <path className="sp-path-bg" d={d} />
                  <path className="sp-path-fg" d={d} ref={pathRef} />
                </svg>
              )}
              {height > 0 && chapters.map((name, i) => {
                const x = PAD + i * GAP
                const y = yAt(x)
                const available = i < indexedUpto
                return (
                  <div
                    key={`${plan.subject}-${plan.cls}-${i}`}
                    className={`sp-pin${i === active ? ' active' : ''}${shown.has(i) ? ' in' : ''}${available ? '' : ' unavailable'}`}
                    style={{ left: x, height }}
                  >
                    <svg className="sp-mk" style={{ top: y - 56 }} viewBox="0 0 34 64" aria-hidden="true">
                      <ellipse className="sp-blob" cx="17" cy="16" rx="14" ry="15.5" />
                      <rect className="sp-stick" x="16" y="28" width="2" height="34" />
                    </svg>
                    <div className="sp-txt" style={{ top: y + 16 }}>
                      <div className="sp-num">Ch {String(i + 1).padStart(2, '0')} · {NCERT[plan.subject].label.slice(0, 4).toUpperCase()}</div>
                      <h3>{name}</h3>
                      <div className="sp-role">Lesson {i + 1} of {n}</div>
                      <p className="sp-desc">
                        {available
                          ? 'Generate a narrated NCERT video for this chapter, then test yourself with an adaptive quiz.'
                          : 'This chapter isn’t in the textbook library yet, so videos and quizzes can’t be made for it.'}
                      </p>
                      {available && (
                        <Link
                          className="sp-go"
                          to={`/search?${new URLSearchParams({ topic: name, subject: plan.subject, class: plan.cls })}`}
                          tabIndex={i === active ? 0 : -1}
                        >
                          Start this chapter →
                        </Link>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
          <div className="sp-fade l" aria-hidden="true" />
          <div className="sp-fade r" aria-hidden="true" />
        </div>

        <div className="sp-bot">
          <span className="sp-bar"><i ref={fillRef} /></span>
          <span className="sp-bot-l">Chapter <b>{String(active + 1).padStart(2, '0')}</b> / {String(n).padStart(2, '0')}</span>
          <span className="sp-bot-r">Scroll or drag →</span>
        </div>
      </div>

      {/* Picker */}
      <div className="sp-picker" aria-hidden={!!plan}>
        <div className="sp-pcard" role="group" aria-label="Build your study plan">
          <span className="sp-eyebrow">Build your roadmap</span>
          <h2>Where are you headed?</h2>
          <p className="sp-sub">Pick your class and subject. We’ll draw the full NCERT chapter trajectory for you to travel.</p>

          <span className="sp-plabel" id="sp-class-l">Class</span>
          <div className="sp-prow" role="radiogroup" aria-labelledby="sp-class-l">
            {['11', '12'].map((c) => (
              <button key={c} type="button" role="radio" aria-checked={cls === c} tabIndex={plan ? -1 : 0}
                className={`sp-popt cls${cls === c ? ' on' : ''}`} onClick={() => setCls(c)}>
                Class {c}
              </button>
            ))}
          </div>

          <span className="sp-plabel" id="sp-sub-l">Subject</span>
          <div className="sp-prow" role="radiogroup" aria-labelledby="sp-sub-l">
            {Object.keys(NCERT).map((s) => (
              <button key={s} type="button" role="radio" aria-checked={subject === s} tabIndex={plan ? -1 : 0}
                className={`sp-popt sub-${s}${subject === s ? ' on' : ''}`} onClick={() => setSubject(s)}>
                <span className="sp-pi" aria-hidden="true">{SUBJECT_ICONS[s]}</span>{NCERT[s].label}
              </button>
            ))}
          </div>

          <button type="button" className={`sp-start${cls && subject ? ' ready' : ''}`} onClick={draw} disabled={!cls || !subject} tabIndex={plan ? -1 : 0}>
            Draw my trajectory <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    </div>
  )
}
