import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Server, Wifi, WifiOff, Smartphone, Building2, Users, Globe,
  HardDrive, CheckCircle2, XCircle, AlertCircle, ChevronDown,
  ChevronRight, Save, Pencil, Plus, RotateCcw,
} from 'lucide-react'
import api from '../api/client'

const DEPLOYMENT_OPTIONS = [
  { value: 'saas', label: 'SaaS', desc: 'Software as a Service — fully hosted by provider' },
  { value: 'paas', label: 'PaaS', desc: 'Platform as a Service — app runs on provider platform' },
  { value: 'iaas', label: 'IaaS', desc: 'Infrastructure as a Service — VMs/storage on cloud' },
  { value: 'on_premise', label: 'On-Premise', desc: 'Org-owned and operated data center' },
  { value: 'hybrid', label: 'Hybrid', desc: 'Mix of cloud and on-premise components' },
]

const INFRA_OPTIONS = [
  { value: 'org_owned', label: 'Org-Owned', desc: 'Organization owns and operates all infrastructure' },
  { value: 'fedramp_inherited', label: 'FedRAMP Inherited', desc: 'Infrastructure covered by FedRAMP authorization' },
  { value: 'third_party', label: 'Third-Party', desc: 'Non-FedRAMP third-party provider' },
  { value: 'mixed', label: 'Mixed', desc: 'Combination of ownership models' },
]

const USER_OPTIONS = [
  { value: 'internal_only', label: 'Internal Only', desc: 'Org employees and contractors only' },
  { value: 'external_users', label: 'Includes External Users', desc: 'Public or partner users access the system' },
  { value: 'automated_only', label: 'Automated Only', desc: 'No interactive human users; system-to-system only' },
  { value: 'mixed', label: 'Mixed', desc: 'Both internal and external users' },
]

const FAMILY_COLORS = {
  PE: 'bg-orange-50 text-orange-700 border-orange-200',
  MA: 'bg-yellow-50 text-yellow-700 border-yellow-200',
  MP: 'bg-amber-50 text-amber-700 border-amber-200',
  AC: 'bg-blue-50 text-blue-700 border-blue-200',
  IA: 'bg-purple-50 text-purple-700 border-purple-200',
}

const DEFAULT_FORM = {
  deployment_model: 'on_premise',
  infrastructure_ownership: 'org_owned',
  has_wireless_networking: true,
  has_external_connections: true,
  has_physical_facilities: true,
  has_mobile_devices: true,
  has_removable_media: true,
  user_population: 'mixed',
  publicly_accessible: true,
  notes: '',
}

function Select({ label, value, onChange, options }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300 bg-white"
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label} — {o.desc}</option>
        ))}
      </select>
    </div>
  )
}

function Toggle({ label, desc, value, onChange }) {
  return (
    <label className="flex items-start gap-3 cursor-pointer group">
      <div
        onClick={() => onChange(!value)}
        className={`relative mt-0.5 w-9 h-5 rounded-full transition-colors flex-shrink-0 ${value ? 'bg-blue-500' : 'bg-gray-300'}`}
      >
        <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${value ? 'translate-x-4' : ''}`} />
      </div>
      <div>
        <p className="text-sm font-medium text-gray-700 group-hover:text-gray-900">{label}</p>
        <p className="text-xs text-gray-400">{desc}</p>
      </div>
    </label>
  )
}

function NaList({ naControls }) {
  const [open, setOpen] = useState(false)
  const grouped = naControls.reduce((acc, { control_id, rationale }) => {
    const family = control_id.split('-')[0]
    if (!acc[family]) acc[family] = []
    acc[family].push({ control_id, rationale })
    return acc
  }, {})

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 text-sm font-medium text-gray-700"
      >
        <span className="flex items-center gap-2">
          <XCircle size={14} className="text-gray-400" />
          {naControls.length} controls auto-determined N/A
        </span>
        <ChevronDown size={14} className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="divide-y divide-gray-100">
          {Object.entries(grouped).sort().map(([family, items]) => (
            <div key={family} className="px-4 py-3">
              <div className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded border font-medium mb-2 ${FAMILY_COLORS[family] || 'bg-gray-50 text-gray-600 border-gray-200'}`}>
                {family}
              </div>
              <div className="space-y-1">
                {items.map(({ control_id, rationale }) => (
                  <div key={control_id} className="flex items-start gap-2 text-xs">
                    <span className="font-mono font-medium text-gray-700 w-20 flex-shrink-0">{control_id}</span>
                    <span className="text-gray-500">{rationale}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function SystemProfile({ projectId }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState(DEFAULT_FORM)

  const { data: profile, isLoading } = useQuery({
    queryKey: ['system-profile', projectId],
    queryFn: () => api.get(`/projects/${projectId}/system-profile`).then(r => r.data).catch(e => {
      if (e.response?.status === 404) return null
      throw e
    }),
  })

  const saveMutation = useMutation({
    mutationFn: (body) => profile
      ? api.put(`/projects/${projectId}/system-profile`, body)
      : api.post(`/projects/${projectId}/system-profile`, body),
    onSuccess: () => {
      qc.invalidateQueries(['system-profile', projectId])
      setEditing(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.delete(`/projects/${projectId}/system-profile`),
    onSuccess: () => qc.invalidateQueries(['system-profile', projectId]),
  })

  const startEdit = () => {
    setForm(profile ? {
      deployment_model: profile.deployment_model,
      infrastructure_ownership: profile.infrastructure_ownership,
      has_wireless_networking: profile.has_wireless_networking,
      has_external_connections: profile.has_external_connections,
      has_physical_facilities: profile.has_physical_facilities,
      has_mobile_devices: profile.has_mobile_devices,
      has_removable_media: profile.has_removable_media,
      user_population: profile.user_population,
      publicly_accessible: profile.publicly_accessible,
      notes: profile.notes || '',
    } : DEFAULT_FORM)
    setEditing(true)
  }

  const set = (key, val) => setForm(f => ({ ...f, [key]: val }))

  if (isLoading) return null

  if (!profile && !editing) {
    return (
      <div className="border border-dashed border-blue-200 rounded-xl p-5 bg-blue-50/50">
        <div className="flex items-start gap-3">
          <AlertCircle size={18} className="text-blue-400 mt-0.5 flex-shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-blue-800">System Profile Not Set</p>
            <p className="text-xs text-blue-600 mt-0.5">
              Define your system's characteristics to automatically determine N/A controls before running assessments.
              This prevents wasted assessment cycles on controls like physical security for cloud-hosted systems.
            </p>
            <button
              onClick={startEdit}
              className="mt-3 flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
            >
              <Plus size={13} /> Set Up System Profile
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (editing) {
    return (
      <div className="border border-blue-200 rounded-xl bg-white overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800">System Profile</h3>
          <button onClick={() => setEditing(false)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
        </div>
        <div className="p-5 space-y-5">
          <div className="grid grid-cols-2 gap-4">
            <Select label="Deployment Model" value={form.deployment_model}
              onChange={v => set('deployment_model', v)} options={DEPLOYMENT_OPTIONS} />
            <Select label="Infrastructure Ownership" value={form.infrastructure_ownership}
              onChange={v => set('infrastructure_ownership', v)} options={INFRA_OPTIONS} />
            <Select label="User Population" value={form.user_population}
              onChange={v => set('user_population', v)} options={USER_OPTIONS} />
          </div>

          <div>
            <p className="text-xs font-medium text-gray-600 mb-3">System Characteristics</p>
            <div className="grid grid-cols-2 gap-4">
              <Toggle label="Has Physical Facilities" desc="Org-operated data center or office space"
                value={form.has_physical_facilities} onChange={v => set('has_physical_facilities', v)} />
              <Toggle label="Has Wireless Networking" desc="Wi-Fi or other wireless in system boundary"
                value={form.has_wireless_networking} onChange={v => set('has_wireless_networking', v)} />
              <Toggle label="Has Mobile Devices" desc="Smartphones, tablets in system boundary"
                value={form.has_mobile_devices} onChange={v => set('has_mobile_devices', v)} />
              <Toggle label="Has Removable Media" desc="USB drives, optical discs, portable storage"
                value={form.has_removable_media} onChange={v => set('has_removable_media', v)} />
              <Toggle label="Has External Connections" desc="Internet-facing or inter-system connections"
                value={form.has_external_connections} onChange={v => set('has_external_connections', v)} />
              <Toggle label="Publicly Accessible" desc="Accessible by members of the public"
                value={form.publicly_accessible} onChange={v => set('publicly_accessible', v)} />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Notes / Rationale</label>
            <textarea
              value={form.notes}
              onChange={e => set('notes', e.target.value)}
              rows={2}
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300 resize-y"
              placeholder="Document any special circumstances or overrides..."
            />
          </div>

          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={() => saveMutation.mutate(form)}
              disabled={saveMutation.isPending}
              className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              <Save size={13} /> {saveMutation.isPending ? 'Saving…' : 'Save Profile'}
            </button>
            {saveMutation.isError && (
              <span className="text-xs text-red-600">
                {saveMutation.error?.response?.data?.detail || 'Save failed'}
              </span>
            )}
          </div>
        </div>
      </div>
    )
  }

  // Profile exists — show summary
  const depLabel = DEPLOYMENT_OPTIONS.find(o => o.value === profile.deployment_model)?.label || profile.deployment_model
  const infraLabel = INFRA_OPTIONS.find(o => o.value === profile.infrastructure_ownership)?.label || profile.infrastructure_ownership
  const userLabel = USER_OPTIONS.find(o => o.value === profile.user_population)?.label || profile.user_population

  return (
    <div className="border border-gray-200 rounded-xl bg-white overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
          <CheckCircle2 size={14} className="text-green-500" />
          System Profile
        </h3>
        <button onClick={startEdit} className="flex items-center gap-1 text-xs text-gray-400 hover:text-blue-600 transition-colors">
          <Pencil size={11} /> Edit
        </button>
      </div>
      <div className="px-5 py-4 space-y-3">
        <div className="flex flex-wrap gap-2">
          {[
            { icon: Server, label: depLabel },
            { icon: Building2, label: infraLabel },
            { icon: Users, label: userLabel },
            { icon: profile.has_wireless_networking ? Wifi : WifiOff,
              label: profile.has_wireless_networking ? 'Wireless' : 'No Wireless',
              dim: !profile.has_wireless_networking },
            { icon: Smartphone, label: profile.has_mobile_devices ? 'Mobile Devices' : 'No Mobile',
              dim: !profile.has_mobile_devices },
            { icon: HardDrive, label: profile.has_removable_media ? 'Removable Media' : 'No Removable Media',
              dim: !profile.has_removable_media },
            { icon: Globe, label: profile.publicly_accessible ? 'Public-Facing' : 'Not Public',
              dim: !profile.publicly_accessible },
          ].map(({ icon: Icon, label, dim }) => (
            <span key={label} className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border ${dim ? 'bg-gray-50 text-gray-400 border-gray-200' : 'bg-blue-50 text-blue-700 border-blue-200'}`}>
              <Icon size={11} /> {label}
            </span>
          ))}
        </div>

        {profile.na_count > 0 && (
          <NaList naControls={profile.na_controls} />
        )}

        {profile.notes && (
          <p className="text-xs text-gray-500 italic">{profile.notes}</p>
        )}
      </div>
    </div>
  )
}
