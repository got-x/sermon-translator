from __future__ import annotations

import asyncio
import json
import queue
from typing import Any

import httpx
import sounddevice as sd
import websockets

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
)

from server_config import (
    REST_BASE_URL,
    LOCALES_ENDPOINT,
    WEBSOCKET_URL,
    SAMPLE_RATE,
    CHANNELS,
    CHUNK_DURATION_MS,
    SERVICE_REQUEST_TIMEOUT,
    WHISPER_CONNECT_TIMEOUT,
)


class AudioStreamApp(App):
    """Single-screen cross-platform audio streaming client."""

    TITLE = "STInput - Audio Stream Client"
    SUB_TITLE = "REST + WebSocket"

    CSS = """
    Screen {
        align: center middle;
    }

    #main {
        width: 90%;
        max-width: 100;
        height: auto;
        border: round $primary;
        padding: 1 2;
    }

    .field-label {
        margin-top: 1;
    }

    Select, Input {
        width: 100%;
    }

    #buttons {
        margin-top: 2;
        height: auto;
        align: center middle;
    }

    #buttons Button {
        margin: 0 1;
    }

    #status {
        margin-top: 2;
        padding: 1;
        border: round $secondary;
        height: auto;
    }

    #hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("ctrl+r", "refresh_data", "Refresh devices/locales"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()

        self.audio_queue: queue.Queue[bytes | None] = queue.Queue(
            maxsize=50
        )

        self.audio_stream: sd.InputStream | None = None
        self.websocket: Any = None
        self.stream_task: asyncio.Task | None = None
        self.session_id: str | None = None
        self.session_name: str | None = None
        self.session_locale: str | None = None
        self.stopping = False
        self.active = False

    def compose(self) -> ComposeResult:
        yield Header()

        with Vertical(id="main"):
            yield Label("Name", classes="field-label")
            yield Input(
                placeholder="Enter your name",
                id="name",
            )

            yield Label("Locale", classes="field-label")
            yield Select(
                [],
                prompt="Select a locale",
                id="locale",
                allow_blank=True,
            )

            yield Label("Audio input", classes="field-label")
            yield Select(
                [],
                prompt="Select an audio input",
                id="device",
                allow_blank=True,
            )

            with Horizontal(id="buttons"):
                yield Button(
                    "Start stream",
                    id="start",
                    variant="success",
                )
                yield Button(
                    "Stop stream",
                    id="stop",
                    variant="error",
                    disabled=True,
                )
                yield Button("Clear inputs", id="clear")

            yield Static("Session: Not created", id="session")
            yield Static(
                "Status: Initializing...",
                id="status",
            )

            yield Static(
                "Audio is sent only after you start a stream.",
                id="hint",
            )

        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_data()

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(
            f"Status: {message}"
        )

    def set_session_reference(self) -> None:
        session_display = self.query_one("#session", Static)
        if self.session_id:
            session_display.update(f"Session: {self.session_name} ({self.session_locale})")
            session_display.tooltip = f"Session ID: {self.session_id}"
        else:
            session_display.update("Session: Not created")
            session_display.tooltip = None

    async def action_refresh_data(self) -> None:
        if not self.active:
            await self.refresh_data()

    async def refresh_data(self) -> None:
        """Refresh the available input devices and locales."""
        self.set_status("Loading devices and locales...")

        device_select = self.query_one("#device", Select)
        locale_select = self.query_one("#locale", Select)

        devices = []
        try:
            devices = await asyncio.to_thread(
                self.get_input_devices
            )

            device_select.set_options(
                [
                    (f"{name} (device {index})", str(index))
                    for index, name in devices
                ]
            )
            device_select.clear()

        except Exception as exc:
            device_select.set_options([])
            self.set_status(
                f"Could not enumerate audio devices: {exc}"
            )

        try:
            async with httpx.AsyncClient(
                base_url=REST_BASE_URL,
                timeout=SERVICE_REQUEST_TIMEOUT,
            ) as client:
                response = await client.get(LOCALES_ENDPOINT)
                response.raise_for_status()
                data = response.json()

            locales = data.get("locales", [])

            options = []
            for item in locales:
                if isinstance(item, str):
                    options.append((item, item))
                elif isinstance(item, dict):
                    code = item.get("code")
                    name = item.get("name", code)
                    if code:
                        options.append((f"{name} ({code})", code))

            locale_select.set_options(options)
            locale_select.clear()

            self.set_status(
                f"Ready. {len(devices)} input device(s), "
                f"{len(options)} locale(s) available."
            )

        except Exception as exc:
            locale_select.set_options([])
            self.set_status(
                f"Locale request failed: {exc}"
            )

    @staticmethod
    def get_input_devices() -> list[tuple[int, str]]:
        """Return (device index, device name) for audio inputs."""
        devices = sd.query_devices()
        result = []

        for index, device in enumerate(devices):
            if device["max_input_channels"] > 0:
                result.append((index, device["name"]))

        return result

    def validate_inputs(self) -> tuple[str, str, int]:
        """Validate all fields before opening the WebSocket."""
        name = self.query_one("#name", Input).value.strip()
        locale = self.query_one("#locale", Select).value
        device = self.query_one("#device", Select).value

        if not name:
            raise ValueError("Please enter a name.")

        if not isinstance(locale, str) or not locale:
            raise ValueError("Please select a locale.")

        if not isinstance(device, str) or not device:
            raise ValueError("Please select an audio input.")

        try:
            device_index = int(device)
            info = sd.query_devices(device_index)

            if info["max_input_channels"] < CHANNELS:
                raise ValueError(
                    "The selected device has too few input channels."
                )

        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                f"The selected audio device is unavailable: {exc}"
            ) from exc

        return name, locale, device_index

    @on(Button.Pressed, "#start")
    async def start_stream(self) -> None:
        if self.active:
            return

        try:
            name, locale, device_index = self.validate_inputs()
        except ValueError as exc:
            self.set_status(f"Validation error: {exc}")
            return

        # Clear any leftovers from a previous session.
        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        self.stopping = False
        self.active = True
        self.set_controls(active=True)
        self.set_status("Connecting to server...")

        self.stream_task = asyncio.create_task(
            self.stream_audio(name, locale, device_index)
        )

    async def stream_audio(
        self,
        name: str,
        locale: str,
        device_index: int,
    ) -> None:
        """Connect and send PCM audio frames until stopped."""
        frame_count = max(
            1,
            int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000),
        )

        def audio_callback(
            indata,
            frames,
            time_info,
            status,
        ) -> None:
            if status:
                # Callback runs on the audio thread.
                # Avoid updating Textual widgets here.
                pass

            chunk = indata.copy().tobytes()

            try:
                self.audio_queue.put_nowait(chunk)
            except queue.Full:
                # Keep latency bounded if the network is slower
                # than the audio capture rate.
                try:
                    self.audio_queue.get_nowait()
                    self.audio_queue.put_nowait(chunk)
                except (queue.Empty, queue.Full):
                    pass

        stream_status = "Stream stopped. Session is ready to resume."
        try:
            session_id = await self.get_or_create_session(name, locale)

            async with websockets.connect(
                WEBSOCKET_URL.format(session_id=session_id),
                open_timeout=WHISPER_CONNECT_TIMEOUT,
                close_timeout=3,
                max_size=2**20,
            ) as websocket:
                self.websocket = websocket

                # The session server forwards this first message to Whisper.
                await websocket.send(
                    json.dumps(
                        {
                            "config": {
                                "sample_rate": SAMPLE_RATE,
                                "language": locale,
                                "task": "transcribe",
                            },
                        }
                    )
                )

                # Capture signed 16-bit PCM audio.
                self.audio_stream = sd.InputStream(
                    device=device_index,
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=frame_count,
                    callback=audio_callback,
                )
                self.audio_stream.start()

                self.set_status(
                    f"Streaming as {name} ({locale})..."
                )

                while not self.stopping:
                    chunk = await asyncio.to_thread(
                        self.audio_queue.get
                    )

                    if chunk is None:
                        break

                    await websocket.send(chunk)

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            stream_status = f"Stream error: {exc}"

        finally:
            if self.audio_stream is not None:
                try:
                    if self.audio_stream.active:
                        self.audio_stream.stop()
                    self.audio_stream.close()
                except Exception:
                    pass

                self.audio_stream = None

            self.websocket = None
            self.active = False
            self.stopping = False
            self.set_controls(active=False)

            if self.is_running:
                self.set_status(stream_status)

    async def get_or_create_session(self, name: str, locale: str) -> str:
        """Reuse this client's session unless its name or spoken language changed."""
        if (
            self.session_id
            and self.session_name == name
            and self.session_locale == locale
        ):
            return self.session_id

        async with httpx.AsyncClient(
            base_url=REST_BASE_URL,
            timeout=SERVICE_REQUEST_TIMEOUT,
        ) as client:
            response = await client.post(
                "/session",
                json={"name": name, "language": locale},
            )
            response.raise_for_status()
            session_id = response.json().get("session_id")

        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError("Session server did not return a session ID.")

        self.session_id = session_id
        self.session_name = name
        self.session_locale = locale
        self.set_session_reference()
        return session_id

    @on(Button.Pressed, "#stop")
    async def stop_stream(self) -> None:
        if not self.active or self.stopping:
            return

        self.stopping = True
        self.set_status("Stopping stream...")

        # Wake the sender if it is waiting for the next audio frame.
        try:
            self.audio_queue.put_nowait(None)
        except queue.Full:
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.put_nowait(None)
            except queue.Empty:
                pass

        # The stream coroutine performs cleanup.
        if self.stream_task is not None:
            try:
                await self.stream_task
            except asyncio.CancelledError:
                pass
            finally:
                self.stream_task = None

    @on(Button.Pressed, "#clear")
    def clear_inputs(self) -> None:
        if self.active:
            return

        self.query_one("#name", Input).value = ""
        self.query_one("#locale", Select).clear()
        self.query_one("#device", Select).clear()
        self.session_id = None
        self.session_name = None
        self.session_locale = None
        self.set_session_reference()
        self.set_status("Inputs cleared. Ready to start.")

    def set_controls(self, active: bool) -> None:
        """Keep one interface, updating controls in place."""
        self.query_one("#start", Button).disabled = active
        self.query_one("#stop", Button).disabled = not active
        self.query_one("#clear", Button).disabled = active

        self.query_one("#name", Input).disabled = active
        self.query_one("#locale", Select).disabled = active
        self.query_one("#device", Select).disabled = active


if __name__ == "__main__":
    AudioStreamApp().run()