import { useState } from 'react'
import { exportAccounts } from '../api'
import { useStore } from '../store'

const ALL_FIELDS = [
  { key: 'email', label: '邮箱' },
  { key: 'password', label: '密码' },
  { key: 'access_token', label: 'Access Token' },
  { key: 'refresh_token', label: 'Refresh Token' },
  { key: 'id_token', label: 'ID Token' },
  { key: 'account_id', label: 'Account ID' },
  { key: 'token_expired_at', label: 'Token 过期时间' },
  { key: 'temp_email_provider', label: '邮箱提供商' },
  { key: 'proxy_used', label: '使用的代理' },
  { key: 'status', label: '状态' },
  { key: 'created_at', label: '创建时间' },
]

interface Props {
  open: boolean
  onClose: () => void
  selectedIds?: number[]
}

export default function ExportDialog({ open, onClose, selectedIds }: Props) {
  const [fields, setFields] = useState<string[]>(['email', 'password', 'access_token', 'refresh_token'])
  const [format, setFormat] = useState('json')
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const addToast = useStore((s) => s.addToast)

  if (!open) return null

  const toggle = (key: string) => {
    setFields((f) => (f.includes(key) ? f.filter((x) => x !== key) : [...f, key]))
  }

  const selectAll = () => setFields(ALL_FIELDS.map((f) => f.key))
  const selectNone = () => setFields([])

  const handleExport = async () => {
    if (fields.length === 0) return
    setLoading(true)
    try {
      await exportAccounts(fields, format, statusFilter || undefined, selectedIds)
      addToast('success', '导出成功')
      onClose()
    } catch (e: any) {
      addToast('error', `导出失败: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-gray-900 rounded-xl border border-gray-700 p-6 w-[480px] max-h-[80vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold mb-1">导出账号</h3>
        {selectedIds && selectedIds.length > 0 && (
          <p className="text-xs text-emerald-400 mb-4">导出选中的 {selectedIds.length} 个账号</p>
        )}
        {!selectedIds && <div className="mb-4" />}

        <div className="mb-5">
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm text-gray-400">选择字段</label>
            <div className="flex gap-2">
              <button onClick={selectAll} className="text-xs text-emerald-400 hover:text-emerald-300">全选</button>
              <button onClick={selectNone} className="text-xs text-gray-500 hover:text-gray-300">清空</button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {ALL_FIELDS.map((f) => (
              <label
                key={f.key}
                className={`flex items-center gap-2 text-sm cursor-pointer px-2.5 py-1.5 rounded-md transition-colors ${
                  fields.includes(f.key) ? 'bg-emerald-900/30 text-emerald-300' : 'text-gray-400 hover:bg-gray-800'
                }`}
              >
                <input
                  type="checkbox"
                  checked={fields.includes(f.key)}
                  onChange={() => toggle(f.key)}
                  className="rounded border-gray-600 text-emerald-500 focus:ring-emerald-500 bg-gray-800"
                />
                {f.label}
              </label>
            ))}
          </div>
        </div>

        <div className="mb-5">
          <label className="text-sm text-gray-400 mb-2 block">格式</label>
          <div className="flex gap-2">
            {['json', 'csv', 'txt'].map((f) => (
              <button
                key={f}
                onClick={() => setFormat(f)}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${
                  format === f
                    ? 'bg-emerald-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700'
                }`}
              >
                {f.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {!selectedIds && (
          <div className="mb-6">
            <label className="text-sm text-gray-400 mb-2 block">状态过滤</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm w-full focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none"
            >
              <option value="">全部</option>
              <option value="success">成功</option>
              <option value="failed">失败</option>
              <option value="registering">注册中</option>
              <option value="pending">待处理</option>
            </select>
          </div>
        )}

        <div className="flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-white rounded-md hover:bg-gray-800 transition-colors">
            取消
          </button>
          <button
            onClick={handleExport}
            disabled={fields.length === 0 || loading}
            className="px-5 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 rounded-md disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {loading && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
            {loading ? '导出中...' : '导出'}
          </button>
        </div>
      </div>
    </div>
  )
}
