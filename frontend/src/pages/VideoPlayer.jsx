import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { API_BASE_URL, getVideo } from '../services/api'

export default function VideoPlayer() {
  const { jobId } = useParams()
  const [video, setVideo] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getVideo(jobId)
      .then((r) => {
        setVideo(r.data)
        setError(null)
      })
      .catch((err) => {
        setVideo(null)
        setError(err.response?.data?.detail || 'Unable to load video')
      })
  }, [jobId])

  if (error) return <div className="error">Error: {error}</div>
  if (!video) return <div>Loading...</div>

  const videoUrl = buildPlayableUrl(video.video_url)

  return (
    <div>
      <h2>{video.topic}</h2>
      <div className="card">
        <video controls width="100%" src={videoUrl}>
          Your browser does not support the video tag.
        </video>
        <p>
          <a href={videoUrl} target="_blank" rel="noreferrer">Open video</a>
        </p>
      </div>
    </div>
  )
}

function buildPlayableUrl(rawUrl) {
  if (!rawUrl) return ''
  if (/^https?:\/\//i.test(rawUrl)) return rawUrl

  const apiOrigin = new URL(API_BASE_URL).origin
  const url = `${apiOrigin}${rawUrl}`
  const token = localStorage.getItem('access_token')
  if (!token || !rawUrl.startsWith('/api/video-file/')) return url

  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}token=${encodeURIComponent(token)}`
}
