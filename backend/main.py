from pathlib import Path
import shutil
import tempfile
import threading
import time

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from audio_capture import clear_audio_queue, get_audio_chunk, start_capture, stop_capture
from scribe import AudioDecodeError, FFmpegUnavailableError, transcribe, transcribe_file
from vad import is_speech


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".webm"}

transcript_buffer = []
is_running = False
is_starting = False
should_pause = False
last_error = None
active_stream = None
capture_thread = None
state_lock = threading.Lock()


def state_snapshot_unlocked():
    return {
        "is_running": is_running,
        "is_starting": is_starting,
        "is_stopping": active_stream is not None and not is_running,
        "should_pause": should_pause,
        "transcript_count": len(transcript_buffer),
        "error": last_error,
    }


def state_snapshot():
    with state_lock:
        return state_snapshot_unlocked()


@app.post("/start")
def start():
    global active_stream, capture_thread, is_running, is_starting, last_error, should_pause

    with state_lock:
        if is_running or is_starting:
            return {"status": "already_running", **state_snapshot_unlocked()}
        if active_stream is not None:
            raise HTTPException(status_code=409, detail="The microphone is still stopping. Try again in a moment.")
        is_starting = True
        last_error = None

    try:
        stream = start_capture()
    except Exception as exc:
        message = f"Could not start the microphone: {exc}"
        with state_lock:
            is_starting = False
            is_running = False
            last_error = message
        raise HTTPException(status_code=503, detail=message) from exc

    with state_lock:
        active_stream = stream
        is_starting = False
        is_running = True
        should_pause = False
        capture_thread = threading.Thread(target=run_loop, args=(stream,), daemon=True)
        capture_thread.start()

    return {"status": "started", **state_snapshot()}


@app.post("/pause")
def pause():
    global should_pause
    with state_lock:
        if not is_running:
            raise HTTPException(status_code=409, detail="Microphone transcription is not running.")
        should_pause = True
    clear_audio_queue()
    return {"status": "paused", **state_snapshot()}


@app.post("/resume")
def resume():
    global should_pause
    with state_lock:
        if not is_running:
            raise HTTPException(status_code=409, detail="Microphone transcription is not running.")
        should_pause = False
    clear_audio_queue()
    return {"status": "resumed", **state_snapshot()}


@app.post("/stop")
def stop():
    global is_running, should_pause
    with state_lock:
        is_running = False
        should_pause = False
    clear_audio_queue()
    return {"status": "stopped", **state_snapshot()}


@app.get("/status")
def status():
    return state_snapshot()


def capture_should_continue():
    with state_lock:
        return is_running and not should_pause


def run_loop(stream):
    global active_stream, is_running, last_error, should_pause

    try:
        while True:
            with state_lock:
                running = is_running
                paused = should_pause

            if not running:
                break
            if paused:
                clear_audio_queue()
                time.sleep(0.1)
                continue

            chunk = get_audio_chunk(capture_should_continue)
            if chunk is None or not capture_should_continue():
                continue
            if not is_speech(chunk):
                continue

            segments = transcribe(chunk)
            with state_lock:
                transcript_buffer.extend(segments)
    except Exception as exc:
        with state_lock:
            last_error = f"Microphone transcription stopped: {exc}"
    finally:
        try:
            stop_capture(stream)
        except Exception as exc:
            with state_lock:
                if last_error is None:
                    last_error = f"Could not close the microphone cleanly: {exc}"
        clear_audio_queue()
        with state_lock:
            if active_stream is stream:
                active_stream = None
            is_running = False
            should_pause = False


@app.get("/transcript")
def transcript():
    with state_lock:
        return list(transcript_buffer)


@app.post("/transcribe-file")
def transcribe_uploaded_file(file: UploadFile = File(...)):
    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Choose one of: {supported}.",
        )

    try:
        with tempfile.TemporaryDirectory(prefix="oris-verba-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            input_path = temp_dir / f"upload{extension}"
            with input_path.open("wb") as destination:
                shutil.copyfileobj(file.file, destination)

            result = transcribe_file(input_path, temp_dir, extension)
            return {"filename": original_name, **result}
    except FFmpegUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AudioDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Could not decode {original_name}: {exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc
    finally:
        file.file.close()


# Run from backend/: ../.venv/bin/python -m uvicorn main:app --reload
