import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, FolderOpen, ChevronRight, Trash2 } from 'lucide-react'
import api from '../api/client'

const BASELINE_COLORS = {
  low: 'bg-green-100 text-green-800',
  moderate: 'bg-yellow-100 text-yellow-800',
  high: 'bg-red-100 text-red-800',
}

export default function ProjectList() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ name: '', description: '', system_type: '', impact_baseline: 'moderate' })

  const { data: projects = [], isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get('/projects').then((r) => r.data),
  })

  const [confirmDelete, setConfirmDelete] = useState(null) // project to delete

  const createProject = useMutation({
    mutationFn: (data) => api.post('/projects', data),
    onSuccess: () => {
      qc.invalidateQueries(['projects'])
      setShowCreate(false)
      setForm({ name: '', description: '', system_type: '', impact_baseline: 'moderate' })
    },
  })

  const deleteProject = useMutation({
    mutationFn: (projectId) => api.delete(`/projects/${projectId}`),
    onSuccess: () => {
      qc.invalidateQueries(['projects'])
      setConfirmDelete(null)
    },
  })

  return (
    <div className="p-8">
      <div className="flex flex-col gap-4 mb-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-gray-900">Projects</h1>
          <p className="text-gray-500 text-sm mt-1">Manage system assessments</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="inline-flex items-center justify-center gap-2 bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-800 transition-colors sm:w-auto"
        >
          <Plus size={16} />
          New Project
        </button>
      </div>

      {/* Create modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl p-5 w-full max-w-md shadow-2xl sm:p-6">
            <h2 className="text-lg font-bold mb-4">New Project</h2>
            <form
              onSubmit={(e) => { e.preventDefault(); createProject.mutate(form) }}
              className="space-y-4"
            >
              <div>
                <label className="block text-sm font-medium mb-1">System Name *</label>
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Description</label>
                <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
                  rows={2} className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">System Type</label>
                <input value={form.system_type} onChange={(e) => setForm({ ...form, system_type: e.target.value })}
                  className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. Web Application, SaaS, On-premise" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Impact Baseline *</label>
                <select value={form.impact_baseline} onChange={(e) => setForm({ ...form, impact_baseline: e.target.value })}
                  className="w-full border rounded-lg px-3 py-2 text-sm">
                  <option value="low">Low (~168 controls)</option>
                  <option value="moderate">Moderate (~330 controls)</option>
                  <option value="high">High (~580 controls)</option>
                </select>
              </div>
              <div className="flex flex-col gap-3 pt-2 sm:flex-row">
                <button type="button" onClick={() => setShowCreate(false)}
                  className="flex-1 border rounded-lg py-2 text-sm hover:bg-gray-50">Cancel</button>
                <button type="submit" disabled={createProject.isPending}
                  className="flex-1 bg-blue-700 text-white rounded-lg py-2 text-sm hover:bg-blue-800 disabled:opacity-50">
                  {createProject.isPending ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Confirm delete modal */}
      {confirmDelete && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl p-5 w-full max-w-sm shadow-2xl sm:p-6">
            <h2 className="text-lg font-bold text-gray-900 mb-2">Delete Project?</h2>
            <p className="text-sm text-gray-600 mb-1">
              This will permanently delete <span className="font-semibold">{confirmDelete.name}</span> and all associated data:
            </p>
            <ul className="text-sm text-gray-500 list-disc ml-5 mb-5 space-y-0.5">
              <li>All documents and embeddings</li>
              <li>All assessments and findings</li>
              <li>All control overrides and activity logs</li>
            </ul>
            <p className="text-sm font-medium text-red-600 mb-4">This action cannot be undone.</p>
            <div className="flex flex-col gap-3 sm:flex-row">
              <button onClick={() => setConfirmDelete(null)}
                className="flex-1 border rounded-lg py-2 text-sm hover:bg-gray-50">Cancel</button>
              <button
                onClick={() => deleteProject.mutate(confirmDelete.id)}
                disabled={deleteProject.isPending}
                className="flex-1 bg-red-600 text-white rounded-lg py-2 text-sm hover:bg-red-700 disabled:opacity-50"
              >
                {deleteProject.isPending ? 'Deleting...' : 'Delete Project'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Project list */}
      {isLoading ? (
        <div className="text-gray-400 text-center py-12">Loading projects...</div>
      ) : projects.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <FolderOpen size={48} className="mx-auto mb-3 opacity-30" />
          <p>No projects yet. Create your first assessment project.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {projects.map((p) => (
            <div
              key={p.id}
              onClick={() => navigate(`/projects/${p.id}`)}
              className="bg-white rounded-xl border border-gray-200 p-4 hover:border-blue-300 hover:shadow-sm cursor-pointer transition-all flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between sm:p-5"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                  <h3 className="font-semibold text-gray-900">{p.name}</h3>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${BASELINE_COLORS[p.impact_baseline] || 'bg-gray-100 text-gray-800'}`}>
                    {p.impact_baseline.toUpperCase()}
                  </span>
                </div>
                {p.description && <p className="text-gray-500 text-sm mt-1">{p.description}</p>}
                <p className="text-gray-400 text-xs mt-1">
                  {p.system_type && `${p.system_type} · `}
                  Created {new Date(p.created_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex items-center gap-3 self-end sm:self-auto">
                <button
                  onClick={(e) => { e.stopPropagation(); setConfirmDelete(p) }}
                  className="p-1.5 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                  title="Delete project"
                >
                  <Trash2 size={16} />
                </button>
                <ChevronRight size={20} className="text-gray-400" />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
