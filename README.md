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

### Local speaker-detection setup

Speaker detection uses sherpa-onnx in a separate virtual environment so its native ONNX runtime is never imported into the working faster-whisper process. From the repository root:

```bash
./.venv/bin/python -m venv .venv-diarization
./.venv-diarization/bin/python -m pip install -r requirements-diarization.txt
mkdir -p models/diarization
curl -L https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2 -o /tmp/oris-verba-segmentation.tar.bz2
tar -xjf /tmp/oris-verba-segmentation.tar.bz2 -C models/diarization
curl -L https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx -o models/diarization/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx
```

Those downloads are model installation only. Once installed, speaker detection runs locally and does not need network access. The backend automatically uses `.venv-diarization/bin/python` and `models/diarization`. Override those locations with `ORIS_VERBA_DIARIZATION_PYTHON` and `ORIS_VERBA_DIARIZATION_MODELS` if needed.

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

Uploads are written to a temporary local directory. Non-WAV media is decoded locally with FFmpeg, passed to the existing faster-whisper model, and removed after success or failure. Speaker detection then runs locally in its isolated process and aligns speaker turns with the timestamped Whisper segments. The editable `text` uses generic `Speaker 1`, `Speaker 2`, and similar labels without timestamps; timestamped speaker turns remain available in the response.

While transcription is running, the homepage shows the actual browser upload bytes, an indeterminate **Preparing audio and loading model** phase, source-media coverage during transcription, and completion. faster-whisper removes silence before inference when VAD is enabled, then restores segment timestamps to the original recording timeline; Oris Verba uses those restored timestamps against the original duration so progress remains meaningful even when long silent sections were removed. Speaker detection reports completed diarization chunks when that optional phase is available.

The overall percentage uses fixed phase ranges so it never moves backward: upload covers the first 10%, transcription advances from 10–90% using processed source duration, and optional speaker detection advances from 90–99%. It reaches 100% only after the complete transcript response is ready. Phases without a reliable measure are shown as indeterminate—no timer-based progress is generated. Progress is transported by a small in-memory polling endpoint; finished and failed jobs expire after one hour, and at most 100 job records are retained. The local upload limit is 2 GiB.

If speaker detection is not installed or fails, the successful plain transcript is preserved and the UI shows: **Transcript completed, but speaker detection was unavailable.** Copy, download, and reset remain available.

## API

- `POST /start` — open the local microphone and start live transcription
- `POST /pause` — pause live processing
- `POST /resume` — resume live processing
- `POST /stop` — stop live capture and close the stream
- `GET /status` — live state and any capture error
- `GET /transcript` — live transcript segments
- `POST /transcribe-file` — transcribe one uploaded file
- `GET /transcribe-file/progress/{job_id}` — read local file-transcription progress
- `GET /docs` — interactive API documentation

File responses include:

```json
{
  "filename": "recording.mp3",
  "text": "Speaker 1: One clean transcript string.",
  "language": "en",
  "duration": 12.8,
  "speaker_count": 1,
  "segments": [
    {
      "start": 0.0,
      "end": 2.4,
      "text": "One clean transcript string.",
      "speaker": "Speaker 1",
      "confidence": -0.18,
      "needs_review": false
    }
  ],
  "speaker_turns": [
    {
      "start": 0.0,
      "end": 2.4,
      "speaker": "Speaker 1"
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
