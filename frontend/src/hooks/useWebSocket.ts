import { useEffect, useRef, useCallback } from 'react'
import { useStore } from '../store'

export function useWebSocket() {
  const addLog = useStore((s) => s.addLog)
  const setWsConnected = useStore((s) => s.setWsConnected)
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/logs`)
    wsRef.current = ws

    ws.onopen = () => {
      retryRef.current = 0
      setWsConnected(true)
    }

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        addLog(data)
      } catch {
        addLog({ time: '', message: e.data })
      }
    }

    ws.onerror = () => {
      setWsConnected(false)
    }

    ws.onclose = () => {
      setWsConnected(false)
      wsRef.current = null
      // Exponential backoff: 1s, 2s, 4s, 8s, max 15s
      const delay = Math.min(1000 * Math.pow(2, retryRef.current), 15000)
      retryRef.current++
      timerRef.current = setTimeout(connect, delay)
    }
  }, [addLog, setWsConnected])

  useEffect(() => {
    connect()
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      wsRef.current?.close()
    }
  }, [connect])
}
