import { useEffect, useRef, useState } from 'react'
import { getToken } from '@clerk/react'
import { WS_BASE_URL } from '../services/api'

export default function useWebSocket(path, onMessage) {
  const wsRef = useRef(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!path) return
    let ws = null
    let cancelled = false

    // Fetch a fresh Clerk token right before connecting; the server checks it
    // once, at connect time.
    getToken()
      .catch(() => null)
      .then((token) => {
        if (cancelled) return
        const separator = path.includes('?') ? '&' : '?'
        const url = `${WS_BASE_URL}${path}${token ? `${separator}token=${encodeURIComponent(token)}` : ''}`
        ws = new WebSocket(url)
        wsRef.current = ws

        ws.onopen = () => setConnected(true)
        ws.onclose = () => setConnected(false)
        ws.onerror = () => setConnected(false)
        ws.onmessage = (evt) => {
          try {
            const data = JSON.parse(evt.data)
            onMessage && onMessage(data)
          } catch (e) {
            onMessage && onMessage(evt.data)
          }
        }
      })

    return () => {
      cancelled = true
      try {
        ws && ws.close()
      } catch (e) {}
    }
  }, [path])

  return { ws: wsRef.current, connected }
}
