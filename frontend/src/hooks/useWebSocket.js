import { useEffect, useRef, useState } from 'react'
import { WS_BASE_URL } from '../services/api'

export default function useWebSocket(path, onMessage) {
  const wsRef = useRef(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!path) return
    const token = localStorage.getItem('access_token')
    const separator = path.includes('?') ? '&' : '?'
    const url = `${WS_BASE_URL}${path}${token ? `${separator}token=${encodeURIComponent(token)}` : ''}`
    const ws = new WebSocket(url)
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

    return () => {
      try {
        ws.close()
      } catch (e) {}
    }
  }, [path])

  return { ws: wsRef.current, connected }
}
