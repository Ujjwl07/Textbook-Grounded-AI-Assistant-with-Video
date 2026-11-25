import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

// Quick topic search that drops down from the header. Submitting opens the
// Search page with the topic (and, for suggestions, subject and class) filled in.
const SUGGESTIONS = [
  { topic: 'Laws of Motion', subject: 'physics', classLevel: '11' },
  { topic: 'Chemical Bonding', subject: 'chemistry', classLevel: '11' },
  { topic: 'Photosynthesis', subject: 'biology', classLevel: '11' },
  { topic: 'Cell Cycle', subject: 'biology', classLevel: '11' },
]

export default function HeaderSearch({ onClose }) {
  const [topic, setTopic] = useState('')
  const inputRef = useRef(null)
  const panelRef = useRef(null)
  const nav = useNavigate()

  useEffect(() => {
    inputRef.current?.focus()
    const onKey = (e) => e.key === 'Escape' && onClose()
    const onDown = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target) && !e.target.closest('.nav-search-btn')) onClose()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [onClose])

  const go = (params) => {
    nav(`/search?${new URLSearchParams(params).toString()}`)
    onClose()
  }

  const onSubmit = (e) => {
    e.preventDefault()
    const t = topic.trim()
    const match = SUGGESTIONS.find((s) => s.topic.toLowerCase() === t.toLowerCase())
    if (match) go({ topic: match.topic, subject: match.subject, class: match.classLevel })
    else if (t) go({ topic: t })
  }

  return (
    <div className="header-search" id="header-search" ref={panelRef} role="search">
      <form onSubmit={onSubmit} className="header-search-row">
        <label htmlFor="header-search-input" className="sr-only">Search a topic</label>
        <input
          id="header-search-input"
          ref={inputRef}
          className="header-search-input"
          type="search"
          placeholder="Search a topic, e.g. Cell Cycle"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          autoComplete="off"
        />
        <button type="submit" className="header-search-submit">Search</button>
      </form>
      <div className="header-search-chips" aria-label="Suggested topics">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.topic}
            type="button"
            className="header-chip"
            onClick={() => go({ topic: s.topic, subject: s.subject, class: s.classLevel })}
          >
            {s.topic}
          </button>
        ))}
      </div>
    </div>
  )
}
