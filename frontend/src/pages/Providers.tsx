import { useEffect, useState } from 'react'
import {
  getProviders,
  addProvider,
  updateProvider,
  deleteProvider,
  testProvider,
  importDefaults,
  type Provider,
} from '../api'
import { useStore } from '../store'

export default function Providers() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [loading, setLoading] = useState(true)
  const [testing, setTesting] = useState<number | null>(null)
  const [testResult, setTestResult] = useState<Record<number, { ok: boolean; msg: string }>>({})
  const [showAdd, setShowAdd] = useState(false)
  const [addLoading, setAddLoading] = useState(false)
  const [importLoading, setImportLoading] = useState(false)
  const [form, setForm] = useState({ name: '', base_url: '', origin: '' })
  const [search, setSearch] = useState('')
  const addToast = useStore((s) => s.addToast)

  const loadProviders = async () => {
    try {
      setProviders(await getProviders())
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadProviders() }, [])

  const handleToggle = async (p: Provider) => {
    try {
      await updateProvider(p.id, { enabled: !p.enabled })
      loadProviders()
    } catch (e: any) {
      addToast('error', e.message)
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除此提供商？')) return
    try {
      await deleteProvider(id)
      addToast('success', '已删除')
      loadProviders()
    } catch (e: any) {
      addToast('error', e.message)
    }
  }

  const handleTest = async (id: number) => {
    setTesting(id)
    try {
      const res = await testProvider(id)
      setTestResult((r) => ({
        ...r,
        [id]: { ok: res.ok, msg: res.ok ? `${res.domains?.length || 0} 个域名` : res.error || '失败' },
      }))
      addToast(res.ok ? 'success' : 'error', res.ok ? '连通性测试通过' : `测试失败: ${res.error}`)
    } catch (e: any) {
      setTestResult((r) => ({ ...r, [id]: { ok: false, msg: e.message } }))
      addToast('error', e.message)
    }
    setTesting(null)
  }

  const handleAdd = async () => {
    if (!form.name || !form.base_url || !form.origin) {
      addToast('error', '请填写所有字段')
      return
    }
    setAddLoading(true)
    try {
      await addProvider(form)
      setForm({ name: '', base_url: '', origin: '' })
      setShowAdd(false)
      addToast('success', '提供商已添加')
      loadProviders()
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setAddLoading(false)
    }
  }

  const handleImport = async () => {
    setImportLoading(true)
    try {
      const res = await importDefaults()
      addToast('success', `已导入 ${res.imported} 个提供商`)
      loadProviders()
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setImportLoading(false)
    }
  }

  const filtered = search
    ? providers.filter((p) => p.name.toLowerCase().includes(search.toLowerCase()) || p.base_url.toLowerCase().includes(search.toLowerCase()))
    : providers
  const enabledCount = providers.filter((p) => p.enabled).length

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
          <h2 className="text-lg font-semibold">邮箱提供商</h2>
          <p className="text-sm text-gray-500 mt-0.5">{enabledCount} 启用 / {providers.length} 总计</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleImport}
            disabled={importLoading}
            className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-md text-sm transition-colors disabled:opacity-50 flex items-center gap-1.5"
          >
            {importLoading && <div className="w-3 h-3 border-2 border-gray-500 border-t-white rounded-full animate-spin" />}
            重新导入默认
          </button>
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded-md text-sm font-medium transition-colors"
          >
            添加
          </button>
        </div>
      </div>

      {showAdd && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-1">名称</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm focus:border-emerald-500 outline-none"
                placeholder="example.com"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Base URL</label>
              <input
                value={form.base_url}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm focus:border-emerald-500 outline-none"
                placeholder="https://api.example.com"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Origin</label>
              <input
                value={form.origin}
                onChange={(e) => setForm({ ...form, origin: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-2.5 py-1.5 text-sm focus:border-emerald-500 outline-none"
                placeholder="https://example.com"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleAdd}
              disabled={addLoading}
              className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded-md text-sm disabled:opacity-50 transition-colors flex items-center gap-1.5"
            >
              {addLoading && <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              确认
            </button>
            <button onClick={() => setShowAdd(false)} className="px-4 py-1.5 text-sm text-gray-400 hover:text-white transition-colors">
              取消
            </button>
          </div>
        </div>
      )}

      {/* Search */}
      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="搜索提供商名称或 URL..."
        className="w-full bg-gray-900 border border-gray-800 rounded-lg px-4 py-2.5 text-sm focus:border-emerald-500 outline-none placeholder-gray-600"
      />

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 text-xs uppercase tracking-wider border-b border-gray-800">
              <th className="p-3 font-medium w-14">启用</th>
              <th className="p-3 font-medium">名称</th>
              <th className="p-3 font-medium">Base URL</th>
              <th className="p-3 font-medium w-20">失败</th>
              <th className="p-3 font-medium w-48">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/50">
            {filtered.length === 0 && (
              <tr><td colSpan={5} className="p-8 text-center text-gray-600">{search ? '无匹配结果' : '暂无提供商'}</td></tr>
            )}
            {filtered.map((p) => (
              <tr key={p.id} className="table-row-hover group">
                <td className="p-3">
                  <button
                    onClick={() => handleToggle(p)}
                    className={`w-9 h-5 rounded-full relative transition-colors ${p.enabled ? 'bg-emerald-600' : 'bg-gray-700'}`}
                    aria-label={p.enabled ? '禁用' : '启用'}
                  >
                    <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all shadow-sm ${p.enabled ? 'left-[18px]' : 'left-0.5'}`} />
                  </button>
                </td>
                <td className="p-3 font-mono text-xs max-w-[200px] truncate text-gray-300">{p.name}</td>
                <td className="p-3 font-mono text-xs text-gray-500 max-w-[280px] truncate">{p.base_url}</td>
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
                    {testResult[p.id] && (
                      <span className={`text-xs ${testResult[p.id].ok ? 'text-emerald-400' : 'text-red-400'}`}>
                        {testResult[p.id].msg}
                      </span>
                    )}
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
