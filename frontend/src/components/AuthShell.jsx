import React, { useRef } from 'react'
import AuthIcons from './AuthIcons'

// Shared layout for the sign-in and sign-up pages: drifting colour glows,
// rows of science icons sliding past, and a branded card that holds Clerk's form.
const ROWS = [
  ['ic-cell', 'el-c', 'ic-micro', 'ic-dna', 'ic-force', 'el-o', 'ic-flask', 'ic-atom', 'el-fe'],
  ['ic-dna', 'el-na', 'ic-atom', 'ic-micro', 'el-h', 'ic-force', 'ic-cell', 'el-ca', 'ic-book'],
  ['ic-play', 'ic-flask', 'el-fe', 'ic-force', 'ic-cell', 'el-o', 'ic-dna', 'ic-micro', 'ic-atom'],
]

const SUBJECTS = [
  ['Physics', '#3b82f6'],
  ['Chemistry', '#10b981'],
  ['Biology', '#ef4444'],
]

function LogoMark() {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <rect x="2" y="7" width="28" height="18" rx="3" fill="#fff" />
      <path d="M16 7v18" stroke="#121214" strokeWidth="1.6" />
      <circle cx="16" cy="16" r="6.5" fill="#E11D33" />
      <path d="M14.3 13.2v5.6l4.6-2.8z" fill="#fff" />
    </svg>
  )
}

export default function AuthShell({ title, accent, subtitle, compact = false, children }) {
  const pageRef = useRef(null)
  const cardRef = useRef(null)
  const raf = useRef(0)
  const last = useRef(null)

  // Cursor-driven motion, batched to one update per frame:
  //  - the whole background (glows + icon rows) drifts with the cursor in layers
  //  - the card tilts toward the cursor with a moving glare
  //  - buttons under the cursor get a spotlight and lean slightly toward it
  const apply = () => {
    raf.current = 0
    const e = last.current
    const page = pageRef.current
    const card = cardRef.current
    if (!e || !page || !card) return
    const pr = page.getBoundingClientRect()
    page.style.setProperty('--px', ((e.clientX - pr.left) / pr.width - 0.5).toFixed(3))
    page.style.setProperty('--py', ((e.clientY - pr.top) / pr.height - 0.5).toFixed(3))

    const r = card.getBoundingClientRect()
    const x = (e.clientX - r.left) / r.width
    const y = (e.clientY - r.top) / r.height
    const inside = x >= 0 && x <= 1 && y >= 0 && y <= 1
    card.style.setProperty('--mx', `${x * 100}%`)
    card.style.setProperty('--my', `${y * 100}%`)
    card.style.setProperty('--ry', inside ? `${(x - 0.5) * 8}deg` : '0deg')
    card.style.setProperty('--rx', inside ? `${(0.5 - y) * 8}deg` : '0deg')
    card.classList.toggle('hot', inside)

    const btn = e.target.closest?.('.cl-socialButtonsBlockButton, .cl-formButtonPrimary')
    card.querySelectorAll('.au-magnet').forEach((el) => {
      if (el !== btn) {
        el.classList.remove('au-magnet')
        el.style.removeProperty('translate')
      }
    })
    if (btn) {
      const b = btn.getBoundingClientRect()
      const bx = e.clientX - b.left
      const by = e.clientY - b.top
      btn.classList.add('au-magnet')
      btn.style.setProperty('--bx', `${bx}px`)
      btn.style.setProperty('--by', `${by}px`)
      btn.style.translate = `${((bx / b.width) - 0.5) * 6}px ${((by / b.height) - 0.5) * 4}px`
    }
  }

  const onMove = (e) => {
    if (e.pointerType === 'touch') return
    last.current = e
    if (!raf.current) raf.current = requestAnimationFrame(apply)
  }
  const onLeave = () => {
    const card = cardRef.current
    if (!card) return
    card.style.setProperty('--ry', '0deg')
    card.style.setProperty('--rx', '0deg')
    card.classList.remove('hot')
    pageRef.current?.style.setProperty('--px', '0')
    pageRef.current?.style.setProperty('--py', '0')
  }

  return (
    <div className="auth-page" ref={pageRef} onPointerMove={onMove} onPointerLeave={onLeave}>
      <AuthIcons />
      <div className="auth-glow a" aria-hidden="true" />
      <div className="auth-glow b" aria-hidden="true" />
      <div className="auth-glow c" aria-hidden="true" />

      <div className="auth-belt" aria-hidden="true">
        {ROWS.map((row, r) => (
          <div key={r} className={`auth-belt-layer l${r + 1}`}>
            <div className={`auth-belt-row r${r + 1}`}>
              {[...row, ...row].map((id, i) => (
                <svg key={i} className="auth-tile" style={{ '--i': i }}><use href={`#au-${id}`} /></svg>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="auth-stage">
        <div className={`auth-card${compact ? ' compact' : ''}`} ref={cardRef}>
          <span className="auth-glare" aria-hidden="true" />
          <div className="auth-head au-in" style={{ '--d': 0 }}>
            <div className="auth-logo"><LogoMark /></div>
            <h1 className="auth-title">
              {title}
              {compact ? ' ' : <br />}
              <span>{accent}</span>
            </h1>
          </div>
          <p className="auth-sub au-in" style={{ '--d': 1 }}>{subtitle}</p>
          <div className="auth-karaoke au-in" style={{ '--d': 2 }} aria-hidden="true"><span /><span /><span /><span /><span /></div>

          <div className="au-in" style={{ '--d': 3 }}>{children}</div>

          <div className="auth-chips au-in" style={{ '--d': 4 }} aria-label="Subjects covered">
            {SUBJECTS.map(([name, color]) => (
              <span key={name} className="auth-chip"><i style={{ background: color }} />{name}</span>
            ))}
          </div>
        </div>
      </div>

      <p className="auth-powered">Lessons grounded in the NCERT corpus 📖</p>
    </div>
  )
}

// Clerk styling for the form inside the card: the card itself is ours, so
// Clerk's own card, logo and first-step heading are made invisible.
export const authFormAppearance = {
  options: { socialButtonsVariant: 'blockButton', socialButtonsPlacement: 'top' },
  variables: { borderRadius: '13px' },
  elements: {
    rootBox: { width: '100%' },
    // overflow visible + a few px of padding so button borders and shadows are never clipped
    cardBox: { width: '100%', boxShadow: 'none', border: 'none', background: 'transparent', borderRadius: 0, overflow: 'visible' },
    card: { boxShadow: 'none', border: 'none', background: 'transparent', padding: '3px', gap: '14px', overflow: 'visible' },
    logoBox: { display: 'none' },
    footer: { background: 'transparent', marginTop: '4px' },
    socialButtonsBlockButton: { boxShadow: 'none' },
    formButtonPrimary: { boxShadow: 'none' },
  },
}
