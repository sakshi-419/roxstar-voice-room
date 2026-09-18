import { useState, useEffect } from 'react'
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useParticipants,
  useLocalParticipant,
  useRoomContext,
} from '@livekit/components-react'
import type { Participant } from 'livekit-client'

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
      const res = await fetch('/health')
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
      const res = await fetch('/token', {
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
        fetch('/dispatch', {
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
  const participants = useParticipants()
  const { isMicrophoneEnabled, localParticipant } = useLocalParticipant()
  const room = useRoomContext()
  const [dispatchStatus, setDispatchStatus] = useState<string | null>(null)
  const [isDispatching, setIsDispatching] = useState(false)

  const toggleMic = async () => {
    try {
      await localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled)
    } catch (err) {
      console.error('Failed to toggle microphone:', err)
    }
  }

  const handleManualDispatch = async () => {
    setIsDispatching(true)
    setDispatchStatus('Dispatching agents...')
    try {
      const res = await fetch('/dispatch', {
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
            disabled={isDispatching}
            id="dispatch-btn"
          >
            🤖 {dispatchStatus || 'Summon AI Agents'}
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

        <div className="info-box" style={{ marginTop: 'auto' }}>
          💡 <strong>Multi-Human Audio Active:</strong> When someone speaks, their card will highlight in emerald green. Speak into your microphone to verify bidirectional audio.
        </div>
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

  if (isLocal) {
    badgeLabel = 'You'
    badgeClass = 'participant-badge badge-you'
  } else if (isDost) {
    avatarClass = 'avatar bot-dost'
    initial = 'D'
    badgeLabel = 'AI Dost'
    badgeClass = 'participant-badge badge-ai'
  } else if (isSathi) {
    avatarClass = 'avatar bot-sathi'
    initial = 'S'
    badgeLabel = 'AI Sathi'
    badgeClass = 'participant-badge badge-ai'
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

        <div className="participant-identity" title={identity}>
          ID: {identity}
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
