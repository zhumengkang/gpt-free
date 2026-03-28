import { useEffect, useState, useCallback } from 'react'
import {
  getAccounts, startRegistration, stopRegistration, getRegistrationStatus,
  batchDeleteAccounts, deleteFailedAccounts, batchRefreshTokens, getStats,
  exportAccounts, type Account, type Stats,
} from '../api'
import { useStore } from '../store'
import { useWebSocket } from '../hooks/useWebSocket'
import AccountsTable from '../components/AccountsTable'
import LogViewer from '../components/LogViewer'
import ExportDialog from '../components/ExportDialog'

const PAGE_SIZE = 10

export default function Dashboard() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [count, setCount] = useState(1)
  const [exportOpen, setExportOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [stats, setStats] = useState<Stats>({ total: 0, success: 0, failed: 0, registering: 0, pending: 0, success_rate: 0 })
  const regStatus = useStore((s) => s.regStatus)
  const setRegStatus = useStore((s) => s.setRegStatus)
  const addToast = useStore((s) => s.addToast)

  useWebSocket()

  const fetchAccounts = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true)
    try {
      const data = await getAccounts(statusFilter || undefined, PAGE_SIZE, page * PAGE_SIZE)
      setAccounts(data.items)
      setTotal(data.total)
    } catch {
      // silent on polling
    } finally {
      setLoading(false)
    }
  }, [statusFilter, page])

  const fetchStatus = useCallback(async () => {
    try {
      setRegStatus(await getRegistrationStatus())
    } catch {
      // silent
    }
  }, [setRegStatus])

  const fetchStats = useCallback(async () => {
    try {
      setStats(await getStats())
    } catch {
      // silent
    }
  }, [])

  useEffect(() => {
    fetchAccounts(true)
    fetchStatus()
    fetchStats()
    const t = setInterval(() => {
      fetchAccounts()
      fetchStatus()
      fetchStats()
    }, 3000)
    return () => clearInterval(t)
  }, [fetchAccounts, fetchStatus, fetchStats])

  useEffect(() => { setPage(0) }, [statusFilter])
  useEffect(() => { setSelected(new Set()) }, [page, statusFilter])

  const handleStart = async () => {
    setStarting(true)
    try {
      const res = await startRegistration(count)
      addToast('success', res.message)
      fetchStatus()
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setStarting(false)
    }
  }

  const handleStop = async () => {
    try {
      await stopRegistration()
      addToast('info', '正在停止注册任务')
      fetchStatus()
    } catch (e: any) {
      addToast('error', e.message)
    }
  }

  const handleBatchDelete = async () => {
    if (selected.size === 0) return
    if (!confirm(`确定删除选中的 ${selected.size} 个账号？`)) return
    setDeleting(true)
    try {
      const res = await batchDeleteAccounts([...selected])
      addToast('success', `已删除 ${res.deleted} 个账号`)
      setSelected(new Set())
      fetchAccounts()
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setDeleting(false)
    }
  }

  const handleDeleteFailed = async () => {
    if (!confirm('确定删除所有注册失败的账号？')) return
    try {
      const res = await deleteFailedAccounts()
      addToast('success', `已删除 ${res.deleted} 个失败账号`)
      fetchAccounts()
      fetchStats()
    } catch (e: any) {
      addToast('error', e.message)
    }
  }

  const handleBatchRefresh = async () => {
    setRefreshing(true)
    try {
      const res = await batchRefreshTokens()
      addToast('success', `Token 刷新: ${res.success} 成功, ${res.failed} 失败`)
      fetchAccounts()
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setRefreshing(false)
    }
  }

  const handleExportSuccess = async () => {
    try {
      await exportAccounts(
        ['email', 'password', 'access_token', 'refresh_token'],
        'json',
        'success',
      )
      addToast('success', '成功账号已导出')
    } catch (e: any) {
      addToast('error', e.message)
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="space-y-5">
      {/* Stats cards */}
      <div className="grid grid-cols-5 gap-4">
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="text-xs text-gray-500 mb-1">总账号</div>
          <div className="text-2xl font-bold tabular-nums text-white">{stats.total}</div>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="text-xs text-gray-500 mb-1">成功</div>
          <div className="text-2xl font-bold tabular-nums text-emerald-400">{stats.success}</div>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="text-xs text-gray-500 mb-1">失败</div>
          <div className="text-2xl font-bold tabular-nums text-red-400">{stats.failed}</div>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="text-xs text-gray-500 mb-1">进行中</div>
          <div className="text-2xl font-bold tabular-nums text-yellow-400">{stats.registering}</div>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="text-xs text-gray-500 mb-1">成功率</div>
          <div className="text-2xl font-bold tabular-nums text-blue-400">{stats.success_rate}%</div>
          {/* Mini bar */}
          {(stats.success + stats.failed) > 0 && (
            <div className="mt-2 h-1.5 bg-gray-800 rounded-full overflow-hidden">
              <div className="h-full bg-emerald-500 rounded-full transition-all" style={{ width: `${stats.success_rate}%` }} />
            </div>
          )}
        </div>
      </div>

      {/* Registration control */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400">数量:</label>
            <input
              type="number"
              min={1}
              value={count}
              onChange={(e) => setCount(Math.max(1, Number(e.target.value)))}
              className="w-24 bg-gray-800 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none"
            />
          </div>

          {!regStatus.running ? (
            <button
              onClick={handleStart}
              disabled={starting}
              className="px-5 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded-md text-sm font-medium disabled:opacity-50 transition-colors flex items-center gap-2"
            >
              {starting && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              {starting ? '启动中...' : '开始注册'}
            </button>
          ) : (
            <button
              onClick={handleStop}
              className="px-5 py-1.5 bg-red-600 hover:bg-red-500 rounded-md text-sm font-medium transition-colors"
            >
              停止
            </button>
          )}

          {regStatus.running && (
            <div className="flex items-center gap-4 text-sm">
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
                <span className="text-yellow-400">运行中</span>
              </div>
              <div className="h-1.5 w-32 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                  style={{ width: `${regStatus.total > 0 ? (regStatus.completed / regStatus.total) * 100 : 0}%` }}
                />
              </div>
              <span className="text-gray-400 tabular-nums">
                {regStatus.completed}/{regStatus.total}
              </span>
            </div>
          )}

          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={handleBatchRefresh}
              disabled={refreshing || stats.success === 0}
              className="px-3.5 py-1.5 bg-gray-800 hover:bg-blue-900/40 border border-gray-700 hover:border-blue-800 rounded-md text-sm text-gray-400 hover:text-blue-400 transition-colors disabled:opacity-40 flex items-center gap-1.5"
            >
              {refreshing && <div className="w-3 h-3 border-2 border-gray-500 border-t-blue-400 rounded-full animate-spin" />}
              {refreshing ? '刷新中...' : '刷新Token'}
            </button>
            <button
              onClick={handleDeleteFailed}
              disabled={stats.failed === 0}
              className="px-3.5 py-1.5 bg-gray-800 hover:bg-red-900/40 border border-gray-700 hover:border-red-800 rounded-md text-sm text-gray-400 hover:text-red-400 transition-colors disabled:opacity-40"
            >
              清除失败
            </button>
            <button
              onClick={handleExportSuccess}
              disabled={stats.success === 0}
              className="px-3.5 py-1.5 bg-gray-800 hover:bg-emerald-900/40 border border-gray-700 hover:border-emerald-800 rounded-md text-sm text-gray-400 hover:text-emerald-400 transition-colors disabled:opacity-40"
            >
              导出成功
            </button>
            <button
              onClick={() => setExportOpen(true)}
              className="px-3.5 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-md text-sm transition-colors"
            >
              自定义导出
            </button>
          </div>
        </div>
      </div>

      {/* Log viewer */}
      <LogViewer />

      {/* Accounts table */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-semibold text-gray-300">
              账号列表
              <span className="ml-2 text-gray-600 font-normal">({total})</span>
            </h2>
            {selected.size > 0 && (
              <div className="flex items-center gap-2 ml-2">
                <span className="text-xs text-emerald-400">已选 {selected.size} 项</span>
                <button
                  onClick={handleBatchDelete}
                  disabled={deleting}
                  className="px-2.5 py-1 text-xs bg-red-600/80 hover:bg-red-500 rounded text-white disabled:opacity-50 transition-colors"
                >
                  {deleting ? '删除中...' : '批量删除'}
                </button>
                <button
                  onClick={() => setExportOpen(true)}
                  className="px-2.5 py-1 text-xs bg-blue-600/80 hover:bg-blue-500 rounded text-white transition-colors"
                >
                  导出选中
                </button>
                <button
                  onClick={() => setSelected(new Set())}
                  className="text-xs text-gray-500 hover:text-gray-300"
                >
                  取消
                </button>
              </div>
            )}
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm focus:border-emerald-500 outline-none"
          >
            <option value="">全部状态</option>
            <option value="success">成功</option>
            <option value="failed">失败</option>
            <option value="registering">注册中</option>
            <option value="pending">待处理</option>
          </select>
        </div>

        <AccountsTable
          accounts={accounts}
          onRefresh={() => { fetchAccounts(false); fetchStats() }}
          loading={loading}
          selected={selected}
          onSelectChange={setSelected}
        />

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-800">
            <span className="text-xs text-gray-500">
              第 {page + 1} / {totalPages} 页
            </span>
            <div className="flex gap-1.5">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="px-3 py-1 text-xs bg-gray-800 hover:bg-gray-700 rounded disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                上一页
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="px-3 py-1 text-xs bg-gray-800 hover:bg-gray-700 rounded disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>

      <ExportDialog
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        selectedIds={selected.size > 0 ? [...selected] : undefined}
      />
    </div>
  )
}
