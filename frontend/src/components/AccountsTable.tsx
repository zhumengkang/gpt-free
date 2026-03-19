import { useState } from 'react'
import { deleteAccount, refreshAccountToken, type Account } from '../api'
import { useStore } from '../store'

interface Props {
  accounts: Account[]
  onRefresh: () => void
  loading?: boolean
  selected: Set<number>
  onSelectChange: (s: Set<number>) => void
}

const statusConfig: Record<string, { color: string; bg: string; label: string }> = {
  success: { color: 'text-emerald-400', bg: 'bg-emerald-400/10', label: '成功' },
  failed: { color: 'text-red-400', bg: 'bg-red-400/10', label: '失败' },
  registering: { color: 'text-yellow-400', bg: 'bg-yellow-400/10', label: '注册中' },
  pending: { color: 'text-gray-400', bg: 'bg-gray-400/10', label: '待处理' },
}

export default function AccountsTable({ accounts, onRefresh, loading, selected, onSelectChange }: Props) {
  const [showPwd, setShowPwd] = useState<Set<number>>(new Set())
  const [expandedError, setExpandedError] = useState<number | null>(null)
  const [refreshingId, setRefreshingId] = useState<number | null>(null)
  const addToast = useStore((s) => s.addToast)

  const togglePwd = (id: number) => {
    setShowPwd((s) => {
      const next = new Set(s)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除此账号？')) return
    try {
      await deleteAccount(id)
      addToast('success', '账号已删除')
      onRefresh()
    } catch (e: any) {
      addToast('error', e.message)
    }
  }

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text)
    addToast('info', '已复制到剪贴板')
  }

  const handleRefresh = async (id: number) => {
    setRefreshingId(id)
    try {
      const res = await refreshAccountToken(id)
      addToast('success', `Token 已刷新，过期: ${res.token_expired_at}`)
      onRefresh()
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setRefreshingId(null)
    }
  }

  const toggleSelect = (id: number) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    onSelectChange(next)
  }

  const toggleAll = () => {
    if (selected.size === accounts.length) {
      onSelectChange(new Set())
    } else {
      onSelectChange(new Set(accounts.map((a) => a.id)))
    }
  }

  if (loading) {
    return (
      <div className="py-12 text-center text-gray-600">
        <div className="inline-block w-5 h-5 border-2 border-gray-600 border-t-emerald-400 rounded-full animate-spin" />
        <span className="ml-2">加载中...</span>
      </div>
    )
  }

  const allChecked = accounts.length > 0 && selected.size === accounts.length

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-500 text-xs uppercase tracking-wider">
            <th className="pb-3 pr-2 w-8">
              <input
                type="checkbox"
                checked={allChecked}
                onChange={toggleAll}
                className="rounded border-gray-600 text-emerald-500 focus:ring-emerald-500 bg-gray-800"
              />
            </th>
            <th className="pb-3 pr-3 font-medium">ID</th>
            <th className="pb-3 pr-3 font-medium">邮箱</th>
            <th className="pb-3 pr-3 font-medium">密码</th>
            <th className="pb-3 pr-3 font-medium">状态</th>
            <th className="pb-3 pr-3 font-medium">提供商</th>
            <th className="pb-3 pr-3 font-medium">代理</th>
            <th className="pb-3 pr-3 font-medium">时间</th>
            <th className="pb-3 font-medium">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/50">
          {accounts.length === 0 && (
            <tr>
              <td colSpan={9} className="py-12 text-center text-gray-600">
                暂无账号数据
              </td>
            </tr>
          )}
          {accounts.map((a) => {
            const sc = statusConfig[a.status] || statusConfig.pending
            return (
              <tr key={a.id} className={`table-row-hover group ${selected.has(a.id) ? 'bg-emerald-900/10' : ''}`}>
                <td className="py-2.5 pr-2">
                  <input
                    type="checkbox"
                    checked={selected.has(a.id)}
                    onChange={() => toggleSelect(a.id)}
                    className="rounded border-gray-600 text-emerald-500 focus:ring-emerald-500 bg-gray-800"
                  />
                </td>
                <td className="py-2.5 pr-3 text-gray-500 tabular-nums">{a.id}</td>
                <td className="py-2.5 pr-3">
                  <button
                    onClick={() => copyText(a.email)}
                    className="font-mono text-xs text-gray-300 hover:text-white transition-colors"
                    title="点击复制"
                  >
                    {a.email}
                  </button>
                </td>
                <td className="py-2.5 pr-3">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-xs text-gray-400">
                      {showPwd.has(a.id) ? a.password : '••••••••'}
                    </span>
                    <button
                      onClick={() => togglePwd(a.id)}
                      className="text-[10px] text-gray-600 hover:text-gray-400 transition-colors"
                    >
                      {showPwd.has(a.id) ? '隐藏' : '显示'}
                    </button>
                    {showPwd.has(a.id) && (
                      <button
                        onClick={() => copyText(a.password)}
                        className="text-[10px] text-gray-600 hover:text-gray-400 transition-colors"
                      >
                        复制
                      </button>
                    )}
                  </div>
                </td>
                <td className="py-2.5 pr-3">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${sc.color} ${sc.bg}`}>
                    {sc.label}
                  </span>
                  {a.status === 'failed' && a.error_message && (
                    <button
                      onClick={() => setExpandedError(expandedError === a.id ? null : a.id)}
                      className="ml-1.5 text-[10px] text-red-500/60 hover:text-red-400"
                    >
                      详情
                    </button>
                  )}
                  {expandedError === a.id && a.error_message && (
                    <div className="mt-1 text-[11px] text-red-400/80 max-w-xs break-all">
                      {a.error_message}
                    </div>
                  )}
                </td>
                <td className="py-2.5 pr-3 text-xs text-gray-500 max-w-[140px] truncate">
                  {a.temp_email_provider || '-'}
                </td>
                <td className="py-2.5 pr-3 text-xs text-gray-500 max-w-[140px] truncate">
                  {a.proxy_used || '-'}
                </td>
                <td className="py-2.5 pr-3 text-xs text-gray-600 whitespace-nowrap">
                  {a.created_at?.replace('T', ' ').slice(0, 19)}
                </td>
                <td className="py-2.5">
                  <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    {a.refresh_token && (
                      <button
                        onClick={() => handleRefresh(a.id)}
                        disabled={refreshingId === a.id}
                        className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50"
                      >
                        {refreshingId === a.id ? '刷新中...' : '刷新Token'}
                      </button>
                    )}
                    {a.access_token && (
                      <button
                        onClick={() => copyText(a.access_token!)}
                        className="text-xs text-emerald-400 hover:text-emerald-300"
                      >
                        复制Token
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(a.id)}
                      className="text-xs text-red-500 hover:text-red-400"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
