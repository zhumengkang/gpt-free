import { useEffect, useRef } from 'react'
import { useStore } from '../store'

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const mountedRef = useRef(false)

  useEffect(() => {
    // 防止重复连接
    if (mountedRef.current) return
    mountedRef.current = true

    function connect() {
      if (wsRef.current?.readyState === WebSocket.OPEN ||
          wsRef.current?.readyState === WebSocket.CONNECTING) return

      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${location.host}/ws/logs`)
      wsRef.current = ws

      ws.onopen = () => {
        retryRef.current = 0
        useStore.getState().setWsConnected(true)
      }

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          useStore.getState().addLog(data)
        } catch {
          useStore.getState().addLog({ time: '', message: e.data })
        }
      }

      ws.onerror = () => {
        useStore.getState().setWsConnected(false)
      }

      ws.onclose = () => {
        useStore.getState().setWsConnected(false)
        wsRef.current = null
        const delay = Math.min(1000 * Math.pow(2, retryRef.current), 15000)
        retryRef.current++
        timerRef.current = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      mountedRef.current = false
      if (timerRef.current) clearTimeout(timerRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null // 防止触发重连
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, []) // 空依赖，只连一次
}
