import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Shield } from 'lucide-react'
import api from '../api/client'
import { setTokens } from '../utils/tokenStorage'

export default function Login() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ username: '', password: '', totp_code: '' })
  const [mfaRequired, setMfaRequired] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const payload = { username: form.username, password: form.password }
      if (form.totp_code) payload.totp_code = form.totp_code
      const { data } = await api.post('/auth/login', payload)
      if (data.mfa_required) {
        setMfaRequired(true)
        setLoading(false)
        return
      }
      setTokens(data.access_token, data.refresh_token)
      navigate('/projects')
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(Array.isArray(detail) ? (detail[0]?.msg || 'Login failed') : (detail || 'Login failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-blue-950 flex items-center justify-center">
      <div className="bg-white rounded-xl shadow-2xl p-8 w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <Shield size={40} className="text-blue-700 mb-2" />
          <h1 className="text-2xl font-bold text-gray-900">ATO Bot</h1>
          <p className="text-gray-500 text-sm">NIST 800-53 Rev 5 Assessment</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-1">Username</label>
            <input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              required
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          {mfaRequired && (
            <div>
              <label htmlFor="totp-code" className="block text-sm font-medium text-gray-700 mb-1">MFA Code</label>
              <input
                id="totp-code"
                name="totp_code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                pattern="\d{6}"
                value={form.totp_code}
                onChange={(e) => setForm({ ...form, totp_code: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="6-digit code"
              />
            </div>
          )}
          {error && <p role="alert" aria-live="polite" className="text-red-600 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-700 text-white rounded-lg py-2 text-sm font-medium hover:bg-blue-800 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  )
}
