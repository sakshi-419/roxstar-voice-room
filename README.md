# Roxstar AI Voice Room Assistant

A real-time LiveKit voice room with two AI personas — **Roxstar AI Dost** (male, Hinglish) and **Roxstar AI Sathi** (female, Hinglish) — that join alongside human participants, understand Hindi / Roman Hinglish / English, and reply naturally in Hinglish.

> **Current status**: Phase 0 — Project scaffolding complete.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project Structure](#project-structure)
3. [Backend Setup (Python / uv)](#backend-setup-python--uv)
4. [Frontend Setup (Node / npm)](#frontend-setup-node--npm)
5. [Redis Setup](#redis-setup)
6. [Environment Variables](#environment-variables)
7. [Verify Phase 0](#verify-phase-0)
8. [Running the Development Environment](#running-the-development-environment)
9. [Architecture](#architecture)

---

## Prerequisites

| Tool | Required version | Install |
|------|-----------------|---------|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.4 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (macOS/Linux) or `irm https://astral.sh/uv/install.ps1 \| iex` (PowerShell) |
| Node.js | ≥ 18 (LTS) | https://nodejs.org |
| npm | ≥ 9 | Bundled with Node |
| Redis | 7.x | See [Redis Setup](#redis-setup) |
| LiveKit Cloud account | — | https://cloud.livekit.io |
| Deepgram account | — | https://console.deepgram.com |
| Google AI (Gemini) key | — | https://aistudio.google.com |
| ElevenLabs account | — | https://elevenlabs.io |

`uv` downloads Python 3.11 automatically on first use — you do **not** need a separate Python installation.

---

## Project Structure

```
roxstar-voice-room/
├── backend/
│   ├── agents/          # AI bot agents (Phase 3+)
│   ├── core/
│   │   ├── redis_client.py   # Async Redis connection factory
│   │   └── room_state.py     # Shared Redis state layer (Phase 2)
│   ├── providers/       # STT / LLM / TTS factories (Phase 2)
│   ├── server/          # FastAPI token server (Phase 1)
│   ├── utils/           # Logging, error handling (Phase 2)
│   ├── config.py        # Pydantic settings — all config from env
│   ├── pyproject.toml   # Python dependencies
│   └── .env.example     # Copy to .env and fill in secrets
├── frontend/
│   ├── src/             # React + TypeScript components (Phase 7)
│   ├── vite.config.ts   # Dev proxy: /token → localhost:8000
│   └── package.json
├── scripts/
│   └── verify_phase0.py # Phase 0 health check script
├── docs/
├── .gitignore           # .env and secrets excluded
└── README.md
```

---

## Backend Setup (Python / uv)

`uv` manages the Python version and virtual environment automatically.

```powershell
# Navigate to the backend directory
cd roxstar-voice-room/backend

# Install all dependencies (downloads Python 3.11 if not present)
uv sync

# The virtual environment is created at backend/.venv
# Activate it (optional — uv run works without activating)
.\.venv\Scripts\Activate.ps1          # PowerShell (Windows)
# source .venv/bin/activate           # bash (macOS/Linux)
```

To add a new dependency:
```powershell
uv add <package-name>
```

---

## Frontend Setup (Node / npm)

```powershell
cd roxstar-voice-room/frontend

# Install all dependencies
npm install

# Start the Vite development server
npm run dev
# Runs on http://localhost:5173
# /token and /dispatch requests are proxied to http://localhost:8000
```

---

## Redis Setup

Redis is required for cross-process coordination between the two AI bot agents.

### Option A — Docker (recommended for local dev)
```powershell
docker run --rm -p 6379:6379 --name roxstar-redis redis:7-alpine
```

### Option B — Windows native (no Docker)
```powershell
winget install Redis.Redis
# Then start the service:
redis-server
```

### Option C — Upstash (hosted, no local install needed)
1. Sign up at https://upstash.com
2. Create a Redis database
3. Copy the `REDIS_URL` (starts with `rediss://`) to your `.env`
4. Set `REDIS_TLS=true`

---

## Environment Variables

```powershell
# Copy the template
Copy-Item backend/.env.example backend/.env

# Then edit backend/.env with your real values
```

Key variables:

| Variable | Description |
|---|---|
| `LIVEKIT_URL` | Your LiveKit Cloud WebSocket URL |
| `LIVEKIT_API_KEY` | LiveKit API key |
| `LIVEKIT_API_SECRET` | LiveKit API secret (**never commit this**) |
| `REDIS_URL` | Redis connection URL (`redis://localhost:6379/0` for local) |
| `REDIS_TLS` | `true` if using Upstash or any TLS Redis endpoint |
| `DEEPGRAM_API_KEY` | Deepgram API key for speech-to-text |
| `GOOGLE_API_KEY` | Google AI key for Gemini LLM |
| `ELEVENLABS_API_KEY` | ElevenLabs API key for TTS |
| `DOST_VOICE_ID` | ElevenLabs voice ID for Dost (male Hindi) |
| `SATHI_VOICE_ID` | ElevenLabs voice ID for Sathi (female Hindi) |

**Security**: `.env` is listed in `.gitignore`. Never commit real API keys. All secrets are read at startup via `pydantic-settings` — none are hard-coded.

---

## Verify Phase 0

Run the verification script to confirm Python, all packages, and Redis are working:

```powershell
cd roxstar-voice-room/backend

# With a local Redis running:
uv run python ../scripts/verify_phase0.py

# With a custom Redis URL:
$env:REDIS_URL = "rediss://your-upstash-url"; uv run python ../scripts/verify_phase0.py
```

Expected output:
```
Python version: 3.11.x ...
PASS: Python version OK.
PASS: redis (asyncio) importable.
PASS: fastapi importable.
PASS: structlog importable.
PASS: pydantic-settings importable.
PASS: livekit-agents importable.
PASS: uvicorn importable.
PASS: Redis PING → True
PASS: Redis SET test:phase0 hello_roxstar  [EX 30]
PASS: Redis GET test:phase0 → 'hello_roxstar'
PASS: Redis DEL test:phase0  (cleanup).

============================================================
ALL PHASE 0 CHECKS PASSED.
============================================================
```

---

## Running the Development Environment

Phase 0 only — confirms the stack starts without errors.

```powershell
# Terminal 1: Redis
docker run --rm -p 6379:6379 redis:7-alpine

# Terminal 2: Phase 0 verification
cd roxstar-voice-room/backend
uv run python ../scripts/verify_phase0.py

# Terminal 3: Frontend dev server (placeholder UI)
cd roxstar-voice-room/frontend
npm run dev
# Open http://localhost:5173
```

Full token server, AI agents, and room UI will be started in later phases.

---

## Architecture

See [`ARCHITECTURE.md`](../ARCHITECTURE.md) for the full system design including:
- Redis distributed coordination
- Exactly-once turn ingestion
- Bot routing strategy
- Speaking lock mechanism
- Failure handling and degraded modes
