/**
 * App.tsx — Phase 0 placeholder
 *
 * The actual VoiceRoom UI will be built in Phase 1 (token connection)
 * through Phase 7 (full chat + bot status). This stub exists so the
 * dev server starts without errors and confirms the React + Vite +
 * TypeScript + LiveKit dependency chain is intact.
 */

import './App.css'

function App() {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #0f0f1a 0%, #1a0f2e 100%)',
        color: '#e2e8f0',
        fontFamily: 'system-ui, sans-serif',
        gap: '1rem',
      }}
    >
      <h1 style={{ fontSize: '2rem', margin: 0 }}>🎙️ Roxstar AI Voice Room</h1>
      <p style={{ color: '#94a3b8', margin: 0 }}>
        Phase 0 — Scaffolding complete. Room UI coming in Phase 1.
      </p>
      <code
        style={{
          background: '#1e293b',
          padding: '0.5rem 1rem',
          borderRadius: '0.5rem',
          fontSize: '0.85rem',
          color: '#38bdf8',
        }}
      >
        @livekit/components-react · livekit-client · Vite 6 · React 19 · TypeScript
      </code>
    </div>
  )
}

export default App
