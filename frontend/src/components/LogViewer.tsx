import { useEffect, useRef } from 'react'
import { useStore } from '../store'

export default function LogViewer() {
  const logs = useStore((s) => s.logs)
  const clearLogs = useStore((s) => s.clearLogs)
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    // Auto-scroll only if already near bottom
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    if (isNearBottom) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs])

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 flex flex-col h-72">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-300">实时日志</span>
          <span className="text-xs text-gray-600">({logs.length})</span>
        </div>
        <button
          onClick={clearLogs}
          className="text-xs text-gray-500 hover:text-gray-300 px-2 py-0.5 rounded hover:bg-gray-800 transition-colors"
        >
          清空
        </button>
      </div>
      <div ref={containerRef} className="flex-1 overflow-y-auto p-3 font-mono text-xs leading-5">
        {logs.length === 0 && (
          <div className="text-gray-600 text-center py-8">等待日志...</div>
        )}
        {logs.map((l, i) => (
          <div key={i} className="text-gray-400 hover:text-gray-200 transition-colors">
            {l.time && <span className="text-gray-600 mr-2 select-none">[{l.time}]</span>}
            <span className={
              l.message.includes('成功') ? 'text-emerald-400' :
              l.message.includes('失败') || l.message.includes('错误') ? 'text-red-400' :
              l.message.includes('等待') ? 'text-yellow-500/70' : ''
            }>
              {l.message}
            </span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
