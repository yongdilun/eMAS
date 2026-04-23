import { useState, useCallback, useEffect, useRef } from 'react'
import { aiApi, toData, toList, executeSuggestedCall, apiErrorMessage } from '../../../services/api'
import logger from '../../../services/logger'

export function extractJobId(aiResponse) {
  const entities = aiResponse?.entities || {}
  if (entities.job_id) return entities.job_id
  if (entities.job) return entities.job
  const suggested = aiResponse?.suggested_calls || []
  for (const call of suggested) {
    if (call.params?.job_id) return call.params.job_id
    if (call.path?.includes('/jobs/')) {
      const parts = call.path.split('/jobs/')[1]
      if (parts) return parts.split(/[/?]/)[0]
    }
  }
  return null
}

function normalizeMessage(m) {
  const role = m.role || (m.sender === 'user' ? 'user' : 'assistant')
  const content = m.content || m.text || m.message || ''
  let ts = m.timestamp || m.created_at || m.sent_at
  if (ts && typeof ts === 'string') {
    try {
      const d = new Date(ts)
      ts = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } catch { ts = '' }
  }
  return {
    id: m.id || m.message_id || `${Date.now()}-${Math.random()}`,
    role,
    content,
    timestamp: ts,
    intent: m.intent,
    confidence: m.confidence,
    ambiguous: m.ambiguous,
    clarifications: m.clarifications || [],
    resultCards: m.result_cards || m.resultCards || [],
    kind: m.kind,
    jobId: m.job_id || m.jobId,
    assist: m.assist,
    proposal: m.proposal,
    suggested_calls: m.suggested_calls || [],
    auto_calls: m.auto_calls || [],
    approval_calls: m.approval_calls || [],
    execution_mode: m.execution_mode,
    bdi_result: m.bdi_result,
  }
}

function normalizeConversation(c) {
  const id = c.id || c.chat_id || c.conversation_id
  const title = c.title || c.name || (c.messages?.[0]?.content ? `${String(c.messages[0].content).slice(0, 40)}...` : 'New conversation')
  return {
    id,
    title,
    created_at: c.created_at || c.createdAt,
    updated_at: c.updated_at || c.updatedAt,
  }
}

const is404 = (err) => err?.status === 404 || err?.original?.status === 404
const WRITE_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE']

function normalizeCall(call = {}) {
  const method = String(call.method || 'GET').toUpperCase()
  return { ...call, method }
}

function classifySuggestedCalls(calls = []) {
  const normalized = (Array.isArray(calls) ? calls : []).map(normalizeCall)
  const autoCalls = normalized.filter((c) => c.method === 'GET' && c.requires_approval === false)
  const approvalCalls = normalized.filter((c) => {
    if (c.requires_approval === true) return true
    return WRITE_METHODS.includes(c.method)
  })
  return { all: normalized, autoCalls, approvalCalls }
}

function buildResultCardsFromCall(call, raw) {
  const payload = toData(raw) ?? raw
  if (!payload) return []
  if (Array.isArray(payload?.result_cards)) return payload.result_cards

  const title = call?.purpose || `${call?.method || 'GET'} ${call?.path || ''}`
  const path = String(call?.path || '')

  if (path.includes('/delay-risk') && typeof payload === 'object' && !Array.isArray(payload)) {
    return [{
      kind: 'delay_risk',
      title: 'Delay Risk',
      tone: String(payload.risk_level || '').toLowerCase() === 'high' ? 'warning' : 'info',
      summary: payload.issue || 'Latest delay-risk estimate is available.',
      metrics: [
        payload.job_id != null ? { label: 'Job', value: String(payload.job_id) } : null,
        payload.risk_level != null ? { label: 'Risk', value: String(payload.risk_level) } : null,
        payload.risk_score != null ? { label: 'Score', value: Number(payload.risk_score).toFixed(1) } : null,
        payload.delay_minutes != null ? { label: 'Delay (mins)', value: String(payload.delay_minutes) } : null,
      ].filter(Boolean),
      bullets: Array.isArray(payload.reasons) ? payload.reasons.slice(0, 3) : [],
    }]
  }

  if (path.includes('/explanation') && typeof payload === 'object' && !Array.isArray(payload)) {
    return [{
      kind: 'job_explanation',
      title: 'Job Explanation',
      tone: 'info',
      summary: payload.summary || 'Planner-readable explanation.',
      metrics: payload.job_id != null ? [{ label: 'Job', value: String(payload.job_id) }] : [],
      bullets: Array.isArray(payload.key_points) ? payload.key_points.slice(0, 3) : [],
    }]
  }

  if (Array.isArray(payload)) {
    const preview = payload.slice(0, 4).map((v) => {
      if (typeof v === 'string') return v
      if (typeof v === 'object' && v) {
        return Object.entries(v)
          .slice(0, 3)
          .map(([k, val]) => `${k}: ${val}`)
          .join(', ')
      }
      return String(v)
    })
    return [{
      kind: 'api_list',
      title,
      tone: 'info',
      summary: `${payload.length} record${payload.length === 1 ? '' : 's'} found.`,
      bullets: preview,
    }]
  }

  if (typeof payload === 'object') {
    const metricsKeys = ['job_id', 'proposal_id', 'risk_level', 'risk_score', 'oee_pct', 'production_units', 'downtime_hrs', 'utilization_pct', 'status']
    const metrics = metricsKeys
      .filter((k) => payload[k] !== undefined && payload[k] !== null)
      .slice(0, 4)
      .map((k) => ({ label: k.replace(/_/g, ' '), value: String(payload[k]) }))

    const summary =
      payload.summary || payload.message || payload.title || (metrics.length ? 'Latest data loaded.' : 'Call completed successfully.')

    return [{
      kind: 'api_result',
      title,
      tone: 'info',
      summary,
      metrics,
    }]
  }

  return [{
    kind: 'api_result',
    title,
    tone: 'info',
    summary: String(payload),
  }]
}

export function useAiChat() {
  const [conversations, setConversations] = useState([])
  const [activeChatId, setActiveChatId] = useState(null)
  const [messages, setMessages] = useState([])
  const [activeTitle, setActiveTitle] = useState('New conversation')
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [chatsAvailable, setChatsAvailable] = useState(null)
  const [executingCallKey, setExecutingCallKey] = useState(null)
  const executedAutoCallKeysRef = useRef(new Set())

  const formatTime = () => {
    const d = new Date()
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  const appendMessage = useCallback((msg) => {
    const id = msg?.id || `${Date.now()}-${Math.random()}`
    setMessages((prev) => [
      ...prev,
      { id, timestamp: formatTime(), ...normalizeMessage({ ...msg, id }) },
    ])
    return id
  }, [])

  const fetchConversations = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const raw = await aiApi.chats.list()
      setChatsAvailable(true)
      const arr = toList(toData(raw) ?? raw)
      const list = (Array.isArray(arr) ? arr : []).map(normalizeConversation)
      setConversations(list)
      if (list.length > 0 && !activeChatId) {
        setActiveChatId(list[0].id)
      }
    } catch (err) {
      if (is404(err)) {
        setChatsAvailable(false)
        setConversations([])
      } else {
        logger.warn('Chat list unavailable', { message: err?.message })
        setConversations([])
        setError(err?.message || 'Could not load conversations')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchConversations()
  }, [])

  useEffect(() => {
    if (!activeChatId || chatsAvailable === false) {
      setMessages([])
      setActiveTitle(chatsAvailable === false ? 'Quick query (no history)' : 'New conversation')
      return
    }
    const loadChat = async () => {
      setLoading(true)
      setError(null)
      try {
        const raw = await aiApi.chats.get(activeChatId)
        const data = toData(raw) ?? raw
        const chat = data?.data ?? data
        const msgs = toList(chat?.messages ?? chat?.message_history ?? [])
        setMessages(msgs.map(normalizeMessage))
        setActiveTitle(chat?.title || chat?.name || 'Conversation')
      } catch (err) {
        if (is404(err)) {
          setChatsAvailable(false)
        }
        logger.warn('Chat load failed', { chatId: activeChatId, message: err?.message })
        setMessages([])
        setActiveTitle('Conversation')
        setError(err?.message || 'Could not load conversation')
      } finally {
        setLoading(false)
      }
    }
    loadChat()
  }, [activeChatId, chatsAvailable])

  const handleSelectChat = useCallback((id) => {
    setActiveChatId(id)
    setError(null)
  }, [])

  const handleNewConversation = useCallback(async () => {
    setError(null)
    if (chatsAvailable === false) {
      setActiveChatId(null)
      setMessages([])
      setInput('')
      setActiveTitle('Quick query (no history)')
      return
    }
    try {
      const raw = await aiApi.chats.create({})
      const data = toData(raw) ?? raw
      const chat = data?.data ?? data
      const id = chat?.id ?? chat?.chat_id ?? chat?.conversation_id
      if (id) {
        setConversations((prev) => [normalizeConversation({ ...chat, id }), ...prev])
        setActiveChatId(id)
        setMessages([])
        setInput('')
      }
    } catch (err) {
      if (is404(err)) {
        setChatsAvailable(false)
        setActiveChatId(null)
        setMessages([])
        setInput('')
        setActiveTitle('Quick query (no history)')
      } else {
        logger.error('Create chat failed', err)
        setError(err?.message || 'Could not create conversation')
      }
    }
  }, [chatsAvailable])

  const handleSchedulingAssist = useCallback(
    async (jobId) => {
      appendMessage({
        role: 'assistant',
        content: `Let me analyze the schedule for job ${jobId}…`,
      })
      try {
        const [assistRaw, proposalRaw] = await Promise.allSettled([
          aiApi.scheduling.assist(jobId),
          aiApi.scheduling.createProposal(jobId),
        ])

        if (assistRaw.status === 'fulfilled') {
          appendMessage({
            role: 'assistant',
            content: `Here is the current assist view for job ${jobId}.`,
            kind: 'assist',
            jobId,
            assist: assistRaw.value,
          })
        }

        if (proposalRaw.status === 'fulfilled') {
          appendMessage({
            role: 'assistant',
            content: `I generated a proposal for job ${jobId}. You can review, approve, or apply it.`,
            kind: 'proposal',
            jobId,
            proposal: proposalRaw.value,
          })
        }

        if (assistRaw.status !== 'fulfilled' && proposalRaw.status !== 'fulfilled') {
          appendMessage({
            role: 'assistant',
            content:
              'The AI scheduling service is currently unavailable. Please try again later or use the manual scheduler.',
          })
        }
      } catch (err) {
        appendMessage({
          role: 'assistant',
          content: `Failed to fetch AI assist data: ${err.message || 'Unknown error'}`,
        })
      }
    },
    [appendMessage]
  )

  const runStatelessCommand = useCallback(
    async (text) => {
      const raw = await aiApi.command(text, true)
      const data = toData(raw) ?? raw
      const res = data?.data ?? data
      return {
        content: res?.message ?? res?.content ?? res?.text ?? 'Here is what I found.',
        intent: res?.intent,
        confidence: res?.confidence,
        ambiguous: res?.ambiguous,
        clarifications: res?.clarifications || [],
        resultCards: res?.result_cards ?? res?.resultCards ?? [],
        ...res,
      }
    },
    []
  )

  const handleSend = useCallback(
    async (overrideText) => {
      const text = (overrideText ?? input).trim()
      if (!text || isSending) return

      appendMessage({ role: 'user', content: text })
      setInput('')
      setIsSending(true)
      setError(null)

      const handleResponse = async (res) => {
        const { all, autoCalls, approvalCalls } = classifySuggestedCalls(res?.suggested_calls || [])
        const assistantMsg = {
          content: res?.message ?? res?.content ?? res?.text ?? 'Here is what I found.',
          intent: res?.intent,
          confidence: res?.confidence,
          ambiguous: res?.ambiguous,
          clarifications: res?.clarifications || [],
          resultCards: res?.result_cards ?? res?.resultCards ?? [],
          suggested_calls: all,
          auto_calls: autoCalls,
          approval_calls: approvalCalls,
          execution_mode: res?.execution_mode,
          bdi_result: res?.bdi_result,
        }
        const assistantMessageId = appendMessage({ role: 'assistant', ...assistantMsg })

        // Auto-execute read-only suggested calls only when backend did not already provide cards.
        const shouldAutoExecuteGets =
          !assistantMsg.ambiguous &&
          assistantMsg.resultCards.length === 0 &&
          autoCalls.length > 0

        if (shouldAutoExecuteGets) {
          for (let i = 0; i < autoCalls.length; i += 1) {
            const call = autoCalls[i]
            const callKey = `${assistantMessageId}:${call.method}:${call.path}:${i}`
            if (executedAutoCallKeysRef.current.has(callKey)) continue
            executedAutoCallKeysRef.current.add(callKey)
            try {
              const raw = await executeSuggestedCall(call)
              const resultCards = buildResultCardsFromCall(call, raw)
              appendMessage({
                role: 'assistant',
                content: call.purpose || 'Read-only result loaded.',
                resultCards,
              })
            } catch (err) {
              appendMessage({
                role: 'assistant',
                content: apiErrorMessage(err, `Failed to auto-run ${call.method} ${call.path}`),
              })
            }
          }
        }

        const hasActionableResponse =
          assistantMsg.resultCards.length > 0 ||
          assistantMsg.suggested_calls.length > 0 ||
          assistantMsg.ambiguous

        if (!hasActionableResponse && (assistantMsg.intent === 'reschedule' || assistantMsg.intent === 'propose_schedule')) {
          const jobId = extractJobId(res)
          if (jobId) {
            await handleSchedulingAssist(jobId)
          } else {
            appendMessage({
              role: 'assistant',
              content:
                'I could not find a specific job ID in that request. Please mention the job ID, for example: "reschedule job P-2404".',
            })
          }
        }
      }

      if (chatsAvailable === false) {
        try {
          const res = await runStatelessCommand(text)
          await handleResponse(res)
        } catch (err) {
          logger.error('Command failed', err)
          appendMessage({
            role: 'assistant',
            content: `Could not get response: ${err?.message || 'Unknown error'}`,
          })
          setError(err?.message || 'Could not get response')
        } finally {
          setIsSending(false)
        }
        return
      }

      let chatId = activeChatId
      if (!chatId) {
        try {
          const raw = await aiApi.chats.create({})
          const data = toData(raw) ?? raw
          const chat = data?.data ?? data
          chatId = chat?.id ?? chat?.chat_id ?? chat?.conversation_id
          if (chatId) {
            setConversations((prev) => [normalizeConversation({ ...chat, id: chatId }), ...prev])
            setActiveChatId(chatId)
          }
        } catch (err) {
          if (is404(err)) {
            setChatsAvailable(false)
            try {
              const res = await runStatelessCommand(text)
              await handleResponse(res)
            } catch (cmdErr) {
              appendMessage({
                role: 'assistant',
                content: `Could not get response: ${cmdErr?.message || 'Unknown error'}`,
              })
            }
          } else {
            appendMessage({
              role: 'assistant',
              content: `Could not create conversation: ${err?.message || 'Unknown error'}`,
            })
          }
          setIsSending(false)
          return
        }
      }

      try {
        const raw = await aiApi.chats.sendMessage(chatId, { query: text })
        const data = toData(raw) ?? raw
        const res = data?.data ?? data?.assistant_message ?? data
        await handleResponse(res)
        setConversations((prev) => {
          const updated = prev.map((c) =>
            c.id === chatId ? { ...c, updated_at: new Date().toISOString() } : c
          )
          return updated.sort((a, b) => (b.updated_at || '') > (a.updated_at || '') ? 1 : -1)
        })
      } catch (err) {
        if (is404(err)) {
          setChatsAvailable(false)
          try {
            const res = await runStatelessCommand(text)
            await handleResponse(res)
          } catch (cmdErr) {
            appendMessage({
              role: 'assistant',
              content: `Could not get response: ${cmdErr?.message || 'Unknown error'}`,
            })
            setError(cmdErr?.message || 'Could not get response')
          }
        } else {
          logger.error('Send message failed', err)
          appendMessage({
            role: 'assistant',
            content: `Could not get response: ${err?.message || 'Unknown error'}`,
          })
          setError(err?.message || 'Could not send message')
        }
      } finally {
        setIsSending(false)
      }
    },
    [input, isSending, activeChatId, chatsAvailable, appendMessage, handleSchedulingAssist, runStatelessCommand]
  )

  const handleExecuteSuggestedCall = useCallback(
    async (call, key) => {
      if (!call?.path) return
      setExecutingCallKey(key)
      try {
        await executeSuggestedCall(call)
        appendMessage({
          role: 'assistant',
          content: call.purpose ? `Done: ${call.purpose}` : 'Action completed.',
        })
      } catch (err) {
        logger.error('Execute suggested call failed', err, { call })
        appendMessage({
          role: 'assistant',
          content: apiErrorMessage(err, `Failed: ${call.purpose || call.method + ' ' + call.path}`),
        })
      } finally {
        setExecutingCallKey(null)
      }
    },
    [appendMessage]
  )

  const handleApproveProposal = useCallback(
    async (proposal) => {
      const pid = proposal?.proposal_id || proposal?.id
      if (!pid) return
      appendMessage({
        role: 'assistant',
        content: 'Approving proposal…',
      })
      try {
        const res = await aiApi.scheduling.approveProposal(pid, {})
        appendMessage({
          role: 'assistant',
          content: res?.message || 'Proposal approved.',
        })
      } catch (err) {
        appendMessage({
          role: 'assistant',
          content: apiErrorMessage(err, `Failed to approve proposal: ${err?.message || 'Unknown error'}`),
        })
      }
    },
    [appendMessage]
  )

  const handleApplyProposal = useCallback(
    async (proposal) => {
      const pid = proposal?.proposal_id || proposal?.id
      if (!pid) return
      appendMessage({
        role: 'assistant',
        content: 'Applying proposal…',
      })
      try {
        const res = await aiApi.scheduling.applyProposal(pid, {})
        appendMessage({
          role: 'assistant',
          content: res?.message || 'Proposal applied to the schedule.',
        })
      } catch (err) {
        appendMessage({
          role: 'assistant',
          content: apiErrorMessage(err, `Failed to apply proposal: ${err?.message || 'Unknown error'}`),
        })
      }
    },
    [appendMessage]
  )

  return {
    conversations,
    activeChatId,
    messages,
    activeTitle,
    input,
    setInput,
    isSending,
    loading,
    error,
    chatsAvailable,
    executingCallKey,
    handleSend,
    handleExecuteSuggestedCall,
    handleApproveProposal,
    handleApplyProposal,
    handleSelectChat,
    handleNewConversation,
    fetchConversations,
  }
}
