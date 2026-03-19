import { create } from 'zustand'
import type { RegStatus } from './api'

interface LogEntry {
  time: string
  message: string
}

interface Toast {
  id: number
  type: 'success' | 'error' | 'info'
  message: string
}

let _toastId = 0

interface Store {
  // Logs
  logs: LogEntry[]
  addLog: (log: LogEntry) => void
  clearLogs: () => void
  // Registration status
  regStatus: RegStatus
  setRegStatus: (s: RegStatus) => void
  // WebSocket state
  wsConnected: boolean
  setWsConnected: (v: boolean) => void
  // Toast notifications
  toasts: Toast[]
  addToast: (type: Toast['type'], message: string) => void
  removeToast: (id: number) => void
}

export const useStore = create<Store>((set) => ({
  logs: [],
  addLog: (log) => set((s) => ({ logs: [...s.logs.slice(-500), log] })),
  clearLogs: () => set({ logs: [] }),

  regStatus: { running: false, total: 0, completed: 0, success: 0, failed: 0 },
  setRegStatus: (regStatus) => set({ regStatus }),

  wsConnected: false,
  setWsConnected: (wsConnected) => set({ wsConnected }),

  toasts: [],
  addToast: (type, message) => {
    const id = ++_toastId
    set((s) => ({ toasts: [...s.toasts.slice(-4), { id, type, message }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 3500)
  },
  removeToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))
