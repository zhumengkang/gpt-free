import { useEffect, useState, useRef } from 'react'
import {
  getProxies,
  batchAddProxies,
  updateProxy,
  deleteProxy,
  batchDeleteProxies,
  testProxy,
  batchTestProxies,
  type Proxy,
} from '../api'
import { useStore } from '../store'

export default function Proxies() {
  const [proxies, setProxies] = useState<Proxy[]>([])
  const [loading, setLoading] = useState(true)
  const [testing, setTesting] = useState<number | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [batchText, setBatchText] = useState('')
  const [proxyType, setProxyType] = useState('http')
  const [addLoading, setAddLoading] = useState(false)
  const [batchTesting, setBatchTesting] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const addToast = useStore((s) => s.addToast)
  const batchTestTimersRef = useRef<{ interval?: ReturnType<typeof setInterval>; timeout?: ReturnType<typeof setTimeout> }>({})

  // 清理批量测试的定时器
  useEffect(() => {
    return () => {
      if (batchTestTimersRef.current.interval) clearInterval(batchTestTimersRef.current.interval)
      if (batchTestTimersRef.current.timeout) clearTimeout(batchTestTimersRef.current.timeout)
    }
  }, [])

  const loadProxies = async () => {
    try {
      setProxies(await getProxies())
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadProxies() }, [])

  const handleToggle = async (p: Proxy) => {
    try {
      await updateProxy(p.id, { enabled: !p.enabled })
      loadProxies()
    } catch (e: any) {
      addToast('error', e.message)
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除此代理？')) return
    try {
      await deleteProxy(id)
      addToast('success', '已删除')
      loadProxies()
    } catch (e: any) {
      addToast('error', e.message)
    }
  }

  const handleBatchDelete = async () => {
    if (selected.size === 0) return
    if (!confirm(`确定删除选中的 ${selected.size} 个代理？`)) return
    setDeleting(true)
    try {
      const res = await batchDeleteProxies([...selected])
      addToast('success', `已删除 ${res.deleted} 个代理`)
      setSelected(new Set())
      loadProxies()
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setDeleting(false)
    }
  }

  const handleTest = async (id: number) => {
    setTesting(id)
    try {
      const res = await testProxy(id)
      if (res.ok) {
        addToast('success', `代理连通${res.ms != null ? ` (${res.ms}ms)` : ''}`)
      } else {
        addToast('error', `测试失败: ${res.error || '未知错误'}`)
      }
      await loadProxies()
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setTesting(null)
    }
  }

  const handleBatchTest = async () => {
    // 清理之前的定时器
    if (batchTestTimersRef.current.interval) clearInterval(batchTestTimersRef.current.interval)
    if (batchTestTimersRef.current.timeout) clearTimeout(batchTestTimersRef.current.timeout)

    setBatchTesting(true)
    try {
      const res = await batchTestProxies()
      addToast('info', `开始批量测试 ${res.testing} 个代理，请稍候...`)

      // 轮询更新列表，显示测试进度
      batchTestTimersRef.current.interval = setInterval(async () => {
        await loadProxies()
      }, 2000)

      // 10秒后停止轮询并提示完成
      batchTestTimersRef.current.timeout = setTimeout(() => {
        if (batchTestTimersRef.current.interval) clearInterval(batchTestTimersRef.current.interval)
        loadProxies()
        addToast('success', '批量测试已完成')
        setBatchTesting(false)
      }, Math.max(10000, res.testing * 1000))
    } catch (e: any) {
      addToast('error', e.message)
      setBatchTesting(false)
    }
  }

  const handleBatchAdd = async () => {
    const lines = batchText.split('\n').map((l) => l.trim()).filter(Boolean)
    if (lines.length === 0) {
      addToast('error', '请输入至少一个代理地址')
      return
    }
    setAddLoading(true)
    try {
      const res = await batchAddProxies(lines, proxyType)
      addToast('success', `已添加 ${res.added} 个代理`)
      setBatchText('')
      setShowAdd(false)
      loadProxies()
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setAddLoading(false)
    }
  }

  const toggleSelect = (id: number) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }

  const toggleAll = () => {
    if (selected.size === proxies.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(proxies.map((p) => p.id)))
    }
  }

  const enabledCount = proxies.filter((p) => p.enabled).length
  const allChecked = proxies.length > 0 && selected.size === proxies.length

  if (loading) {
    return (
      <div className="py-20 text-center text-gray-600">
        <div className="inline-block w-6 h-6 border-2 border-gray-600 border-t-emerald-400 rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">代理池</h2>
          <p className="text-sm text-gray-500 mt-0.5">{enabledCount} 启用 / {proxies.length} 总计</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleBatchTest}
            disabled={batchTesting || proxies.length === 0}
            className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-md text-sm transition-colors disabled:opacity-50 flex items-center gap-1.5"
          >
            {batchTesting && <div className="w-3 h-3 border-2 border-gray-500 border-t-white rounded-full animate-spin" />}
            {batchTesting ? '测试中...' : '批量测试'}
          </button>
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded-md text-sm font-medium transition-colors"
          >
            批量添加
          </button>
        </div>
      </div>

      {/* 选中操作栏 */}
      {selected.size > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 px-4 py-2.5 flex items-center gap-3">
          <span className="text-xs text-emerald-400">已选 {selected.size} 项</span>
          <button
            onClick={handleBatchDelete}
            disabled={deleting}
            className="px-2.5 py-1 text-xs bg-red-600/80 hover:bg-red-500 rounded text-white disabled:opacity-50 transition-colors"
          >
            {deleting ? '删除中...' : '批量删除'}
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="text-xs text-gray-500 hover:text-gray-300"
          >
            取消
          </button>
        </div>
      )}

      {showAdd && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 space-y-3">
          <div className="flex gap-3 items-center">
            <label className="text-sm text-gray-400">类型:</label>
            <div className="flex gap-1.5">
              {['http', 'socks5'].map((t) => (
                <button
                  key={t}
                  onClick={() => setProxyType(t)}
                  className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${
                    proxyType === t ? 'bg-emerald-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  {t.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <textarea
            value={batchText}
            onChange={(e) => setBatchText(e.target.value)}
            placeholder={"每行一个代理地址，例如:\nhttp://127.0.0.1:7890\nsocks5://user:pass@host:port"}
            className="w-full h-36 bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm font-mono resize-none focus:border-emerald-500 outline-none placeholder-gray-600"
          />
          <div className="flex items-center gap-3">
            <button
              onClick={handleBatchAdd}
              disabled={addLoading}
              className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded-md text-sm disabled:opacity-50 transition-colors flex items-center gap-1.5"
            >
              {addLoading && <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              确认添加
            </button>
            <button onClick={() => setShowAdd(false)} className="px-4 py-1.5 text-sm text-gray-400 hover:text-white transition-colors">
              取消
            </button>
            {batchText && (
              <span className="text-xs text-gray-500">
                {batchText.split('\n').filter((l) => l.trim()).length} 行
              </span>
            )}
          </div>
        </div>
      )}

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 text-xs uppercase tracking-wider border-b border-gray-800">
              <th className="p-3 w-8">
                <input
                  type="checkbox"
                  checked={allChecked}
                  onChange={toggleAll}
                  className="rounded border-gray-600 text-emerald-500 focus:ring-emerald-500 bg-gray-800"
                />
              </th>
              <th className="p-3 font-medium w-14">启用</th>
              <th className="p-3 font-medium">地址</th>
              <th className="p-3 font-medium w-20">类型</th>
              <th className="p-3 font-medium w-24">测试结果</th>
              <th className="p-3 font-medium w-20">失败</th>
              <th className="p-3 font-medium w-32">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/50">
            {proxies.length === 0 && (
              <tr>
                <td colSpan={7} className="p-12 text-center text-gray-600">
                  暂无代理，点击"批量添加"导入
                </td>
              </tr>
            )}
            {proxies.map((p) => (
              <tr key={p.id} className={`table-row-hover group ${selected.has(p.id) ? 'bg-emerald-900/10' : ''}`}>
                <td className="p-3">
                  <input
                    type="checkbox"
                    checked={selected.has(p.id)}
                    onChange={() => toggleSelect(p.id)}
                    className="rounded border-gray-600 text-emerald-500 focus:ring-emerald-500 bg-gray-800"
                  />
                </td>
                <td className="p-3">
                  <button
                    onClick={() => handleToggle(p)}
                    className={`w-9 h-5 rounded-full relative transition-colors ${p.enabled ? 'bg-emerald-600' : 'bg-gray-700'}`}
                    aria-label={p.enabled ? '禁用' : '启用'}
                  >
                    <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all shadow-sm ${p.enabled ? 'left-[18px]' : 'left-0.5'}`} />
                  </button>
                </td>
                <td className="p-3 font-mono text-xs text-gray-300">{p.url}</td>
                <td className="p-3">
                  <span className="text-xs text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">{p.proxy_type}</span>
                </td>
                <td className="p-3">
                  {p.last_test_at ? (
                    <div className="flex items-center gap-1.5">
                      <span className={`text-xs ${p.last_test_ok ? 'text-emerald-400' : 'text-red-400'}`}>
                        {p.last_test_ok ? '✓' : '✗'}
                      </span>
                      {p.last_test_ms !== null && (
                        <span className="text-xs text-gray-500 tabular-nums">{p.last_test_ms}ms</span>
                      )}
                    </div>
                  ) : (
                    <span className="text-xs text-gray-600">未测试</span>
                  )}
                </td>
                <td className="p-3">
                  <span className={`tabular-nums ${p.fail_count > 0 ? 'text-red-400' : 'text-gray-600'}`}>{p.fail_count}</span>
                </td>
                <td className="p-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleTest(p.id)}
                      disabled={testing === p.id}
                      className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50 transition-colors"
                    >
                      {testing === p.id ? '测试中...' : '测试'}
                    </button>
                    <button
                      onClick={() => handleDelete(p.id)}
                      className="text-xs text-red-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
