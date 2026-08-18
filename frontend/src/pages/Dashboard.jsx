import React, { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { getDashboard, listVideos } from '../services/api'

export default function Dashboard() {
  const { user } = useAuth()
  const [data, setData] = useState(null)
  const [videos, setVideos] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!user) return
    Promise.all([getDashboard(user.id), listVideos()])
      .then(([dashboardRes, videosRes]) => {
        setData(dashboardRes.data)
        setVideos(videosRes.data.videos || [])
        setError(null)
      })
      .catch((err) => { setError(err.response?.data?.detail || err.message); setData(null) })
  }, [user])

  return (
    <div>
      <h2>Student Dashboard</h2>
      {error && <div className="error">Error: {error}</div>}
      <div className="card">{data ? JSON.stringify(data) : 'No dashboard data (loading...)'}</div>
      <h3>Your Videos</h3>
      <div className="card">
        {videos.length === 0 ? 'No videos yet.' : (
          <ul>
            {videos.map((video) => (
              <li key={video.job_id}>{video.topic} - {video.status}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
