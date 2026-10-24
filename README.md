# Sermon transcription & translation

Sermon Translator provides live speech transcription and translation for
in-person or online audiences. A speaker can stream a microphone from the
browser or the optional STInput desktop client; listeners follow translations
in a browser.

## Feature overview

- Create named live sessions and choose the spoken/source language.
- Stream microphone audio through the session server to Whisper for live
  transcription, or submit text directly from the speaker dashboard.
- Translate each transcript into the languages selected by connected
  listeners using LibreTranslate.
- Browse available sessions, see the listener count and whether an audio
  stream is active, and join with a chosen translation language. The session
  list refreshes automatically every five seconds.
- Follow new translations live. Each translation is numbered, can be ordered
  newest-first or oldest-first, and can show or hide its original text.
- Switch to a simplified print view without reloading the listener page, then
  use the browser's print command.
- Use the session web UI in English, German, or Ukrainian. The first visit
  follows the browser's preferred supported language (English otherwise);
  the language picker choice is saved in the browser.
- Use STInput as an optional terminal-based microphone client instead of the
  browser speaker page.

Whisper and LibreTranslate run as separate Docker Compose services. Audio is
transcribed by Whisper and translated by LibreTranslate; see
[How the services work](#how-the-services-work) and
[Privacy and deployment security](#privacy-and-deployment-security) for data
handling and deployment considerations.

## Prerequisites

### Required to run the services

- **Docker Engine or Docker Desktop** with the Docker Compose v2 plugin
  (`docker compose`). See the [Docker installation guide](https://docs.docker.com/engine/install/)
  or [Docker Desktop downloads](https://www.docker.com/products/docker-desktop/).
- **Internet access for the initial setup.** Docker must be able to pull the
  service images, and the services must be able to download their speech and
  translation models. After downloads are cached, normal use may work offline.
- **Sufficient disk space and memory** for the selected container images and
  models. Requirements vary by Whisper model, device, and translation
  languages; larger models need substantially more resources. See
  [External images, models, and data](#external-images-models-and-data).
- **A modern browser** for the speaker and listener web pages. The speaker
  page needs microphone permission. Browsers require HTTPS for microphone
  access except on `localhost`; use HTTPS when accessing it from another
  device.

### Optional: STInput desktop client

- **Python 3.10 or newer** and `pip` to run STInput from source. Installation
  instructions are in [Run the STInput desktop client](#run-the-stinput-desktop-client).
- **A microphone or other audio input device** supported by
  [sounddevice](https://python-sounddevice.readthedocs.io/). On Linux, a
  PortAudio package may also need to be installed using the operating
  system's package manager.
- **PyInstaller** only if you want to build a standalone executable; it is
  installed separately in [Generate the STInput client app](#generate-the-stinput-client-app).
  Build the executable on the operating system where it will run.

## Preparation

Copy `.env.example` to `.env` in the project root. Docker Compose reads this file
automatically when it starts the stack. In PowerShell:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

### Environment variables

The root `.env` configures host ports, service images, Whisper, audio capture,
service addresses, and request timeouts:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SESSION_HOST` | `localhost` | Hostname stinput uses to reach the session service |
| `SESSION_PORT` | `8080` | Host port for the session web app and API |
| `TRANSLATE_PORT` | `5000` | Host port for the LibreTranslate API |
| `WHISPER_PORT` | `9080` | Host port for the Whisper WebSocket service |
| `SESSION_IMAGE` | `python:3.11` | Session service container image |
| `TRANSLATE_IMAGE` | `libretranslate/libretranslate:v1.6.5` | Translation service image |
| `WHISPER_IMAGE` | `lintoai/linto-stt-whisper:2.0.0` | Whisper service image |
| `WHISPER_MODEL` | `small` | Whisper model size |
| `WHISPER_DEVICE` | `cpu` | Whisper inference device |
| `WHISPER_COMPUTE_TYPE` | `int8` | Whisper inference precision |
| `TRANSLATE_LANGUAGES` | `en,de,uk` | Comma-separated languages whose LibreTranslate models are loaded |
| `AUDIO_SAMPLE_RATE` | `16000` | Audio sample rate in Hz |
| `AUDIO_CHANNELS` | `1` | Number of audio channels |
| `AUDIO_CHUNK_DURATION_MS` | `100` | Audio frame duration sent to Whisper |
| `TRANSLATE_BASE_URL` | `http://translate:5000` | Internal Compose URL for LibreTranslate |
| `WHISPER_WS_URL` | `ws://whisper:80/ws` | Internal Compose URL for Whisper |
| `SERVICE_REQUEST_TIMEOUT` | `10` | HTTP timeout in seconds |
| `WHISPER_CONNECT_TIMEOUT` | `10` | Whisper WebSocket connection timeout in seconds |

The ports on the left side of each Compose port mapping are host ports; the
container ports on the right stay fixed for communication between services.
stinput reads `SESSION_HOST`, `SESSION_PORT`, and the audio settings from the
same root `.env` file. Process environment variables override values in `.env`.
The session app passes audio settings to the browser-based provider page.

The `*_BASE_URL` and `*_WS_URL` values are internal container-network URLs.
When changing them, use the target service's Compose service name and internal
container port, not its published host port.

After changing values, apply them with:

```sh
docker compose up -d
```

### Transcription settings

`WHISPER_MODEL`, `WHISPER_DEVICE`, and `WHISPER_COMPUTE_TYPE` control Whisper.
Choose values supported by the selected Whisper image and by your hardware.

### Translation

The translation models loaded by LibreTranslate are controlled by
`TRANSLATE_LANGUAGES` in `.env`.

`AUDIO_SAMPLE_RATE`, `AUDIO_CHANNELS`, and `AUDIO_CHUNK_DURATION_MS` are shared
by the session provider page and stinput client; keep these compatible with the
Whisper service's expected audio format.

### External images, models, and data

The Git repository contains the application code and configuration, not the
service images or speech/translation model data. The model/cache directories
are excluded from Git. Each user must obtain the required images and model
data for their own installation, and must have enough disk space and network
access for the initial downloads. Do not expect a fresh clone to include
working model files.

Docker Compose downloads the configured images when you run
`docker compose up -d`. The Whisper service downloads the configured model
when it is first used and caches it in `speach-to-text/whisper-cache`. See the
[LinTO Whisper Docker image documentation](https://hub.docker.com/r/lintoai/linto-stt-whisper),
its [environment variable reference](https://github.com/linto-ai/linto-stt/blob/master/ENV.md),
and the [OpenAI Whisper model card](https://github.com/openai/whisper/blob/main/model-card.md)
for model options and details. Model size affects download size, disk use,
memory, and processing requirements.

LibreTranslate uses Argos Translate language packages. On a fresh clone, run
the following once to download packages for the configured language codes into
the mounted local data directory:

```powershell
docker compose run --rm --entrypoint ./venv/bin/python translate `
  scripts/install_models.py --load_only_lang_codes en,de,uk
```

Change the codes to match `TRANSLATE_LANGUAGES` in `.env`. This command
downloads model data from upstream sources; it does not add those files to the
Git repository. The data remains in the ignored
`translate/libretranslate_models` directory on that machine. LibreTranslate's
[installation guide](https://docs.libretranslate.com/guides/installation/),
[Argos Translate package index](https://www.argosopentech.com/argospm/index/),
[Argos Translate project](https://github.com/argosopentech/argos-translate),
and [OPUS](https://opus.nlpl.eu/) provide package and data information.

Review and comply with the licenses and attribution requirements of each
selected model, dataset, and container image. Those terms are separate from
this project's Apache-2.0 license and can differ between model versions and
language pairs. For example, the locally installed Ukrainian-to-English
package identifies its underlying OPUS-MT model as CC-BY 4.0; verify the
upstream terms and attribution for the exact assets you install.

## Start up

### Run servers

From the project root, start the session server, Whisper, and LibreTranslate:

```powershell
docker compose up -d
```

The first startup may take several minutes while Docker downloads the images
and Whisper loads its model. Check service status and logs with:

```powershell
docker compose ps
docker compose logs -f session whisper translate
```

Open the session app at `http://localhost:8080` (or the configured
`SESSION_PORT`). The root page lists sessions for listeners. Open
`http://localhost:8080/provider.html` to create a session and launch the
speaker dashboard. Listeners select a live session and a translation language
from the session list.

To stop the stack, run:

```powershell
docker compose down
```

This stops and removes the containers but keeps the downloaded model files in
the repository's `translate/libretranslate_models` and
`speach-to-text/whisper-cache` folders. Session records and transcripts are
held in memory and are lost when the session service restarts.

### Run the STInput desktop client

STInput is an optional terminal user interface for streaming a microphone to
the session server. It can run alongside the browser interface. Install its
dependencies from the project root:

```powershell
py -m venv stinput\.venv
.\stinput\.venv\Scripts\python.exe -m pip install -r stinput\requirements.txt
```

With the servers running, launch the client:

```powershell
.\stinput\.venv\Scripts\python.exe stinput\app.py
```

Enter a speaker/session name, choose a spoken language and input device, then
select **Start stream**. Use **Stop stream** to end audio capture. The client
loads the root `.env` for its session host/port and audio settings; operating
system environment variables override values from that file. Grant microphone
access if the operating system or security software prompts for it.

Stopping the stream closes the audio connection but keeps the session ID in
STInput. Select **Start stream** again with the same session name and spoken
language to reconnect to that session. The session remains listed for
listeners, and they can continue using the same session link. Changing the
name or spoken language creates a new session on the next start; **Clear
inputs** clears the saved session reference as well.

### Generate the STInput client app

Build the standalone executable on the same operating system and architecture
where it will be used. From the project root, activate the STInput virtual
environment and install PyInstaller:

```powershell
.\stinput\.venv\Scripts\python.exe -m pip install pyinstaller
Set-Location stinput
.\.venv\Scripts\python.exe -m PyInstaller --clean STInput.spec
```

The executable is written to `stinput\dist\STInput.exe`. Start the session
servers before launching it. PyInstaller does not generally cross-compile, so
build a separate executable on Windows, macOS, and Linux as needed.

The source client reads the project-root `.env`. For a packaged executable,
configure `SESSION_HOST`, `SESSION_PORT`, and the audio settings in the
environment before launching it; the executable does not bundle the root
`.env`. For example, in PowerShell:

```powershell
$env:SESSION_HOST = "localhost"
$env:SESSION_PORT = "8080"
.\stinput\dist\STInput.exe
```

## How the services work

```text
Browser speaker page ─┐
                      ├── HTTP + WebSocket ──> Session server
STInput desktop app ──┘                             │
                                                   ├── audio ──> Whisper
                                                   │              speech-to-text
                                                   │
                                                   └── text ────> LibreTranslate
                                                                  translations
Browser listener page <──────── translated text ───┘
```

The session server creates sessions, receives manual text or audio transcripts,
requests translations, and broadcasts them to connected listeners. Whisper
transcribes audio; LibreTranslate translates the resulting text. Audio is sent
to Whisper through the session server and is not stored by this application.

## Session API

The session server exposes these endpoints for its web clients and STInput:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/locales` | List translation-service locales that report available target languages |
| `POST /session` | Create a session with a JSON body containing `name` and spoken `language`; returns `session_id` |
| `GET /sessions` | List in-memory sessions, listener counts, and each session's `audio_active` state |
| `GET /session/{session_id}` | Get session details, audio state/settings, and up to the 10 most recent transcripts |
| `POST /session/{session_id}/text` | Submit text to translate; expects a JSON body containing `text` |
| `WS /ws/audio/{session_id}` | Stream audio from the speaker client to Whisper |
| `WS /ws/subscribe/{session_id}?lang={code}` | Receive live translations for the selected target language and stream-state updates |

The API and WebSocket routes currently have no authentication or authorization;
see [Privacy and deployment security](#privacy-and-deployment-security) before
exposing the service to a network.

Translations are requested for languages with listeners currently connected
when a transcript is processed. For the expected live flow, listeners should
join and select their translation language before the speaker starts. The
provider page shows recent transcripts; listener pages receive new live
translations and do not replay earlier messages when they join.

## Session lifecycle and current limits

Sessions, subscribers, and transcripts are held in the session server's
memory. Restarting or recreating the session service removes them. The
provider dashboard shows recent transcripts, but the listener feed starts
receiving messages only after the listener joins; it does not load old
translations.

An audio stream is considered active while a speaker's audio WebSocket is
connected. The session list refreshes its active/inactive indicator every five
seconds. Ending the audio stream updates the listener page to show that no
more live translations are expected; the session itself remains available
until the service restarts.

Translations are generated for target languages with connected listeners
when each transcript is processed. If listeners join after a transcript was
processed, they will receive translations for later transcripts, not that
earlier one. The provider's recent-transcript list is limited to the latest
10 items returned by the session API.

## Languages and translation coverage

`TRANSLATE_LANGUAGES` controls which language models LibreTranslate loads; it
does not guarantee that every source/target combination can be translated.
LibreTranslate requires a compatible translation model or model path for a
language pair. The session app's `/api/locales` endpoint lists languages
reported by LibreTranslate as having translation targets, but a particular
pair may still be unavailable.

The session's language is the spoken/source language used in the Whisper
configuration. Listeners independently choose a target language. The
translation request currently uses automatic source-language detection, so
the selected session language should still match what is spoken, and needed
translation models must be installed and loaded by LibreTranslate.

After changing `TRANSLATE_LANGUAGES`, recreate the translation service so its
startup configuration is applied:

```powershell
docker compose up -d --force-recreate translate
```

## Troubleshooting

### Services do not start or a port is already in use

Check which services are running and inspect their logs:

```powershell
docker compose ps
docker compose logs --tail 100 session whisper translate
```

If a host port is already used, change the corresponding `SESSION_PORT`,
`TRANSLATE_PORT`, or `WHISPER_PORT` value in `.env`, then run
`docker compose up -d`. Container-side ports remain fixed. When changing
`SESSION_PORT`, STInput reads the new value from the root `.env`; set the same
port in the process environment when using the packaged executable.

### Languages are missing or translations fail

Check the LibreTranslate logs for model loading or download errors:

```powershell
docker compose logs --tail 150 translate
```

Confirm which locales the session server currently exposes:

```powershell
Invoke-RestMethod http://localhost:8080/api/locales |
  ConvertTo-Json -Depth 5
```

Use the configured session port instead of `8080` if it differs. Verify that
the required language models and translation pair are available to
LibreTranslate. Check that the speaker is using the correct spoken language
and that at least one listener has connected with the desired target language
before the text is processed.

### The browser cannot access the microphone

Allow microphone permission in the browser and operating system. Browsers
generally require a secure context (HTTPS) for microphone access; `localhost`
is also allowed for local development. If accessing the app from another
device, use an HTTPS deployment rather than the plain HTTP development URL.

### Audio or transcription stops unexpectedly

Inspect the session and Whisper logs:

```powershell
docker compose logs --tail 150 session whisper
```

Check that the selected Whisper model loaded successfully and that
`AUDIO_SAMPLE_RATE`, `AUDIO_CHANNELS`, and `AUDIO_CHUNK_DURATION_MS` are
compatible with the Whisper service and the capture device. Larger Whisper
models need more memory and processing capacity; on CPU, they may introduce
substantial transcription delay.

### A session link no longer works

Sessions and their transcripts are kept in the session process's memory.
Restarting or recreating that service clears them, so create a new session and
share its new link.

## Privacy and deployment security

This project is intended for development or a trusted network unless you add
appropriate deployment security. The current session API and WebSocket
endpoints have no authentication or authorization, and the Compose services
are published on host ports. Anyone who can reach the session service may be
able to create sessions, submit text, connect as a listener, or stream audio.
Do not expose these ports directly to the public internet.

Audio is forwarded from the speaker client through the session server to the
Whisper service for transcription. Transcript text and translations are kept
in session memory while the session server is running; they are not written
to a persistent transcript database by this application. Model files are
persisted in the configured local cache directories.

For deployment beyond a trusted local network, place the web application
behind a correctly configured HTTPS/WSS reverse proxy, restrict network
access to internal service ports, and add authentication and authorization
for session creation, speaker streams, and listener connections. Treat audio
and transcript text as potentially sensitive, and inform speakers and
listeners how the data is processed. The STInput client currently connects to
the configured session host over HTTP/WS, so do not use it across an
untrusted network without adding secure transport support.

## Proof of concept — not production-ready

This project is a personal proof of concept shared in the hope that it may be
useful to others. It is intended for local experimentation, development, and
small trusted-network trials. It is **not designed, load-tested, or optimized
for production use or a large audience at a venue**. In particular, it does
not provide an easy public access path for many attendees, nor does it include
capacity planning, load balancing, horizontal scaling, high availability,
resource limits, rate limiting, monitoring, or operational procedures.
Performance and transcription latency depend on the hardware, model, number
of connected listeners, and translation workload; no capacity or availability
is guaranteed.

Security protections expected of a production service are also missing.
Session creation and speaker/listener endpoints have no authentication or
authorization. The default Compose configuration publishes the session,
LibreTranslate, and Whisper ports on the host. Service-to-service traffic
inside the Docker network uses plain HTTP or WebSocket (not TLS); browser and
STInput connections also use HTTP/WS by default. Do not expose these ports or
send sensitive audio or text over an untrusted network. A production
deployment would need a security review and, at minimum, correctly configured
HTTPS/WSS, network restrictions for internal services, authentication and
authorization, and suitable capacity, monitoring, backup, and recovery
planning. These changes are not supplied or implied by this proof of concept.

## License

Unless a file or component says otherwise, this project is licensed under the
[Apache License 2.0](./LICENSE), copyright 2026 Tim P. It permits use,
modification, and redistribution subject to the license terms. It includes an
express disclaimer of warranties and a limitation of liability, but applicable
law may limit how those provisions apply. The license does not make users
waive every possible claim, and no license can waive rights that cannot
legally be waived.

The project uses separately licensed third-party software and models,
including the container images, Python packages, and translation/speech
models. The Apache license in this repository does not replace those
components' licenses or terms. Review the terms and attribution requirements
for each image, package, and model you obtain; see
[External images, models, and data](#external-images-models-and-data) for
upstream links. No complete third-party license audit is provided here.