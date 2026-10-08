from faster_whisper import WhisperModel
import numpy as np
from pathlib import Path
import shutil
import subprocess
import threading

from settings import WHISPER_MODEL, LOW_CONF_THRESHOLD

model = None
model_lock = threading.Lock()
transcription_lock = threading.Lock()


class FFmpegUnavailableError(RuntimeError):
    pass


class AudioDecodeError(RuntimeError):
    pass


def get_model():
    global model
    if model is None:
        with model_lock:
            if model is None:
                model = WhisperModel(
                    WHISPER_MODEL,
                    device="cpu",
                    compute_type="int8",
                )
    return model


def looks_weird(text: str) -> bool:
    words = text.lower().split()

    if len(words) < 4:
        return False

    unique_ratio = len(set(words)) / len(words)
    return unique_ratio < 0.5  # lots of repetition = suspicious


def _transcribe_source(
    source,
    *,
    language,
    vad_filter,
    progress_callback=None,
    hotwords=None,
    initial_prompt=None,
):
    with transcription_lock:
        if progress_callback is not None:
            # Model loading, decoding, VAD, and language detection do not expose
            # reliable incremental progress through faster-whisper.
            progress_callback(0.0, 0.0, "preparing")
        transcribe_options = {
            "language": language,
            "vad_filter": vad_filter,
            "beam_size": 5,
        }
        if hotwords:
            transcribe_options["hotwords"] = hotwords
        if initial_prompt:
            transcribe_options["initial_prompt"] = initial_prompt
        segments, info = get_model().transcribe(source, **transcribe_options)
        results = []
        duration = float(getattr(info, "duration", 0) or 0)

        if progress_callback is not None:
            progress_callback(0.0, duration, "transcribing")

        # faster-whisper performs inference while this generator is consumed.
        # With VAD enabled it removes silence for inference, then maps yielded
        # segment timestamps back onto the original media timeline. Using the
        # restored end time against info.duration therefore reports source-media
        # coverage instead of the shorter, compressed duration_after_vad.
        processed_seconds = 0.0
        for seg in segments:
            low_conf = seg.avg_logprob < LOW_CONF_THRESHOLD
            weird = looks_weird(seg.text)

            needs_review = low_conf or weird

            results.append(
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                    "confidence": round(seg.avg_logprob, 2),
                    "needs_review": needs_review,
                }
            )
            if progress_callback is not None:
                processed_seconds = max(processed_seconds, float(seg.end))
                progress_callback(processed_seconds, duration, "transcribing")

    return {
        "text": " ".join(segment["text"] for segment in results).strip(),
        "language": getattr(info, "language", language or "unknown"),
        "segments": results,
        "duration": duration,
    }


def transcribe(audio: np.ndarray, hotwords=None, initial_prompt=None):
    return _transcribe_source(
        audio,
        language="en",
        vad_filter=False,
        hotwords=hotwords,
        initial_prompt=initial_prompt,
    )["segments"]


def transcribe_file(
    input_path: Path,
    work_dir: Path,
    extension: str,
    progress_callback=None,
    postprocess_callback=None,
    hotwords=None,
):
    audio_path = input_path

    if extension != ".wav":
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise FFmpegUnavailableError(
                "FFmpeg is required for this format. On macOS, install it with "
                "`brew install ffmpeg`, then restart the backend."
            )

        audio_path = work_dir / "decoded.wav"
        process = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(input_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            detail = process.stderr.strip() or "FFmpeg could not decode the file."
            raise AudioDecodeError(detail)

    result = _transcribe_source(
        str(audio_path),
        language=None,
        vad_filter=True,
        progress_callback=progress_callback,
        hotwords=hotwords,
    )
    if postprocess_callback is not None:
        return postprocess_callback(audio_path, result)
    return result
