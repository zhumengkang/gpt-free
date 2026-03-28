import { useEffect, useState } from 'react'
import { getSettings, updateSettings, type Settings } from '../api'
import { useStore } from '../store'

export default function SettingsPage() {
  const [form, setForm] = useState<Settings>({
    thread_count: 20,
    default_password: '',
    default_proxy: '',
    registration_delay_min: 5,
    registration_delay_max: 30,
    email_poll_timeout: 120,
    auto_switch_provider: true,
    email_mode: 'tempmail_lol',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const addToast = useStore((s) => s.addToast)

  useEffect(() => {
    getSettings()
      .then(setForm)
      .catch((e) => addToast('error', e.message))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    if (form.thread_count < 1 || form.thread_count > 50) {
      addToast('error', '线程数需在 1-50 之间')
      return
    }
    if (form.registration_delay_min > form.registration_delay_max) {
      addToast('error', '最小延迟不能大于最大延迟')
      return
    }
    if (form.default_password && form.default_password.length < 8) {
      addToast('error', '密码长度至少 8 位（留空则随机生成）')
      return
    }

    setSaving(true)
    try {
      await updateSettings(form)
      addToast('success', '设置已保存')
    } catch (e: any) {
      addToast('error', e.message)
    } finally {
      setSaving(false)
    }
  }

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  if (loading) {
    return (
      <div className="py-20 text-center text-gray-600">
        <div className="inline-block w-6 h-6 border-2 border-gray-600 border-t-emerald-400 rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="max-w-xl space-y-5">
      <h2 className="text-lg font-semibold">全局设置</h2>

      <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 space-y-6">
        {/* Email mode */}
        <div>
          <label className="text-sm text-gray-400 block mb-1.5">邮箱模式</label>
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => set('email_mode', 'tempmail_lol')}
              className={`px-4 py-3 rounded-md border text-sm text-left transition-colors ${
                form.email_mode === 'tempmail_lol'
                  ? 'border-emerald-500 bg-emerald-500/10 text-emerald-400'
                  : 'border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-600'
              }`}
            >
              <div className="font-medium">Tempmail.lol</div>
              <div className="text-xs mt-0.5 opacity-70">专业临时邮箱服务，成功率高</div>
            </button>
            <button
              onClick={() => set('email_mode', 'custom')}
              className={`px-4 py-3 rounded-md border text-sm text-left transition-colors ${
                form.email_mode === 'custom'
                  ? 'border-emerald-500 bg-emerald-500/10 text-emerald-400'
                  : 'border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-600'
              }`}
            >
              <div className="font-medium">自建邮箱池</div>
              <div className="text-xs mt-0.5 opacity-70">使用邮箱提供商页面配置的服务</div>
            </button>
          </div>
        </div>

        {/* Thread count */}
        <div>
          <label className="text-sm text-gray-400 block mb-1.5">并发线程数</label>
          <input
            type="number"
            min={1}
            max={50}
            value={form.thread_count}
            onChange={(e) => set('thread_count', Math.max(1, Math.min(50, Number(e.target.value))))}
            className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none"
          />
          <p className="text-xs text-gray-600 mt-1">同时运行的注册线程数量 (1-50)</p>
        </div>

        {/* Password */}
        <div>
          <label className="text-sm text-gray-400 block mb-1.5">注册密码</label>
          <input
            type="text"
            value={form.default_password}
            onChange={(e) => set('default_password', e.target.value)}
            placeholder="留空则每次随机生成 16 位密码"
            className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm font-mono focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none placeholder-gray-600"
          />
          <p className="text-xs text-gray-600 mt-1">
            {form.default_password
              ? `使用固定密码（${form.default_password.length} 位）`
              : '每次注册自动生成随机 16 位强密码（含大小写、数字、特殊字符）'}
          </p>
        </div>

        {/* Proxy */}
        <div>
          <label className="text-sm text-gray-400 block mb-1.5">代理地址</label>
          <input
            type="text"
            value={form.default_proxy}
            onChange={(e) => set('default_proxy', e.target.value)}
            placeholder="留空则使用本地网络直连，例如 http://127.0.0.1:7897"
            className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm font-mono focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none placeholder-gray-600"
          />
          <p className="text-xs text-gray-600 mt-1">
            {form.default_proxy
              ? `使用代理: ${form.default_proxy}`
              : '未配置代理，将使用本地网络直连（需确保能访问 OpenAI）'}
          </p>
        </div>

        {/* Delay */}
        <div>
          <label className="text-sm text-gray-400 block mb-1.5">注册间隔 (秒)</label>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-gray-600 mb-1">最小</div>
              <input
                type="number"
                min={0}
                value={form.registration_delay_min}
                onChange={(e) => set('registration_delay_min', Math.max(0, Number(e.target.value)))}
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm focus:border-emerald-500 outline-none"
              />
            </div>
            <div>
              <div className="text-xs text-gray-600 mb-1">最大</div>
              <input
                type="number"
                min={0}
                value={form.registration_delay_max}
                onChange={(e) => set('registration_delay_max', Math.max(0, Number(e.target.value)))}
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm focus:border-emerald-500 outline-none"
              />
            </div>
          </div>
          <p className="text-xs text-gray-600 mt-1">每次注册之间的随机等待时间</p>
        </div>

        {/* Email timeout */}
        <div>
          <label className="text-sm text-gray-400 block mb-1.5">邮件轮询超时 (秒)</label>
          <input
            type="number"
            min={30}
            max={300}
            value={form.email_poll_timeout}
            onChange={(e) => set('email_poll_timeout', Math.max(30, Math.min(300, Number(e.target.value))))}
            className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none"
          />
          <p className="text-xs text-gray-600 mt-1">等待验证码邮件的最大时间 (30-300)</p>
        </div>

        {/* Auto switch */}
        <div className="flex items-center justify-between py-1">
          <div>
            <label className="text-sm text-gray-300">失败自动切换提供商</label>
            <p className="text-xs text-gray-600 mt-0.5">邮箱创建失败时自动尝试下一个提供商</p>
          </div>
          <button
            onClick={() => set('auto_switch_provider', !form.auto_switch_provider)}
            className={`w-11 h-6 rounded-full relative transition-colors flex-shrink-0 ${
              form.auto_switch_provider ? 'bg-emerald-600' : 'bg-gray-700'
            }`}
            role="switch"
            aria-checked={form.auto_switch_provider}
          >
            <span
              className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all shadow-sm ${
                form.auto_switch_provider ? 'left-[22px]' : 'left-0.5'
              }`}
            />
          </button>
        </div>

        {/* Save */}
        <div className="pt-2 border-t border-gray-800">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-md text-sm font-medium disabled:opacity-50 transition-colors flex items-center gap-2"
          >
            {saving && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
            {saving ? '保存中...' : '保存设置'}
          </button>
        </div>
      </div>
    </div>
  )
}
