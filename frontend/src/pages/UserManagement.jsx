import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { UserPlus, Shield, CheckCircle, XCircle, KeyRound } from 'lucide-react'
import api from '../api/client'

const ROLES = ['viewer', 'system_owner', 'reviewer', 'assessor', 'security_officer', 'system_admin']

const ROLE_COLOR = {
  system_admin: 'bg-purple-100 text-purple-800',
  security_officer: 'bg-blue-100 text-blue-800',
  assessor: 'bg-green-100 text-green-800',
  reviewer: 'bg-yellow-100 text-yellow-800',
  system_owner: 'bg-orange-100 text-orange-800',
  viewer: 'bg-gray-100 text-gray-600',
}

function formatApiError(error, fallback) {
  const detail = error.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || String(item)).join('; ')
  }
  return detail || fallback
}

function CreateUserModal({ onClose }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ username: '', email: '', password: '', role: 'viewer' })
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: (data) => api.post('/users', data).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries(['users']); onClose() },
    onError: (e) => setError(formatApiError(e, 'Failed to create user')),
  })

  const submit = (e) => {
    e.preventDefault()
    setError('')
    mutation.mutate(form)
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5 sm:p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Create User</h2>
        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Username</label>
            <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
              required className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Email</label>
            <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
              required className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Password</label>
            <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
              required className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm">
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex flex-col gap-2 pt-2 sm:flex-row">
            <button type="button" onClick={onClose}
              className="flex-1 border border-gray-300 rounded-lg py-2 text-sm hover:bg-gray-50">Cancel</button>
            <button type="submit" disabled={mutation.isPending}
              className="flex-1 bg-blue-700 text-white rounded-lg py-2 text-sm hover:bg-blue-800 disabled:opacity-50">
              {mutation.isPending ? 'Creating...' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function ResetPasswordModal({ user, onClose }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ password: '', confirmPassword: '' })
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: (data) => api.post(`/users/${user.id}/reset-password`, data).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries(['users']); onClose() },
    onError: (e) => setError(formatApiError(e, 'Failed to reset password')),
  })

  const submit = (e) => {
    e.preventDefault()
    setError('')
    if (form.password !== form.confirmPassword) {
      setError('Passwords do not match')
      return
    }
    mutation.mutate({ password: form.password })
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5 sm:p-6">
        <div className="flex items-center gap-2 mb-4">
          <KeyRound size={18} className="text-blue-700" />
          <h2 className="text-lg font-semibold text-gray-900">Reset Password</h2>
        </div>
        <p className="text-sm text-gray-500 mb-4">
          Set a new password for <span className="font-medium text-gray-800">{user.username}</span>.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">New Password</label>
            <input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            />
            <p className="text-[11px] text-gray-400 mt-1">
              Minimum 12 characters with uppercase, lowercase, number, and special character.
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Confirm Password</label>
            <input
              type="password"
              value={form.confirmPassword}
              onChange={(e) => setForm({ ...form, confirmPassword: e.target.value })}
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex flex-col gap-2 pt-2 sm:flex-row">
            <button type="button" onClick={onClose}
              className="flex-1 border border-gray-300 rounded-lg py-2 text-sm hover:bg-gray-50">Cancel</button>
            <button type="submit" disabled={mutation.isPending}
              className="flex-1 bg-blue-700 text-white rounded-lg py-2 text-sm hover:bg-blue-800 disabled:opacity-50">
              {mutation.isPending ? 'Resetting...' : 'Reset'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function UserManagement() {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [resetUser, setResetUser] = useState(null)

  const { data: me } = useQuery({
    queryKey: ['users', 'me'],
    queryFn: () => api.get('/users/me').then((r) => r.data),
  })

  const { data: users = [], isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: () => api.get('/users').then((r) => r.data),
  })

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }) => api.patch(`/users/${id}`, { is_active }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries(['users']),
  })

  const changeRole = useMutation({
    mutationFn: ({ id, role }) => api.patch(`/users/${id}`, { role }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries(['users']),
  })

  return (
    <div className="p-8">
      <div className="flex flex-col gap-4 mb-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-gray-900">User Management</h1>
          <p className="text-sm text-gray-500 mt-1">Manage system users and role assignments</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {me && (
            <button onClick={() => setResetUser(me)}
              className="inline-flex items-center justify-center gap-2 border border-gray-300 bg-white text-gray-700 px-4 py-2 rounded-lg text-sm hover:bg-gray-50">
              <KeyRound size={16} /> Change My Password
            </button>
          )}
          <button onClick={() => setShowCreate(true)}
            className="inline-flex items-center justify-center gap-2 bg-blue-700 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-800">
            <UserPlus size={16} /> New User
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">User</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Email</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-40">Role</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-28">Status</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-24">Last Login</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-20">MFA</th>
              <th className="w-48"></th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
            )}
            {users.map((u) => (
              <tr key={u.id} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="px-4 py-3 font-medium text-gray-800">{u.username}</td>
                <td className="px-4 py-3 text-gray-500">{u.email}</td>
                <td className="px-4 py-3">
                  <select
                    value={u.role}
                    onChange={(e) => changeRole.mutate({ id: u.id, role: e.target.value })}
                    className={`text-xs px-2 py-1 rounded-full font-medium border-0 cursor-pointer ${ROLE_COLOR[u.role] || 'bg-gray-100'}`}
                  >
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${u.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                    {u.is_active ? <CheckCircle size={11} /> : <XCircle size={11} />}
                    {u.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs">
                  {u.last_login ? new Date(u.last_login).toLocaleDateString() : 'Never'}
                </td>
                <td className="px-4 py-3">
                  {u.mfa_enabled ? (
                    <span className="text-xs text-green-600 flex items-center gap-1"><Shield size={12} /> On</span>
                  ) : (
                    <span className="text-xs text-gray-400">Off</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-3">
                    <button
                      onClick={() => setResetUser(u)}
                      className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
                    >
                      <KeyRound size={12} /> Reset
                    </button>
                  <button
                    onClick={() => toggleActive.mutate({ id: u.id, is_active: !u.is_active })}
                    className="text-xs text-blue-600 hover:text-blue-800"
                  >
                    {u.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && <CreateUserModal onClose={() => setShowCreate(false)} />}
      {resetUser && <ResetPasswordModal user={resetUser} onClose={() => setResetUser(null)} />}
    </div>
  )
}
