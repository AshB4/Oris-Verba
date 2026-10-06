import logging
from pathlib import Path
import tempfile
import threading
import time

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from audio_capture import clear_audio_queue, get_audio_chunk, start_capture, stop_capture
from diarization import diarize_transcript
from scribe import AudioDecodeError, FFmpegUnavailableError, transcribe, transcribe_file
from vad import is_speech


logger = logging.getLogger(__name__)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".webm"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
UPLOAD_COPY_CHUNK_SIZE = 1024 * 1024
MAX_FILE_JOBS = 100
FILE_JOB_TTL_SECONDS = 60 * 60
TRANSCRIPTION_START_PERCENT = 10.0
TRANSCRIPTION_END_PERCENT = 90.0
DIARIZATION_END_PERCENT = 99.0

transcript_buffer = []
is_running = False
is_starting = False
should_pause = False
last_error = None
active_stream = None
capture_thread = None
state_lock = threading.Lock()
file_job_lock = threading.Lock()
file_jobs = {}


def cleanup_file_jobs(now=None):
    now = time.monotonic() if now is None else now
    expired = [
        job_id
        for job_id, job in file_jobs.items()
        if job["status"] in {"complete", "error"}
        and now - job["updated_at"] >= FILE_JOB_TTL_SECONDS
    ]
    for job_id in expired:
        del file_jobs[job_id]


def file_job_snapshot(job):
    return {key: value for key, value in job.items() if key not in {"created_at", "updated_at"}}


def update_file_job(job_id, **updates):
    if not job_id:
        return
    with file_job_lock:
        now = time.monotonic()
        cleanup_file_jobs(now)
        if job_id not in file_jobs and len(file_jobs) >= MAX_FILE_JOBS:
            finished_jobs = [
                (existing_id, job)
                for existing_id, job in file_jobs.items()
                if job["status"] in {"complete", "error"}
            ]
            if finished_jobs:
                oldest_id, _job = min(finished_jobs, key=lambda item: item[1]["updated_at"])
                del file_jobs[oldest_id]
            else:
                return
        job = file_jobs.setdefault(
            job_id,
            {
                "status": "preparing",
                "percent": None,
                "stage_percent": None,
                "processed_seconds": 0.0,
                "duration_seconds": None,
                "error": None,
                "progress_metric": None,
                "created_at": now,
                "updated_at": now,
            },
        )
        requested_percent = updates.get("percent")
        current_percent = job.get("percent")
        if requested_percent is not None:
            requested_percent = float(requested_percent)
            if updates.get("status") != "complete":
                requested_percent = min(99.0, requested_percent)
            if current_percent is not None:
                requested_percent = max(float(current_percent), requested_percent)
            updates["percent"] = round(requested_percent, 1)
        requested_stage_percent = updates.get("stage_percent")
        if (
            requested_stage_percent is not None
            and updates.get("status", job["status"]) == job["status"]
            and job.get("stage_percent") is not None
        ):
            updates["stage_percent"] = max(
                float(job["stage_percent"]),
                float(requested_stage_percent),
            )
        requested_processed = updates.get("processed_seconds")
        if requested_processed is not None:
            updates["processed_seconds"] = max(
                float(job.get("processed_seconds") or 0.0),
                float(requested_processed),
            )
        job.update(updates)
        job["updated_at"] = now


def update_transcription_progress(job_id, processed_seconds, duration_seconds, stage):
    if stage != "transcribing":
        update_file_job(
            job_id,
            status="preparing",
            percent=None,
            stage_percent=None,
            progress_metric=None,
        )
        return

    duration_seconds = max(0.0, float(duration_seconds))
    processed_seconds = max(0.0, float(processed_seconds))
    if duration_seconds > 0:
        processed_seconds = min(processed_seconds, duration_seconds)
    percent = None
    stage_percent = None
    if duration_seconds > 0:
        stage_percent = min(100.0, processed_seconds / duration_seconds * 100)
        percent = TRANSCRIPTION_START_PERCENT + (
            (TRANSCRIPTION_END_PERCENT - TRANSCRIPTION_START_PERCENT) * stage_percent / 100
        )
    update_file_job(
        job_id,
        status="transcribing",
        percent=round(percent, 1) if percent is not None else None,
        stage_percent=round(stage_percent, 1) if stage_percent is not None else None,
        processed_seconds=round(processed_seconds, 2),
        duration_seconds=round(duration_seconds, 2) if duration_seconds > 0 else None,
        progress_metric="source_media_time",
    )


def update_diarization_progress(job_id, processed_chunks, total_chunks):
    percent = None
    stage_percent = None
    if total_chunks > 0:
        stage_percent = min(100.0, max(0.0, processed_chunks / total_chunks * 100))
        percent = TRANSCRIPTION_END_PERCENT + (
            (DIARIZATION_END_PERCENT - TRANSCRIPTION_END_PERCENT) * stage_percent / 100
        )
    update_file_job(
        job_id,
        status="diarizing",
        percent=round(percent, 1) if percent is not None else None,
        stage_percent=round(stage_percent, 1) if stage_percent is not None else None,
        progress_metric="diarization_chunks",
    )


def add_speaker_labels(audio_path, transcription, job_id):
    update_file_job(
        job_id,
        status="diarizing",
        percent=TRANSCRIPTION_END_PERCENT,
        stage_percent=None,
        progress_metric="diarization_chunks",
    )
    try:
        return diarize_transcript(
            audio_path,
            transcription,
            progress_callback=lambda processed, total: update_diarization_progress(
                job_id,
                processed,
                total,
            ),
        )
    except Exception as exc:
        logger.warning("Speaker detection failed; returning the plain transcript: %s", exc)
        return {
            **transcription,
            "diarization_warning": "Transcript completed, but speaker detection was unavailable.",
        }


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
    global active_stream, capture_thread, is_running, last_error, should_pause
    with state_lock:
        stream = active_stream
        thread = capture_thread

    close_error = None
    try:
        # Stop callbacks before signaling the capture loop to drain its final
        # queued frames. stop_capture is serialized and safe to call again from
        # run_loop's final cleanup.
        stop_capture(stream)
    except Exception as exc:
        close_error = exc
    finally:
        with state_lock:
            is_running = False
            should_pause = False

    if thread is not None and thread is not threading.current_thread():
        thread.join()

    with state_lock:
        if active_stream is stream:
            active_stream = None
        if capture_thread is thread:
            capture_thread = None

    if close_error is not None:
        with state_lock:
            last_error = f"Could not close the microphone cleanly: {close_error}"
        raise HTTPException(status_code=500, detail=last_error) from close_error

    return {"status": "stopped", **state_snapshot()}


@app.get("/status")
def status():
    return state_snapshot()


def capture_should_continue():
    with state_lock:
        return is_running and not should_pause


def capture_should_flush():
    with state_lock:
        return not is_running


def run_loop(stream):
    global active_stream, capture_thread, is_running, last_error, should_pause

    try:
        while True:
            with state_lock:
                running = is_running
                paused = should_pause

            if paused:
                clear_audio_queue()
                time.sleep(0.1)
                continue

            chunk = get_audio_chunk(
                capture_should_continue,
                capture_should_flush,
            )
            with state_lock:
                running = is_running
                paused = should_pause

            if chunk is None:
                if not running:
                    break
                continue
            if paused:
                continue
            if not is_speech(chunk):
                if not running:
                    break
                continue

            segments = transcribe(chunk)
            with state_lock:
                transcript_buffer.extend(segments)
            if not running:
                break
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
            if capture_thread is threading.current_thread():
                capture_thread = None
            is_running = False
            should_pause = False


@app.get("/transcript")
def transcript():
    with state_lock:
        return list(transcript_buffer)


@app.get("/transcribe-file/progress/{job_id}")
def transcribe_file_progress(job_id: str):
    with file_job_lock:
        cleanup_file_jobs()
        job = file_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Transcription job not found.")
        return file_job_snapshot(job)


@app.post("/transcribe-file")
def transcribe_uploaded_file(file: UploadFile = File(...), job_id: str | None = None):
    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Choose one of: {supported}.",
        )

    update_file_job(job_id, status="preparing", percent=None, stage_percent=None)

    try:
        with tempfile.TemporaryDirectory(prefix="oris-verba-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            input_path = temp_dir / f"upload{extension}"
            with input_path.open("wb") as destination:
                copied_bytes = 0
                while chunk := file.file.read(UPLOAD_COPY_CHUNK_SIZE):
                    copied_bytes += len(chunk)
                    if copied_bytes > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail="File is too large. The local limit is 2 GiB.",
                        )
                    destination.write(chunk)

            update_file_job(job_id, status="preparing")
            result = transcribe_file(
                input_path,
                temp_dir,
                extension,
                progress_callback=lambda processed, duration, stage: update_transcription_progress(
                    job_id,
                    processed,
                    duration,
                    stage,
                ),
                postprocess_callback=lambda audio_path, transcription: add_speaker_labels(
                    audio_path,
                    transcription,
                    job_id,
                ),
            )
            update_file_job(
                job_id,
                status="complete",
                percent=100.0,
                stage_percent=100.0,
                processed_seconds=result.get("duration", 0),
                duration_seconds=result.get("duration") or None,
                progress_metric="complete",
            )
            return {"filename": original_name, **result}
    except FFmpegUnavailableError as exc:
        update_file_job(job_id, status="error", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AudioDecodeError as exc:
        detail = f"Could not decode {original_name}: {exc}"
        update_file_job(job_id, status="error", error=detail)
        raise HTTPException(status_code=422, detail=detail) from exc
    except HTTPException as exc:
        update_file_job(job_id, status="error", error=exc.detail)
        raise
    except Exception as exc:
        detail = f"Transcription failed: {exc}"
        update_file_job(job_id, status="error", error=detail)
        raise HTTPException(status_code=500, detail=detail) from exc
    finally:
        file.file.close()


# Run from backend/: ../.venv/bin/python -m uvicorn main:app --reload
