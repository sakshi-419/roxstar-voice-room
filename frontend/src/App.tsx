import { useState, useEffect, useRef } from 'react'
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useParticipants,
  useLocalParticipant,
  useRoomContext,
  useChat,
} from '@livekit/components-react'
import type { Participant } from 'livekit-client'

const TOKEN_SERVER_URL = (import.meta.env.VITE_TOKEN_SERVER_URL || '').replace(/\/$/, '')

interface HealthState {
  backend: boolean
  redis: boolean
  checking: boolean
}

export default function App() {
  const [roomName, setRoomName] = useState('roxstar-lounge')
  const [participantName, setParticipantName] = useState('')
  const [autoDispatch, setAutoDispatch] = useState(true)

  const [token, setToken] = useState<string | null>(null)
  const [serverUrl, setServerUrl] = useState<string | null>(null)
  const [isConnecting, setIsConnecting] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const [health, setHealth] = useState<HealthState>({
    backend: false,
    redis: false,
    checking: true,
  })

  // Poll backend health check
  const checkHealth = async () => {
    try {
      const res = await fetch(`${TOKEN_SERVER_URL}/health`)
      if (res.ok) {
        const data = await res.json()
        setHealth({
          backend: true,
          redis: !!data.redis,
          checking: false,
        })
      } else {
        setHealth({ backend: false, redis: false, checking: false })
      }
    } catch {
      setHealth({ backend: false, redis: false, checking: false })
    }
  }

  useEffect(() => {
    checkHealth()
    const timer = setInterval(checkHealth, 10000)
    return () => clearInterval(timer)
  }, [])

  const handleJoin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!roomName.trim() || !participantName.trim()) {
      setErrorMsg('Please enter both Room Name and Your Name.')
      return
    }

    setErrorMsg(null)
    setIsConnecting(true)

    try {
      // 1. Fetch token from backend
      const res = await fetch(`${TOKEN_SERVER_URL}/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          room_name: roomName.trim(),
          participant_name: participantName.trim(),
        }),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `Token request failed (${res.status})`)
      }

      const data = await res.json()
      if (!data.token || !data.livekit_url) {
        throw new Error('Invalid token response from server')
      }

      // 2. If autoDispatch requested, summon Dost & Sathi
      if (autoDispatch) {
        fetch(`${TOKEN_SERVER_URL}/dispatch`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ room_name: roomName.trim() }),
        }).catch((err) => {
          console.warn('Auto-dispatch notice:', err)
        })
      }

      setServerUrl(data.livekit_url)
      setToken(data.token)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setErrorMsg(msg)
    } finally {
      setIsConnecting(false)
    }
  }

  const handleLeave = () => {
    setToken(null)
    setServerUrl(null)
  }

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="brand">
          <div className="brand-logo">🎙️</div>
          <div>
            <h1 className="brand-title">Roxstar AI Voice Room</h1>
            <div className="brand-subtitle">Phase 1: Real-Time LiveKit Connectivity</div>
          </div>
        </div>

        <div
          className={`header-status-pill ${
            health.backend && health.redis ? '' : 'offline'
          }`}
          title={`Backend: ${health.backend ? 'Online' : 'Offline'} | Redis: ${
            health.redis ? 'Connected' : 'Disconnected'
          }`}
        >
          <span className="pulse-dot" />
          {health.checking
            ? 'Checking System...'
            : health.backend && health.redis
            ? 'System Ready (Redis OK)'
            : health.backend
            ? 'Backend OK (Redis Issue)'
            : 'Backend Offline'}
        </div>
      </header>

      {/* Main Content */}
      {!token || !serverUrl ? (
        <div className="join-view">
          <div className="hero-card">
            <div className="hero-header">
              <h2 className="hero-title">Join Voice Room</h2>
              <p className="hero-description">
                Connect your microphone and join with human peers and AI companions.
              </p>
            </div>

            <form onSubmit={handleJoin}>
              <div className="form-group">
                <label className="form-label" htmlFor="room-input">
                  Room Name
                </label>
                <input
                  id="room-input"
                  className="form-input"
                  type="text"
                  placeholder="e.g. roxstar-lounge"
                  value={roomName}
                  onChange={(e) => setRoomName(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="name-input">
                  Your Display Name
                </label>
                <input
                  id="name-input"
                  className="form-input"
                  type="text"
                  placeholder="e.g. Aarav, Rohan, Priya"
                  value={participantName}
                  onChange={(e) => setParticipantName(e.target.value)}
                  required
                />
              </div>

              <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  id="autodispatch-toggle"
                  type="checkbox"
                  checked={autoDispatch}
                  onChange={(e) => setAutoDispatch(e.target.checked)}
                  style={{ accentColor: 'var(--accent-indigo)', width: '16px', height: '16px' }}
                />
                <label
                  htmlFor="autodispatch-toggle"
                  style={{ fontSize: '13px', color: 'var(--text-secondary)', cursor: 'pointer' }}
                >
                  Auto-summon AI companions (Dost &amp; Sathi)
                </label>
              </div>

              <button
                type="submit"
                className="btn-primary"
                disabled={isConnecting}
                id="join-room-btn"
              >
                {isConnecting ? 'Connecting...' : 'Join Room ➔'}
              </button>

              {errorMsg && (
                <div className="error-banner">
                  ⚠️ {errorMsg}
                </div>
              )}
            </form>

            <div className="info-box" style={{ marginTop: '24px' }}>
              <strong>Multi-User Testing:</strong> Open another browser window or incognito tab with the same <strong>Room Name</strong> and a different <strong>Display Name</strong> to test two human participants talking in real-time.
            </div>
          </div>
        </div>
      ) : (
        <LiveKitRoom
          serverUrl={serverUrl}
          token={token}
          connect={true}
          audio={true}
          video={false}
          onDisconnected={handleLeave}
        >
          <RoomView
            roomName={roomName}
            participantName={participantName}
            onLeave={handleLeave}
          />
          <RoomAudioRenderer />
        </LiveKitRoom>
      )}
    </div>
  )
}

function RoomView({
  roomName,
  participantName,
  onLeave,
}: {
  roomName: string
  participantName: string
  onLeave: () => void
}) {
  const rawParticipants = useParticipants()
  const { isMicrophoneEnabled, localParticipant } = useLocalParticipant()
  const room = useRoomContext()
  const { chatMessages, send, isSending } = useChat()
  const [dispatchStatus, setDispatchStatus] = useState<string | null>(null)
  const [isDispatching, setIsDispatching] = useState(false)
  const [showChat, setShowChat] = useState(true)
  const [chatInput, setChatInput] = useState('')
  const chatBottomRef = useRef<HTMLDivElement>(null)

  // Strict participant deduplication: Exactly 1 User card, at most 1 Dost card, at most 1 Sathi card
  const participants = (() => {
    const list: Participant[] = []

    // 1. Local user participant always first
    const local = rawParticipants.find((p) => p.isLocal) || (localParticipant as Participant)
    if (local) list.push(local)

    // 2. Exactly one Dost participant (pick active/speaking or most recent)
    const dostCandidates = rawParticipants.filter(
      (p) => !p.isLocal && (p.identity.toLowerCase().includes('dost') || (p.name || '').toLowerCase().includes('dost'))
    )
    if (dostCandidates.length > 0) {
      const activeDost = dostCandidates.find((p) => p.isSpeaking) || dostCandidates[dostCandidates.length - 1]
      list.push(activeDost)
    }

    // 3. Exactly one Sathi participant (pick active/speaking or most recent)
    const sathiCandidates = rawParticipants.filter(
      (p) => !p.isLocal && (p.identity.toLowerCase().includes('sathi') || (p.name || '').toLowerCase().includes('sathi'))
    )
    if (sathiCandidates.length > 0) {
      const activeSathi = sathiCandidates.find((p) => p.isSpeaking) || sathiCandidates[sathiCandidates.length - 1]
      list.push(activeSathi)
    }

    // 4. Other human peers deduplicated by identity
    const seen = new Set(list.map((p) => p.identity))
    for (const p of rawParticipants) {
      if (!p.isLocal && !seen.has(p.identity)) {
        const idL = (p.identity || '').toLowerCase()
        const nmL = (p.name || '').toLowerCase()
        if (!idL.includes('dost') && !idL.includes('sathi') && !nmL.includes('dost') && !nmL.includes('sathi')) {
          seen.add(p.identity)
          list.push(p)
        }
      }
    }

    return list
  })()

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  const handleSendChat = async (e?: React.SyntheticEvent, customMsg?: string) => {
    if (e) e.preventDefault()
    const textToSend = (customMsg || chatInput).trim()
    if (!textToSend || isSending) return
    if (!customMsg) setChatInput('')
    try {
      await send(textToSend)
    } catch (err) {
      console.error('Failed to send text chat:', err)
    }
  }

  const hasDost = participants.some((p) => {
    const id = (p.identity || "").toLowerCase()
    const nm = (p.name || "").toLowerCase()
    return id.includes("dost") || nm.includes("dost")
  })
  const hasSathi = participants.some((p) => {
    const id = (p.identity || "").toLowerCase()
    const nm = (p.name || "").toLowerCase()
    return id.includes("sathi") || nm.includes("sathi")
  })
  const allAgentsActive = hasDost && hasSathi

  const toggleMic = async () => {
    try {
      await localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled)
    } catch (err) {
      console.error('Failed to toggle microphone:', err)
    }
  }

  const handleManualDispatch = async () => {
    if (isDispatching || allAgentsActive) return;
    setIsDispatching(true)
    setDispatchStatus('Dispatching agents...')
    try {
      const res = await fetch(`${TOKEN_SERVER_URL}/dispatch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_name: roomName }),
      })
      if (res.ok) {
        const data = await res.json()
        const count = (data.dispatched?.length || 0) + (data.already_running?.length || 0)
        setDispatchStatus(`Active agents (${count})`)
      } else {
        setDispatchStatus('Dispatch failed')
      }
    } catch {
      setDispatchStatus('Network error')
    } finally {
      setIsDispatching(false)
      setTimeout(() => setDispatchStatus(null), 4000)
    }
  }

  const handleDisconnect = async () => {
    await room.disconnect()
    onLeave()
  }

  return (
    <div className="room-layout">
      {/* Room Bar */}
      <div className="room-bar">
        <div className="room-info">
          <div className="room-tag">
            <span className="pulse-dot" style={{ color: 'var(--accent-emerald)' }} />
            Room: {roomName}
          </div>
          <span className="user-tag">You: {participantName}</span>
        </div>

        <div className="room-actions">
          <button
            type="button"
            className={`btn-action ${isMicrophoneEnabled ? 'mic-active' : 'mic-muted'}`}
            onClick={toggleMic}
            id="mic-toggle-btn"
          >
            {isMicrophoneEnabled ? '🎙️ Mic ON' : '🔇 Mic Muted'}
          </button>

          <button
            type="button"
            className="btn-action dispatch"
            onClick={handleManualDispatch}
            disabled={isDispatching || allAgentsActive}
            id="dispatch-btn"
          >
            🤖 {allAgentsActive ? 'AI Agents Active' : (dispatchStatus || 'Summon AI Agents')}
          </button>
          <button
            type="button"
            className={`btn-action ${showChat ? 'mic-active' : ''}`}
            onClick={() => setShowChat(!showChat)}
            id="chat-toggle-btn"
          >
            💬 Chat {chatMessages.length > 0 ? `(${chatMessages.length})` : ''}
          </button>

          <button
            type="button"
            className="btn-action leave"
            onClick={handleDisconnect}
            id="leave-room-btn"
          >
            Leave ✖
          </button>
        </div>
      </div>

      {/* Participants Grid */}
      <div className="participants-section">
        <div className="section-header">
          <h2 className="section-title">
            Connected Participants ({participants.length})
          </h2>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Live Audio Stream Active
          </span>
        </div>

        <div className="participants-grid">
          {participants.map((p) => (
            <ParticipantTile
              key={p.sid || p.identity}
              participant={p}
              isLocal={p.isLocal}
            />
          ))}
        </div>

        <div className="info-box">
          🎙️ <strong>Two AI Co-Hosts Active:</strong> Say <strong>"Dost, ..."</strong> to talk to <strong>AI Dost (Male Voice)</strong> or <strong>"Sathi, ..."</strong> to talk to <strong>AI Sathi (Female Voice)</strong>. Follow-ups (e.g. <em>"thoda simple batao"</em>) will automatically continue with the current speaker!
        </div>

        {/* Live Room Text Chat (Requirement 2.3 & Scenarios 1-5) */}
        {showChat && (
          <div className="chat-container">
            <div className="chat-header">
              <span className="chat-title">💬 Live Room Text Chat</span>
              <span className="chat-subtitle">Ask questions via text or voice — AI Dost &amp; Sathi will respond!</span>
            </div>

            <div className="quick-prompts">
              <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginRight: '6px' }}>Try asking:</span>
              <button type="button" className="prompt-chip" onClick={() => handleSendChat(undefined, 'Dost, AI kya hota hai?')}>
                "Dost, AI kya hota hai?"
              </button>
              <button type="button" className="prompt-chip" onClick={() => handleSendChat(undefined, 'Sathi, rain ka concept samjhao.')}>
                "Sathi, rain ka concept samjhao."
              </button>
              <button type="button" className="prompt-chip" onClick={() => handleSendChat(undefined, 'Thoda aur simple batao.')}>
                "Thoda aur simple batao."
              </button>
              <button type="button" className="prompt-chip" onClick={() => handleSendChat(undefined, 'Can you explain cloud computing?')}>
                "Can you explain cloud computing?"
              </button>
            </div>

            <div className="chat-messages">
              {chatMessages.length === 0 ? (
                <div className="chat-empty">
                  No messages yet. Speak into your mic or type a question below!
                </div>
              ) : (
                chatMessages.map((msg) => {
                  const sender = msg.from?.name || msg.from?.identity || 'User'
                  const isDost = sender.toLowerCase().includes('dost')
                  const isSathi = sender.toLowerCase().includes('sathi')
                  const isSelf = msg.from?.identity === localParticipant.identity

                  let bubbleClass = 'chat-bubble user-bubble'
                  let tagLabel = sender
                  if (isSelf) {
                    bubbleClass = 'chat-bubble self-bubble'
                    tagLabel = 'You'
                  } else if (isDost) {
                    bubbleClass = 'chat-bubble dost-bubble'
                    tagLabel = 'AI Dost (Male)'
                  } else if (isSathi) {
                    bubbleClass = 'chat-bubble sathi-bubble'
                    tagLabel = 'AI Sathi (Female)'
                  }

                  return (
                    <div key={msg.id || msg.timestamp} className={`chat-message-row ${isSelf ? 'row-self' : 'row-other'}`}>
                      <div className="chat-meta">
                        <span className="chat-sender">{tagLabel}</span>
                        <span className="chat-time">
                          {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                      <div className={bubbleClass}>{msg.message}</div>
                    </div>
                  )
                })
              )}
              <div ref={chatBottomRef} />
            </div>

            <form className="chat-input-form" onSubmit={handleSendChat}>
              <input
                type="text"
                className="chat-input"
                placeholder="Type your message in Hindi, Hinglish, or English..."
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                disabled={isSending}
                id="room-chat-input"
              />
              <button type="submit" className="chat-send-btn" disabled={!chatInput.trim() || isSending} id="room-chat-send-btn">
                {isSending ? '...' : 'Send ➔'}
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  )
}

function ParticipantTile({
  participant,
  isLocal,
}: {
  participant: Participant
  isLocal: boolean
}) {
  const isSpeaking = participant.isSpeaking
  const isMicEnabled = participant.isMicrophoneEnabled

  const identity = participant.identity
  const name = participant.name || identity

  // Detect participant type
  const isDost = identity.includes('dost') || name.toLowerCase().includes('dost')
  const isSathi = identity.includes('sathi') || name.toLowerCase().includes('sathi')
  const isAgent = isDost || isSathi || identity.startsWith('agent-')

  let avatarClass = 'avatar'
  let initial = name.charAt(0).toUpperCase() || 'U'
  let badgeLabel = 'Human'
  let badgeClass = 'participant-badge badge-human'

  let subtitle = isLocal ? 'You (Microphone)' : ('ID: ' + identity) 
  if (isLocal) {
    badgeLabel = 'You'
    badgeClass = 'participant-badge badge-you'
  } else if (isDost) {
    avatarClass = 'avatar bot-dost'
    initial = 'D'
    badgeLabel = 'AI Dost (Male Voice)'
    badgeClass = 'participant-badge badge-ai'
    subtitle = 'Male Co-Host · Say "Dost..." to speak'
  } else if (isSathi) {
    avatarClass = 'avatar bot-sathi'
    initial = 'S'
    badgeLabel = 'AI Sathi (Female Voice)'
    badgeClass = 'participant-badge badge-ai'
    subtitle = 'Female Co-Host · Say "Sathi..." to speak'
  } else if (isAgent) {
    avatarClass = 'avatar bot-dost'
    initial = 'A'
    badgeLabel = 'AI Agent'
    badgeClass = 'participant-badge badge-ai'
  }

  return (
    <div
      className={`participant-card ${isSpeaking ? 'is-speaking' : ''} ${
        isLocal ? 'is-local' : ''
      }`}
    >
      <div className="avatar-wrapper">
        {isSpeaking && <div className="speaking-ring" />}
        <div className={avatarClass}>{initial}</div>
      </div>

      <div className="participant-meta">
        <div className="participant-name-row">
          <span className="participant-name" title={name}>
            {name}
          </span>
          <span className={badgeClass}>{badgeLabel}</span>
        </div>

        <div className="participant-identity" title={identity} style={{ color: (isDost || isSathi) ? 'var(--accent-cyan, #38bdf8)' : undefined, fontWeight: (isDost || isSathi) ? 500 : undefined }}>
          {subtitle}
        </div>

        <div className="participant-audio-indicator">
          {isMicEnabled ? (
            <span className="audio-active">🎙️ Mic Active</span>
          ) : (
            <span className="audio-muted">🔇 Muted</span>
          )}
          {isSpeaking && (
            <span style={{ color: 'var(--accent-emerald)', marginLeft: '6px', fontWeight: 600 }}>
              • Speaking
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
