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


def _transcribe_source(source, *, language, vad_filter):
    with transcription_lock:
        segments, info = get_model().transcribe(
            source,
            language=language,
            vad_filter=vad_filter,
            beam_size=5,
        )
        results = []

        # faster-whisper performs inference while this generator is consumed.
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

    return {
        "text": " ".join(segment["text"] for segment in results).strip(),
        "language": getattr(info, "language", language or "unknown"),
        "segments": results,
    }


def transcribe(audio: np.ndarray):
    return _transcribe_source(
        audio,
        language="en",
        vad_filter=False,
    )["segments"]


def transcribe_file(input_path: Path, work_dir: Path, extension: str):
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

    return _transcribe_source(
        str(audio_path),
        language=None,
        vad_filter=True,
    )
