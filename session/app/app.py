import uuid
import json
import asyncio
import os
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import httpx
import websockets

app = FastAPI()

sessions = {}

TRANSLATE_BASE_URL = os.getenv(
    "TRANSLATE_BASE_URL",
    "http://translate:5000",
).rstrip("/")
LIBRE_URL = f"{TRANSLATE_BASE_URL}/translate"
LIBRE_LANGUAGES_URL = f"{TRANSLATE_BASE_URL}/languages"
WHISPER_WS = os.getenv("WHISPER_WS_URL", "ws://whisper:80/ws")
SERVICE_REQUEST_TIMEOUT = float(os.getenv("SERVICE_REQUEST_TIMEOUT", "10"))
WHISPER_CONNECT_TIMEOUT = float(os.getenv("WHISPER_CONNECT_TIMEOUT", "10"))
AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
AUDIO_CHANNELS = int(os.getenv("AUDIO_CHANNELS", "1"))
AUDIO_CHUNK_DURATION_MS = int(os.getenv("AUDIO_CHUNK_DURATION_MS", "100"))

class TranscriptInput(BaseModel):
    text: str
    source: str = "unknown"   # "whisper" | "manual"
    language: Optional[str] = None

class SessionInput(BaseModel):
    name: str
    language: str

class Session:
    def __init__(self, name, source_lang):
        self.id = str(uuid.uuid4())
        self.name = name
        self.source_lang = source_lang
        self.subscribers = []  # (ws, lang)
        self.transcripts = []
        self.audio_streams = 0
        self.audio_started = False


# ----------------------
# SESSION MANAGEMENT
# ----------------------

@app.get("/api/locales")
async def list_locales():
    try:
        async with httpx.AsyncClient(
            timeout=SERVICE_REQUEST_TIMEOUT
        ) as client:
            response = await client.get(LIBRE_LANGUAGES_URL)
            response.raise_for_status()
            languages = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve locales from the translate service.",
        ) from exc

    if not isinstance(languages, list):
        raise HTTPException(
            status_code=502,
            detail="Translate service returned an invalid languages response.",
        )

    locales = []
    for language in languages:
        if not isinstance(language, dict):
            continue

        code = language.get("code")
        name = language.get("name")
        targets = language.get("targets")
        if (
            isinstance(code, str)
            and code
            and isinstance(name, str)
            and name
            and isinstance(targets, list)
            and targets
        ):
            locales.append({"code": code, "name": name})

    return {"locales": locales}


@app.post("/session")
async def create_session(data: SessionInput):
    s = Session(data.name, data.language)
    sessions[s.id] = s
    return {"session_id": s.id}


@app.get("/sessions")
async def list_sessions():
    return [
        {
            "id": s.id,
            "name": s.name,
            "language": s.source_lang,
            "subscribers": len(s.subscribers),
            "audio_active": s.audio_streams > 0,
        }
        for s in sessions.values()
    ]


# ----------------------
# SUBSCRIBER WS
# ----------------------

@app.websocket("/ws/subscribe/{session_id}")
async def subscribe(ws: WebSocket, session_id: str, lang: str = "en"):
    await ws.accept()

    session = sessions[session_id]
    session.subscribers.append((ws, lang))
    try:
        await ws.send_text(json.dumps({
            "type": "stream_state",
            "active": session.audio_streams > 0,
            "started": session.audio_started,
        }))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if (ws, lang) in session.subscribers:
            session.subscribers.remove((ws, lang))

@app.get("/session/{session_id}")
async def session_info(session_id: str):
    s = sessions[session_id]

    langs = {}
    for _, lang in s.subscribers:
        langs[lang] = langs.get(lang, 0) + 1

    return {
        "name": s.name,
        "language": s.source_lang,
        "subscribers": len(s.subscribers),
        "languages": langs,
        "transcripts": s.transcripts[-10:],
        "audio_active": s.audio_streams > 0,
        "audio_started": s.audio_started,
        "audio": {
            "sample_rate": AUDIO_SAMPLE_RATE,
            "channels": AUDIO_CHANNELS,
            "chunk_duration_ms": AUDIO_CHUNK_DURATION_MS,
        },
    }

# ----------------------
# AUDIO STREAM → WHISPER
# ----------------------

@app.websocket("/ws/audio/{session_id}")
async def audio(ws: WebSocket, session_id: str):
    await ws.accept()
    session = sessions[session_id]
    session.audio_streams += 1
    session.audio_started = True
    await broadcast_stream_state(session)
    try:
        async with websockets.connect(
            WHISPER_WS,
            open_timeout=WHISPER_CONNECT_TIMEOUT,
        ) as whisper:

            first = await ws.receive()

            if "text" in first:
                await whisper.send(first["text"])
            else:
                print("Expected config JSON first")
                return

            async def forward_audio():
                while True:
                    msg = await ws.receive()

                    if "bytes" in msg:
                        await whisper.send(msg["bytes"])
                    elif "text" in msg:
                        print("Received text message:", msg["text"])
                    else:
                        print("Unknown message type:", msg)

            async def receive_text():
                while True:
                    msg = await whisper.recv()
                    try:
                        raw = json.loads(msg)
                        data = TranscriptInput(
                            text=raw.get("text", ""),
                            source="whisper",
                            language=session.source_lang
                        )
                        await handle_transcript(session, data)

                    except Exception as e:
                        print("Whisper parse error:", e, msg)

            tasks = {
                asyncio.create_task(forward_audio()),
                asyncio.create_task(receive_text()),
            }
            try:
                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    task.result()
            except WebSocketDisconnect:
                pass
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        session.audio_streams = max(0, session.audio_streams - 1)
        await broadcast_stream_state(session)


# ----------------------
# MANUAL TEXT INPUT (optional)
# ----------------------

@app.post("/session/{session_id}/text")
async def push_text(session_id: str, data: TranscriptInput):
    session = sessions.get(session_id)

    if not session:
        return {"error": "session not found"}
    
    data.source = "manual"

    print("RAW INPUT:", data)

    await handle_transcript(session, data)


# ----------------------
# CORE LOGIC
# ----------------------

async def handle_transcript(session: Session, data: TranscriptInput):

    text = data.text.strip()

    print("Received transcript:", text, "from", data.source)

    if not text:
        return

    translations = {}

    async with httpx.AsyncClient(
        timeout=SERVICE_REQUEST_TIMEOUT
    ) as client:

        # get unique languages
        langs = set(lang for _, lang in session.subscribers)

        for lang in langs:
            print("Translating to", lang)
            translations[lang] = await translate(client, text, lang)

    # store
    sequence = len(session.transcripts) + 1
    session.transcripts.append({
        "sequence": sequence,
        "text": text,
        "source": data.source,
        "translations": translations
    })

    # broadcast
    await broadcast(session, text, translations, sequence)


async def translate(client, text, lang):
    print("Translating ", text, "to", lang)
    r = await client.post(LIBRE_URL, json={
        "q": text,
        "source": "auto",
        "target": lang
    })
    r.raise_for_status()
    return r.json().get("translatedText")


async def broadcast(session, text, translations, sequence):
    print("Broadcasting to", len(session.subscribers), "subscribers")
    for ws, lang in session.subscribers:
        try:
            await ws.send_text(json.dumps({
                "sequence": sequence,
                "original": text,
                "translation": translations.get(lang),
                "lang": lang
            }))
        except:
            pass


async def broadcast_stream_state(session):
    event = json.dumps({
        "type": "stream_state",
        "active": session.audio_streams > 0,
        "started": session.audio_started,
    })
    for ws, _ in session.subscribers:
        try:
            await ws.send_text(event)
        except (WebSocketDisconnect, RuntimeError):
            pass

# ----------------------
# UI endpoints
# ----------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")