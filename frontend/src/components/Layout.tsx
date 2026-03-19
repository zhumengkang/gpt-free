import { NavLink, Outlet } from 'react-router-dom'
import { useStore } from '../store'

const links = [
  { to: '/', label: '仪表盘' },
  { to: '/providers', label: '邮箱提供商' },
  { to: '/proxies', label: '代理池' },
  { to: '/settings', label: '设置' },
]

function ToastContainer() {
  const toasts = useStore((s) => s.toasts)
  const removeToast = useStore((s) => s.removeToast)

  if (toasts.length === 0) return null

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          onClick={() => removeToast(t.id)}
          className={`px-4 py-3 rounded-lg shadow-lg cursor-pointer text-sm animate-slide-in border ${
            t.type === 'success'
              ? 'bg-emerald-900/90 border-emerald-700 text-emerald-100'
              : t.type === 'error'
              ? 'bg-red-900/90 border-red-700 text-red-100'
              : 'bg-blue-900/90 border-blue-700 text-blue-100'
          }`}
        >
          {t.message}
        </div>
      ))}
    </div>
  )
}

export default function Layout() {
  const wsConnected = useStore((s) => s.wsConnected)

  return (
    <div className="min-h-screen flex flex-col bg-gray-950">
      <nav className="bg-gray-900/80 backdrop-blur-sm border-b border-gray-800 px-6 py-3 flex items-center gap-8 sticky top-0 z-40">
        <div className="flex items-center gap-2.5">
          <div className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]" />
          <span className="text-lg font-bold text-white tracking-tight">GPT-Free</span>
        </div>
        <div className="flex gap-1">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.to === '/'}
              className={({ isActive }) =>
                `px-3.5 py-1.5 rounded-md text-sm font-medium transition-all ${
                  isActive
                    ? 'bg-emerald-600/90 text-white shadow-sm'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`
              }
            >
              {l.label}
            </NavLink>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2 text-xs text-gray-500">
          <div className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-emerald-400' : 'bg-red-400'}`} />
          {wsConnected ? 'WS 已连接' : 'WS 断开'}
        </div>
      </nav>
      <main className="flex-1 p-6 max-w-[1400px] mx-auto w-full">
        <Outlet />
      </main>
      <ToastContainer />
    </div>
  )
}
