import React, { useState } from 'react'
import { generateVideo } from '../services/api'
import { useNavigate } from 'react-router-dom'

export default function TopicSearch() {
  const [topic, setTopic] = useState('')
  const nav = useNavigate()

  async function onGenerate() {
    const res = await generateVideo({ topic, subject: 'generic', class_level: 'all' })
    nav(`/generate/${res.data.job_id}`)
  }

  return (
    <div>
      <h2>Topic Search</h2>
      <div className="card">
        <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Enter topic" />
        <button onClick={onGenerate} disabled={!topic}>Generate Video</button>
      </div>
    </div>
  )
}
