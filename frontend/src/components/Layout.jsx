import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Shield, FolderOpen, Users, Clock, LogOut, ShieldCheck, Sparkles, Building2, BookOpen, ClipboardList, Database, Scale, MessageSquare, SlidersHorizontal, Menu, X } from 'lucide-react'
import api from '../api/client'
import CyberAssistantPanel from './CyberAssistantPanel'
import { CYBER_ASSISTANT_EVENT, openCyberAssistant } from './cyberAssistant'
import { clearTokens, getAccessToken, getRefreshToken } from '../utils/tokenStorage'

function NavItem({ to, icon: Icon, label, onClick }) {
  return (
    <Link
      to={to}
      onClick={onClick}
      className="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-300 hover:bg-blue-800 hover:text-white transition-colors text-sm"
    >
      <Icon size={16} />
      {label}
    </Link>
  )
}

export default function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [assistantSession, setAssistantSession] = useState(null)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  useEffect(() => {
    const handleOpen = (event) => {
      setAssistantSession({
        nonce: Date.now(),
        mode: event.detail?.mode || 'general',
        title: event.detail?.title || null,
        projectId: event.detail?.projectId ?? null,
        assessmentId: event.detail?.assessmentId ?? null,
        thinkingEffort: event.detail?.thinkingEffort || 'medium',
        attachments: event.detail?.attachments || [],
        initialPrompt: event.detail?.initialPrompt || '',
        hiddenInitialMessage: !!event.detail?.hiddenInitialMessage,
      })
    }
    window.addEventListener(CYBER_ASSISTANT_EVENT, handleOpen)
    return () => window.removeEventListener(CYBER_ASSISTANT_EVENT, handleOpen)
  }, [])

  useEffect(() => {
    setMobileNavOpen(false)
  }, [location.pathname])

  const logout = async () => {
    try {
      const refresh = getRefreshToken()
      if (refresh) await api.post('/auth/logout', { refresh_token: refresh })
    } catch {
      // Logout remains local when the server session is already unavailable.
    }
    clearTokens()
    navigate('/login')
  }

  const token = getAccessToken()
  let role = 'viewer'
  try {
    role = JSON.parse(atob(token.split('.')[1])).role
  } catch {
    // A missing or malformed token is handled as the least-privileged role.
  }

  const isAdmin = ['system_admin'].includes(role)
  const isSecurityOfficer = ['system_admin', 'security_officer'].includes(role)

  const navContent = (onNavigate) => (
    <>
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        <NavItem to="/projects" icon={FolderOpen} label="Projects" onClick={onNavigate} />
        <NavItem to="/control-catalog" icon={Scale} label="800-53 Reference" onClick={onNavigate} />
        <NavItem to="/common-controls" icon={Building2} label="Common Controls" onClick={onNavigate} />
        <NavItem to="/enterprise-policies" icon={BookOpen} label="Policy Library" onClick={onNavigate} />
        <NavItem to="/enterprise-procedures" icon={ClipboardList} label="Procedures" onClick={onNavigate} />
        <NavItem to="/assessment-policy" icon={SlidersHorizontal} label="Assessment Policy" onClick={onNavigate} />

        {isAdmin && (
          <>
            <div className="pt-3 pb-1 px-3 text-blue-400 text-xs font-semibold uppercase tracking-wide">
              Admin
            </div>
            <NavItem to="/users" icon={Users} label="Users" onClick={onNavigate} />
            <NavItem to="/admin/prompts" icon={Sparkles} label="Prompt Manager" onClick={onNavigate} />
            <NavItem to="/admin/ai-runtime" icon={Database} label="AI Runtime" onClick={onNavigate} />
          </>
        )}

        {isSecurityOfficer && (
          <>
            <div className="pt-3 pb-1 px-3 text-blue-400 text-xs font-semibold uppercase tracking-wide">
              Security
            </div>
            <NavItem to="/admin/dashboard" icon={ShieldCheck} label="Security Ops" onClick={onNavigate} />
            <NavItem to="/security/audit-log" icon={Clock} label="SOC Audit Log" onClick={onNavigate} />
          </>
        )}
      </nav>

      <div className="p-3 border-t border-blue-800">
        <button
          onClick={logout}
          className="flex items-center gap-2 w-full px-3 py-2 text-gray-300 hover:text-white hover:bg-blue-800 rounded-lg text-sm transition-colors"
        >
          <LogOut size={16} />
          Sign Out
        </button>
      </div>
    </>
  )

  return (
    <div className="min-h-dvh bg-gray-50 lg:flex">
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-blue-800 bg-blue-900 px-4 text-white shadow-sm lg:hidden">
        <button
          type="button"
          onClick={() => setMobileNavOpen(true)}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-blue-100 hover:bg-blue-800 hover:text-white"
          aria-label="Open navigation"
        >
          <Menu size={22} />
        </button>
        <div className="flex min-w-0 items-center gap-2 font-bold">
          <Shield size={18} className="flex-shrink-0" />
          <span className="truncate">ATO Bot</span>
        </div>
        <button
          type="button"
          onClick={() => openCyberAssistant({ mode: 'general', title: 'Cyber Assistant' })}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-blue-100 hover:bg-blue-800 hover:text-white"
          aria-label="Open cyber assistant"
        >
          <MessageSquare size={19} />
        </button>
      </header>

      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileNavOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-[min(18rem,86vw)] flex-col bg-blue-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-blue-800 p-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-white font-bold text-lg">
                  <Shield size={20} />
                  <span className="truncate">ATO Bot</span>
                </div>
                <p className="text-blue-300 text-xs mt-1">NIST 800-53 Rev 5</p>
              </div>
              <button
                type="button"
                onClick={() => setMobileNavOpen(false)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-blue-100 hover:bg-blue-800 hover:text-white"
                aria-label="Close navigation"
              >
                <X size={20} />
              </button>
            </div>
            {navContent(() => setMobileNavOpen(false))}
          </aside>
        </div>
      )}

      {/* Sidebar */}
      <aside className="hidden w-56 flex-shrink-0 bg-blue-900 lg:flex lg:h-dvh lg:flex-col">
        <div className="p-4 border-b border-blue-800">
          <div className="flex items-center gap-2 text-white font-bold text-lg">
            <Shield size={20} />
            ATO Bot
          </div>
          <p className="text-blue-300 text-xs mt-1">NIST 800-53 Rev 5</p>
        </div>
        {navContent()}
      </aside>

      {/* Main content */}
      <main className="app-main min-w-0 flex-1 overflow-x-hidden lg:h-dvh lg:overflow-auto">
        <Outlet />
        <button
          type="button"
          onClick={() => openCyberAssistant({ mode: 'general', title: 'Cyber Assistant' })}
          className="fixed bottom-4 right-4 z-30 hidden items-center gap-2 rounded-full bg-violet-600 px-4 py-3 text-white shadow-lg transition-colors hover:bg-violet-700 sm:inline-flex"
        >
          <MessageSquare size={16} />
          Cyber Assistant
        </button>
      </main>

      {assistantSession && (
        <CyberAssistantPanel
          session={assistantSession}
          onClose={() => setAssistantSession(null)}
        />
      )}
    </div>
  )
}
