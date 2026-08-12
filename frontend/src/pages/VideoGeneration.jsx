import React, { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import useWebSocket from '../hooks/useWebSocket'
import { getStatus } from '../services/api'

export default function VideoGeneration() {
  const { jobId } = useParams()
  const [status, setStatus] = useState(null)

  // fallback initial fetch
  useEffect(() => {
    let mounted = true
    async function fetch() {
      try {
        const res = await getStatus(jobId)
        if (!mounted) return
        setStatus(res.data)
      } catch (e) {}
    }
    fetch()
    return () => (mounted = false)
  }, [jobId])

  // subscribe to websocket updates
  useWebSocket(`/ws/${jobId}`, (data) => {
    if (!data) return
    // server may send full JobState or partial updates
    setStatus((prev) => ({ ...(prev || {}), ...data }))
  })

  if (!status) return <div>Connecting...</div>

  return (
    <div>
      <h2>Generation Status</h2>
      <div className="card">Stage: {status.stage} — {status.progress}%</div>
      {status.status === 'completed' && (
        <Link to={`/watch/${jobId}`}>Watch video</Link>
      )}
    </div>
  )
}
