# Oris-Verba

Local microphone and file transcription using FastAPI, React, WebRTC VAD, and faster-whisper. Audio stays on the machine. The application does not use a cloud transcription API or upload media to an external service.

## Requirements

- Python 3.12 recommended
- Node.js 20+
- A working macOS input device for live transcription
- FFmpeg for compressed audio and video files

Install FFmpeg on macOS:

```bash
brew install ffmpeg
```

## Local setup

From the repository root:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cd frontend
npm install
```

The configured Whisper model is `small` in `backend/settings.py`. Cache it once while online:

```bash
cd backend
../.venv/bin/python -c "from settings import WHISPER_MODEL; from faster_whisper import WhisperModel; WhisperModel(WHISPER_MODEL, device='cpu', compute_type='int8'); print(f'{WHISPER_MODEL} cached')"
```

After the model is cached, transcription works offline. To verify the cache without network access:

```bash
cd backend
HF_HUB_OFFLINE=1 ../.venv/bin/python -c "from settings import WHISPER_MODEL; from faster_whisper import WhisperModel; WhisperModel(WHISPER_MODEL, device='cpu', compute_type='int8', local_files_only=True); print(f'{WHISPER_MODEL} loads offline')"
```

## Start the application

Backend, from the repository root:

```bash
cd backend && ../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Frontend, in a second terminal from the repository root:

```bash
cd frontend && npm run dev
```

Open <http://localhost:5173>.

## Live microphone transcription

1. Select **Live microphone**.
2. Click **Start**.
3. Speak into the Mac's selected input device.
4. Use **Pause**, **Resume**, and **Stop** as needed.

The microphone is opened by the local Python backend, not by the browser. On macOS, grant microphone access to the terminal application that starts the backend under **System Settings → Privacy & Security → Microphone**. Device and transcription failures appear in the UI.

## File transcription

1. Select **Audio / video file**.
2. Drag a file into the drop area or click **Choose file**.
3. Click **Transcribe**.
4. Edit the completed transcript if needed.
5. Copy it, download it as `.txt`, or choose **New File / Reset**.

Supported formats:

- `.wav`
- `.mp3`
- `.m4a`
- `.mp4`
- `.flac`
- `.ogg`
- `.webm`

Uploads are written to a temporary local directory. Non-WAV media is decoded locally with FFmpeg, passed to the existing faster-whisper model, and removed after success or failure. The response keeps the transcript as one clean `text` string and also returns timestamped segments with confidence/review metadata.

## API

- `POST /start` — open the local microphone and start live transcription
- `POST /pause` — pause live processing
- `POST /resume` — resume live processing
- `POST /stop` — stop live capture and close the stream
- `GET /status` — live state and any capture error
- `GET /transcript` — live transcript segments
- `POST /transcribe-file` — transcribe one uploaded file
- `GET /docs` — interactive API documentation

File responses include:

```json
{
  "filename": "recording.mp3",
  "text": "One clean transcript string.",
  "language": "en",
  "segments": [
    {
      "start": 0.0,
      "end": 2.4,
      "text": "One clean transcript string.",
      "confidence": -0.18,
      "needs_review": false
    }
  ]
}
```

## Troubleshooting

### OpenMP or `libiomp5` crash on macOS

Use only the project interpreter for backend commands:

```bash
./.venv/bin/python -c "import sys; print(sys.executable)"
```

It should print a path inside this repository. Shared Python installations may contain PyTorch, Functorch, scikit-learn, or FAISS, which bundle OpenMP runtimes that conflict with CTranslate2. Do not permanently set `KMP_DUPLICATE_LIB_OK=TRUE`; it hides the conflict rather than fixing it.

### Whisper model unavailable

Run the model-cache command in **Local setup** once while online. Then rerun the offline verification command. No Ollama installation is needed.

### Microphone cannot start

- Confirm an input device is selected in macOS Sound settings.
- Grant microphone access to the terminal running the backend.
- Restart the backend after changing macOS permissions.

### File cannot be decoded

Run `ffmpeg -version`. If it is missing, install it with `brew install ffmpeg` and restart the backend.

## Tests

Backend tests are short-lived and mock Whisper inference:

```bash
cd backend && ../.venv/bin/python -m unittest test_app.py -v
```

Frontend checks:

```bash
cd frontend && npm run lint && npm run build
```
