import { useEffect, useMemo, useRef, useState } from 'react'
import {
  MessageSquare, Paperclip, Pencil, Plus, Send, Shield, Sparkles, Trash2, Upload, X,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '../api/client'

const MODE_LABELS = {
  general: 'Cyber Assistant',
  workspace: 'Workspace Assistant',
  control: 'Control Assistant',
  remediation: 'Remediation Assistant',
  admin_runtime: 'Runtime Assistant',
}

function fmt(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

function AssistantMessageBody({ content, isUser }) {
  if (isUser) {
    return <div className="whitespace-pre-wrap">{content}</div>
  }

  return (
    <div className="assistant-markdown text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ node, ...props }) => <h1 className="text-lg font-semibold mt-1 mb-3" {...props} />,
          h2: ({ node, ...props }) => <h2 className="text-base font-semibold mt-1 mb-2.5" {...props} />,
          h3: ({ node, ...props }) => <h3 className="text-sm font-semibold mt-1 mb-2" {...props} />,
          p: ({ node, ...props }) => <p className="mb-3 last:mb-0" {...props} />,
          ul: ({ node, ...props }) => <ul className="list-disc pl-5 mb-3 space-y-1" {...props} />,
          ol: ({ node, ...props }) => <ol className="list-decimal pl-5 mb-3 space-y-1" {...props} />,
          li: ({ node, ...props }) => <li className="leading-relaxed" {...props} />,
          blockquote: ({ node, ...props }) => (
            <blockquote className="border-l-4 border-violet-200 pl-3 italic text-gray-700 mb-3" {...props} />
          ),
          code: ({ inline, className, children, ...props }) => (
            inline ? (
              <code className="rounded bg-gray-200 px-1 py-0.5 text-[0.95em]" {...props}>{children}</code>
            ) : (
              <code className="block rounded-xl bg-gray-900 text-gray-100 p-3 overflow-x-auto text-xs" {...props}>
                {children}
              </code>
            )
          ),
          pre: ({ node, ...props }) => <pre className="mb-3" {...props} />,
          table: ({ node, ...props }) => (
            <div className="mb-3 overflow-x-auto">
              <table className="min-w-full border border-gray-200 text-xs" {...props} />
            </div>
          ),
          thead: ({ node, ...props }) => <thead className="bg-gray-100" {...props} />,
          th: ({ node, ...props }) => <th className="border border-gray-200 px-2 py-1.5 text-left font-semibold" {...props} />,
          td: ({ node, ...props }) => <td className="border border-gray-200 px-2 py-1.5 align-top" {...props} />,
          hr: ({ node, ...props }) => <hr className="my-4 border-gray-200" {...props} />,
          a: ({ node, ...props }) => <a className="text-violet-700 underline" target="_blank" rel="noreferrer" {...props} />,
        }}
      >
        {content || ''}
      </ReactMarkdown>
    </div>
  )
}

export default function CyberAssistantPanel({ session, onClose }) {
  const [conversationList, setConversationList] = useState([])
  const [conversation, setConversation] = useState(null)
  const [messages, setMessages] = useState([])
  const [attachments, setAttachments] = useState([])
  const [suggestions, setSuggestions] = useState([])
  const [input, setInput] = useState('')
  const [thinkingEffort, setThinkingEffort] = useState(session?.thinkingEffort || 'medium')
  const [booting, setBooting] = useState(false)
  const [sending, setSending] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const sessionTemplateRef = useRef(session)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const fileInputRef = useRef(null)
  const panelRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, booting, sending])

  useEffect(() => {
    const handleWindowPaste = async (e) => {
      if (!panelRef.current?.contains(document.activeElement)) return
      const clipboardFiles = Array.from(e.clipboardData?.files || []).filter(Boolean)
      const itemFiles = Array.from(e.clipboardData?.items || [])
        .map((item) => (item.kind === 'file' ? item.getAsFile() : null))
        .filter(Boolean)
      const files = clipboardFiles.length ? clipboardFiles : itemFiles
      if (!files.length) return
      e.preventDefault()
      await uploadFiles(files)
    }

    window.addEventListener('paste', handleWindowPaste)
    return () => window.removeEventListener('paste', handleWindowPaste)
  }, [conversation?.id, uploading, booting, sending])

  const fetchConversationList = async () => {
    const res = await api.get('/assistant/conversations')
    setConversationList(res.data.items || [])
    return res.data.items || []
  }

  const fetchSuggestions = async (mode) => {
    const sugg = await api.get('/assistant/suggestions', { params: { mode: mode || 'general' } })
    setSuggestions(sugg.data.suggestions || [])
  }

  const loadConversation = async (conversationId) => {
    setBooting(true)
    try {
      const res = await api.get(`/assistant/conversations/${conversationId}`)
      const payload = res.data
      setConversation(payload.conversation)
      setMessages(payload.messages || [])
      setAttachments(payload.attachments || [])
      await fetchSuggestions(payload.conversation?.mode || 'general')
    } finally {
      setBooting(false)
      setTimeout(() => inputRef.current?.focus(), 40)
    }
  }

  const createConversationFromSession = async (seedSession) => {
    setBooting(true)
    setConversation(null)
    setMessages([])
    setAttachments([])
    setInput('')
    try {
      const res = await api.post('/assistant/conversations', {
        mode: seedSession?.mode || 'general',
        title: seedSession?.title || null,
        project_id: seedSession?.projectId ?? null,
        assessment_id: seedSession?.assessmentId ?? null,
        attachments: (seedSession?.attachments || []).map((a) => ({
          type: a.attachment_type || a.type,
          resource_id: a.resource_id || '',
          label: a.label,
          context_json: a.context_json || {},
        })),
      })
      const payload = res.data
      setConversation(payload.conversation)
      setMessages(payload.messages || [])
      setAttachments(payload.attachments || [])
      await fetchConversationList()
      await fetchSuggestions(payload.conversation?.mode || 'general')

      if (seedSession?.initialPrompt) {
        const intro = await api.post(`/assistant/conversations/${payload.conversation.id}/messages`, {
          content: seedSession.initialPrompt,
          hidden: !!seedSession.hiddenInitialMessage,
          thinking_effort: seedSession.thinkingEffort || 'medium',
        })
        setConversation(intro.data.conversation)
        setMessages(intro.data.messages || [])
        setAttachments(intro.data.attachments || [])
        await fetchConversationList()
      }
    } catch (e) {
      setMessages([{
        id: 'error',
        role: 'assistant',
        content: `Assistant failed to start: ${e.response?.data?.detail || e.message}`,
        metadata_json: {},
      }])
    } finally {
      setBooting(false)
      setTimeout(() => inputRef.current?.focus(), 40)
    }
  }

  useEffect(() => {
    if (!session?.nonce) return
    let cancelled = false
    const init = async () => {
      sessionTemplateRef.current = session
      setThinkingEffort(session?.thinkingEffort || 'medium')
      try {
        await fetchConversationList()
        if (!cancelled) {
          await createConversationFromSession(session)
        }
      } catch (e) {
        if (!cancelled) {
          setMessages([{
            id: 'error',
            role: 'assistant',
            content: `Assistant failed to start: ${e.response?.data?.detail || e.message}`,
            metadata_json: {},
          }])
        }
      }
    }
    init()
    return () => { cancelled = true }
  }, [session?.nonce])

  const visibleMessages = useMemo(
    () => messages.filter((msg) => !msg.metadata_json?.hidden),
    [messages],
  )

  const sendMessage = async (explicitText = null) => {
    const text = (explicitText ?? input).trim()
    if (!conversation?.id || !text || sending) return
    setInput('')
    setSending(true)
    try {
      const res = await api.post(`/assistant/conversations/${conversation.id}/messages`, {
        content: text,
        thinking_effort: thinkingEffort,
      })
      setConversation(res.data.conversation)
      setMessages(res.data.messages || [])
      setAttachments(res.data.attachments || [])
      await fetchConversationList()
    } catch (e) {
      setMessages((prev) => [...prev, {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `Error: ${e.response?.data?.detail || e.message}`,
        metadata_json: {},
      }])
    } finally {
      setSending(false)
      setTimeout(() => inputRef.current?.focus(), 40)
    }
  }

  const uploadFiles = async (fileList) => {
    const files = Array.from(fileList || []).filter(Boolean)
    if (!conversation?.id || files.length === 0 || uploading) return
    setUploading(true)
    try {
      const form = new FormData()
      files.forEach((file) => form.append('files', file))
      const res = await api.post(`/assistant/conversations/${conversation.id}/files`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setAttachments((prev) => [...prev, ...(res.data.attachments || [])])
      await fetchConversationList()
      setMessages((prev) => [...prev, {
        id: `upload-${Date.now()}`,
        role: 'assistant',
        content: `Attached ${files.length} file${files.length === 1 ? '' : 's'} to this chat context.`,
        metadata_json: {},
      }])
    } catch (e) {
      setMessages((prev) => [...prev, {
        id: `upload-error-${Date.now()}`,
        role: 'assistant',
        content: `File upload failed: ${e.response?.data?.detail || e.message}`,
        metadata_json: {},
      }])
    } finally {
      setUploading(false)
      setDragActive(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
      setTimeout(() => inputRef.current?.focus(), 40)
    }
  }

  const handleFilePicker = async (e) => {
    await uploadFiles(e.target.files)
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    if (!conversation?.id || booting || sending || uploading) return
    setDragActive(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setDragActive(false)
  }

  const handleDrop = async (e) => {
    e.preventDefault()
    if (!conversation?.id || booting || sending || uploading) {
      setDragActive(false)
      return
    }
    const files = e.dataTransfer?.files
    await uploadFiles(files)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const handlePaste = async (e) => {
    const clipboardFiles = Array.from(e.clipboardData?.files || []).filter(Boolean)
    const itemFiles = Array.from(e.clipboardData?.items || [])
      .map((item) => (item.kind === 'file' ? item.getAsFile() : null))
      .filter(Boolean)
    const files = clipboardFiles.length ? clipboardFiles : itemFiles

    if (!files.length) return

    e.preventDefault()
    await uploadFiles(files)
  }

  const handleRename = async (item) => {
    const next = window.prompt('Rename chat', item.title || '')
    if (!next || !next.trim()) return
    await api.patch(`/assistant/conversations/${item.id}`, { title: next.trim() })
    await fetchConversationList()
    if (conversation?.id === item.id) {
      setConversation((prev) => ({ ...prev, title: next.trim() }))
    }
  }

  const handleDelete = async (item) => {
    if (!window.confirm(`Delete "${item.title || 'this chat'}"?`)) return
    await api.delete(`/assistant/conversations/${item.id}`)
    const remaining = await fetchConversationList()
    if (conversation?.id === item.id) {
      if (remaining.length > 0) {
        await loadConversation(remaining[0].id)
      } else {
        await createConversationFromSession({
          ...sessionTemplateRef.current,
          title: null,
          initialPrompt: '',
          hiddenInitialMessage: false,
        })
      }
    }
  }

  const handleNewChat = async () => {
    await createConversationFromSession({
      ...sessionTemplateRef.current,
      title: null,
      initialPrompt: '',
      hiddenInitialMessage: false,
    })
  }

  const title = conversation?.title || session?.title || MODE_LABELS[session?.mode || 'general'] || 'Cyber Assistant'

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div ref={panelRef} className="fixed inset-0 bg-white shadow-2xl z-50 flex md:left-auto md:w-[980px] md:max-w-full">
        <aside className="hidden w-[300px] max-w-[42%] border-r border-gray-200 bg-white md:flex md:flex-col">
          <div className="flex items-start justify-between px-4 py-4 border-b bg-violet-50">
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <Shield size={13} className="text-violet-600 flex-shrink-0" />
                <span className="text-xs font-semibold text-violet-600 uppercase tracking-wide">
                  Conversation Manager
                </span>
              </div>
              <p className="text-base font-bold text-gray-900 truncate">Cyber Assistant</p>
              <p className="text-xs text-gray-600 mt-0.5">
                Multiple chats, context-specific threads, and reusable history.
              </p>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 ml-3 mt-0.5 flex-shrink-0">
              <X size={18} />
            </button>
          </div>

          <div className="p-3 border-b border-gray-100">
            <button
              type="button"
              onClick={handleNewChat}
              className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 text-white px-3 py-2.5 text-sm font-medium hover:bg-violet-700 transition-colors"
            >
              <Plus size={15} />
              New Chat
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {conversationList.length === 0 && (
              <div className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-3 text-xs text-gray-500">
                No saved conversations yet.
              </div>
            )}
            {conversationList.map((item) => (
              <div
                key={item.id}
                className={`rounded-xl border p-3 transition-colors ${
                  conversation?.id === item.id
                    ? 'border-violet-200 bg-violet-50'
                    : 'border-gray-200 bg-white hover:bg-gray-50'
                }`}
              >
                <button
                  type="button"
                  onClick={() => loadConversation(item.id)}
                  className="w-full text-left"
                >
                  <div className="flex items-start gap-2">
                    <MessageSquare size={14} className="text-violet-500 mt-0.5 flex-shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold text-gray-900 truncate">
                        {item.title || 'Untitled chat'}
                      </div>
                      <div className="mt-1 text-[11px] text-gray-500 line-clamp-2">
                        {item.last_message_preview || item.attachment_labels?.join(' - ') || 'No messages yet'}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {(item.attachment_labels || []).slice(0, 2).map((label) => (
                          <span
                            key={label}
                            className="inline-flex items-center rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-medium text-violet-700"
                          >
                            {label}
                          </span>
                        ))}
                      </div>
                      <div className="mt-2 text-[10px] uppercase tracking-wide text-gray-400">
                        {item.mode} - {fmt(item.updated_at)}
                      </div>
                    </div>
                  </div>
                </button>
                <div className="mt-3 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleRename(item)}
                    className="inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-violet-700"
                  >
                    <Pencil size={11} />
                    Rename
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(item)}
                    className="inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-red-600"
                  >
                    <Trash2 size={11} />
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </aside>

        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex items-start justify-between px-4 py-3 border-b bg-violet-50 flex-shrink-0 sm:px-5 sm:py-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1">
                <Shield size={13} className="text-violet-600 flex-shrink-0" />
                <span className="text-xs font-semibold text-violet-600 uppercase tracking-wide">
                  {MODE_LABELS[conversation?.mode || session?.mode || 'general'] || 'Cyber Assistant'}
                </span>
              </div>
              <p className="text-base font-bold text-gray-900 truncate">{title}</p>
              <p className="text-xs text-gray-600 mt-0.5">
                Ask general cyber questions or use the attached project context when present.
              </p>
            </div>
            <button onClick={onClose} className="ml-3 mt-0.5 flex-shrink-0 text-gray-400 hover:text-gray-600 md:hidden">
              <X size={18} />
            </button>
          </div>

          <div className="px-4 py-3 bg-gray-50 border-b flex-shrink-0 sm:px-5">
            <div className="min-w-0">
              <p className="text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">Active Context</p>
              <div className="flex flex-wrap gap-2">
                {(attachments.length ? attachments : [{ id: 'general', label: 'General Cyber Chat' }]).map((item) => (
                  <span
                    key={item.id}
                    className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-violet-100 text-violet-700 font-medium"
                  >
                    <Sparkles size={10} />
                    {item.label}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4 min-h-0 sm:px-4 sm:py-4">
            {booting && (
              <div className="flex justify-start">
                <div className="bg-gray-100 rounded-2xl rounded-bl-md px-4 py-3">
                  <div className="flex gap-1.5 items-center">
                    {[0, 150, 300].map((delay) => (
                      <span key={delay} className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: `${delay}ms` }} />
                    ))}
                  </div>
                </div>
              </div>
            )}

            {!booting && visibleMessages.length === 0 && (
              <div className="bg-violet-50 border border-violet-200 rounded-2xl px-4 py-3 text-sm text-violet-900">
                Start with a question about this control, remediation area, assessment, or cyber topic.
              </div>
            )}

            {visibleMessages.map((msg) => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[88%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-violet-600 text-white rounded-br-md'
                    : 'bg-gray-100 text-gray-800 rounded-bl-md'
                }`}>
                  <AssistantMessageBody content={msg.content} isUser={msg.role === 'user'} />
                </div>
              </div>
            ))}

            {sending && (
              <div className="flex justify-start">
                <div className="bg-gray-100 rounded-2xl rounded-bl-md px-4 py-3">
                  <div className="flex gap-1.5 items-center">
                    {[0, 150, 300].map((delay) => (
                      <span key={delay} className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: `${delay}ms` }} />
                    ))}
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div
            className={`px-4 py-3 border-t bg-gray-50 flex-shrink-0 transition-colors ${
              dragActive ? 'bg-violet-50 border-violet-200' : ''
            }`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {suggestions.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {suggestions.slice(0, 3).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => sendMessage(s)}
                    className="text-xs px-2.5 py-1 rounded-full border border-violet-200 bg-white text-violet-700 hover:bg-violet-50"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            <div className="flex flex-col items-stretch gap-3 mb-3 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  onChange={handleFilePicker}
                  className="hidden"
                  accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.png,.jpg,.jpeg,.gif,.tif,.tiff,.bmp,.txt,.md,.rst,.text,.vsd,.vsdx"
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={!conversation?.id || booting || sending || uploading}
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  {uploading ? <Upload size={13} className="animate-pulse" /> : <Paperclip size={13} />}
                  {uploading ? 'Attaching...' : 'Attach Files'}
                </button>
                <span className="text-[11px] text-gray-400">
                  Drop screenshots, PDFs, Office files, text, or diagrams here.
                </span>
              </div>
              <div className="w-full sm:w-44 sm:max-w-full">
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Thinking
                </label>
                <select
                  value={thinkingEffort}
                  onChange={(e) => setThinkingEffort(e.target.value)}
                  className="w-full rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-300"
                >
                  <option value="low">Low - faster</option>
                  <option value="medium">Medium - balanced</option>
                  <option value="high">High - slower</option>
                </select>
              </div>
            </div>
            <div className="flex gap-2 items-end">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                placeholder="Ask about evidence, controls, remediation, RMF, or the current workspace..."
                rows={2}
                disabled={booting || sending || !conversation?.id}
                className="flex-1 border border-gray-200 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-violet-300 disabled:opacity-50 bg-white"
              />
              <button
                type="button"
                onClick={() => sendMessage()}
                disabled={booting || sending || !input.trim() || !conversation?.id}
                className="bg-violet-600 text-white p-3 rounded-xl hover:bg-violet-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title="Send"
              >
                <Send size={16} />
              </button>
            </div>
            <p className="text-[11px] text-gray-400 mt-2">
              Enter to send. Shift+Enter for a new line. You can also paste screenshots from the clipboard.
            </p>
          </div>
        </div>
      </div>
    </>
  )
}
