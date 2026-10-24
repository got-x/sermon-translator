import os
from pathlib import Path


def _load_project_environment() -> dict[str, str]:
    """Read the root .env file, with process environment values taking priority."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    values = {}

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")

    values.update(os.environ)
    return values


_ENV = _load_project_environment()
SESSION_HOST = _ENV.get("SESSION_HOST", "localhost")
SESSION_PORT = _ENV.get("SESSION_PORT", "8080")
REST_BASE_URL = f"http://{SESSION_HOST}:{SESSION_PORT}"
LOCALES_ENDPOINT = "/api/locales"

# Use wss:// in production when the server supports TLS.
WEBSOCKET_SCHEME = "wss" if REST_BASE_URL.startswith("https://") else "ws"
WEBSOCKET_HOST = REST_BASE_URL.split("://", 1)[-1]
WEBSOCKET_URL = f"{WEBSOCKET_SCHEME}://{WEBSOCKET_HOST}/ws/audio/{{session_id}}"

SAMPLE_RATE = int(_ENV.get("AUDIO_SAMPLE_RATE", "16000"))
CHANNELS = int(_ENV.get("AUDIO_CHANNELS", "1"))
CHUNK_DURATION_MS = int(_ENV.get("AUDIO_CHUNK_DURATION_MS", "100"))
SERVICE_REQUEST_TIMEOUT = float(_ENV.get("SERVICE_REQUEST_TIMEOUT", "10"))
WHISPER_CONNECT_TIMEOUT = float(_ENV.get("WHISPER_CONNECT_TIMEOUT", "10"))