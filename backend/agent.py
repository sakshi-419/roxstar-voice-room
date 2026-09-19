"""
backend/agent.py
----------------
LiveKit Agents entrypoint for Roxstar AI Voice Room.
Delegates to server.main for LiveKit Cloud deployment and local dev.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from server.main import cli, server

if __name__ == "__main__":
    cli.run_app(server)
