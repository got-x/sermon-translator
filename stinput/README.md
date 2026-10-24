For this, I recommend building a Python terminal GUI (TUI) rather than a traditional command-line tool. A TUI gives you a single, persistent interface with selectable audio devices, text inputs, locale selection, status messages, and Start/Stop controls — without page loads or screen changes.

A good cross-platform stack is:

- [Textual](https://textual.textualize.io/?utm_source=chatgpt.com) — interactive terminal UI for Windows, macOS, and Linux.
- [sounddevice](https://python-sounddevice.readthedocs.io/?utm_source=chatgpt.com) — enumerate audio inputs and capture microphone audio.
- [httpx](https://www.python-httpx.org/?utm_source=chatgpt.com) — retrieve available locales from a REST API.
- [websockets](https://websockets.readthedocs.io/?utm_source=chatgpt.com) — stream captured audio to the server over a WebSocket connection.
- PyInstaller — package the application into an executable for each target operating system.

The implementation below uses one screen throughout the entire session. It validates the name, locale, and audio device before starting, sends the selected metadata to the server, streams audio in chunks, and allows the stream to be stopped without closing the application.

## 1. Project structure

audio-stream-client/

`app.py`

Main TUI application

`requirements.txt`

Dependencies

`server_config.py`

Server configuration

The example assumes the server exposes a REST endpoint returning locales and a WebSocket endpoint accepting a JSON start message followed by binary PCM audio frames. Those endpoint paths and message formats are configurable because your actual server protocol has not been specified.

## 2. Install the dependencies

Create `requirements.txt`:

```

textual>=0.80
sounddevice>=0.5
httpx>=0.27
websockets>=13
numpy>=1.26

```

Install the dependencies in a virtual environment:

```
python -m venv .venv
```

Activate it:

```
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

Then install:

```
python -m pip install -r requirements.txt
```

On Linux, you may also need to install the system audio development libraries and PortAudio package. On macOS, grant microphone access if prompted.

## 3. Configure the server

Create `server_config.py`:

```
REST_BASE_URL = "http://localhost:8000"LOCALES_ENDPOINT = "/api/locales"# Use wss:// in production when the server supports TLS.WEBSOCKET_URL = "ws://localhost:8000/ws/audio"SAMPLE_RATE = 16000CHANNELS = 1CHUNK_DURATION_MS = 100
```

This configuration captures mono audio at 16 kHz and sends approximately 100 ms of audio per WebSocket frame.

## 4. Main application

Create `app.py`:

```
from __future__ import annotations            self.set_status(f"Stream error: {exc}")        finally:            if self.audio_stream is not None:                try:                    if self.audio_stream.active:                        self.audio_stream.stop()                    self.audio_stream.close()                except Exception:                    pass                self.audio_stream = None            self.websocket = None            self.active = False            self.stopping = False            self.set_controls(active=False)            if self.is_running:                self.set_status("Stream stopped. Ready.")    @on(Button.Pressed, "#stop")    async def stop_stream(self) -> None:        if not self.active or self.stopping:            return        self.stopping = True        self.set_status("Stopping stream...")        # Wake the sender if it is waiting for the next audio frame.        try:            self.audio_queue.put_nowait(None)        except queue.Full:            try:                self.audio_queue.get_nowait()                self.audio_queue.put_nowait(None)            except queue.Empty:                pass        # The stream coroutine performs cleanup.        if self.stream_task is not None:            try:                await self.stream_task            except asyncio.CancelledError:                pass            finally:                self.stream_task = None    @on(Button.Pressed, "#clear")    def clear_inputs(self) -> None:        if self.active:            return        self.query_one("#name", Input).value = ""        self.query_one("#locale", Select).value = Select.BLANK        self.query_one("#device", Select).value = Select.BLANK        self.set_status("Inputs cleared. Ready to start.")    def set_controls(self, active: bool) -> None:        """Keep one interface, updating controls in place."""        self.query_one("#start", Button).disabled = active        self.query_one("#stop", Button).disabled = not active        self.query_one("#clear", Button).disabled = active        self.query_one("#name", Input).disabled = active        self.query_one("#locale", Select).disabled = active        self.query_one("#device", Select).disabled = activeif __name__ == "__main__":    AudioStreamApp().run()
```

## 5. Expected REST response

The application expects the locale endpoint to return JSON in this format:

```
{
  "locales": [
    {
      "code": "en-US",
      "name": "English (United States)"
    },
    {
      "code": "de-DE",
      "name": "German (Germany)"
    },
    {
      "code": "fr-FR",
      "name": "French (France)"
    }
  ]
}
```

The code also accepts a simple array of locale strings, such as `{"locales": ["en-US", "de-DE"]}`.

## 6. How the interface behaves

Idle state

NAME

Enter your name

LOCALE

Select a locale

AUDIO INPUT

Select an audio input

Start stream

Stop stream — disabled

Clear inputs

Streaming state

Status: Streaming as Alex (en-US)...

Start stream — disabled

Stop stream

Clear inputs — disabled

The controls update in place. While a stream is active, the inputs cannot be changed accidentally. When you stop the stream, the application returns to the idle state.

## 7. Build a standalone executable

Install PyInstaller:

```
python -m pip install pyinstaller
```

Build the application:

```
pyinstaller --clean --onefile --name AudioStreamClient app.py
```

The executable will be created under `dist/`.

- Windows: `dist\AudioStreamClient.exe`
- macOS/Linux: `dist/AudioStreamClient`

Important: Build on each target operating system. PyInstaller does not generally cross-compile a Windows executable from Linux or vice versa. Also, the target machine needs compatible audio drivers and system audio libraries.

## 8. Important production considerations

Before connecting this to your actual server, I would address four details:

1. WebSocket protocol: The example sends a JSON `start` message, then binary PCM frames, followed by a JSON `stop` message. Your server must support this exact sequence, or the client must be adapted to its protocol.
2. Audio format: The frames contain signed 16-bit little-endian PCM audio, mono, at 16 kHz. No WAV header is included. If your server expects WAV, Opus, or another encoding, the audio handling needs to change.
3. Server responses: The example sends audio but does not yet display incoming WebSocket messages. If your server sends transcription results, processing status, or errors, you can add a concurrent receive loop and display them in the same interface.
4. Connection security: Use HTTPS for REST and WSS for WebSockets in production. If the server requires authentication, add the appropriate token or session mechanism.

One additional refinement worth making is to preserve the actual error message in the status field rather than always replacing it with “Stream stopped” during cleanup.

One question that will help finalize the implementation: What does your server expect over the WebSocket connection — raw PCM audio chunks, WAV data, or another audio format? If you have an example REST response and WebSocket protocol, I can adapt the client to match it exactly.