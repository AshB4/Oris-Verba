import json
import os
from pathlib import Path
import shutil
import subprocess
import wave


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIARIZATION_PYTHON = Path(
    os.environ.get(
        "ORIS_VERBA_DIARIZATION_PYTHON",
        PROJECT_ROOT / ".venv-diarization" / "bin" / "python",
    )
)
DIARIZATION_MODELS_DIR = Path(
    os.environ.get(
        "ORIS_VERBA_DIARIZATION_MODELS",
        PROJECT_ROOT / "models" / "diarization",
    )
)
SEGMENTATION_MODEL = DIARIZATION_MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.int8.onnx"
EMBEDDING_MODEL = DIARIZATION_MODELS_DIR / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
WORKER_PATH = Path(__file__).resolve().parent / "diarization_worker.py"


class DiarizationError(RuntimeError):
    pass


def _is_compatible_wave(audio_path: Path) -> bool:
    try:
        with wave.open(str(audio_path), "rb") as audio:
            return (
                audio.getnchannels() == 1
                and audio.getsampwidth() == 2
                and audio.getframerate() == 16000
            )
    except (OSError, wave.Error):
        return False


def _prepare_audio(audio_path: Path) -> Path:
    if _is_compatible_wave(audio_path):
        return audio_path

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise DiarizationError("FFmpeg is required to prepare audio for speaker detection.")

    prepared_path = audio_path.parent / "diarization.wav"
    process = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(audio_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-sample_fmt",
            "s16",
            str(prepared_path),
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or "FFmpeg could not prepare the audio."
        raise DiarizationError(detail)
    return prepared_path


def _require_local_assets():
    missing = [
        path
        for path in (DIARIZATION_PYTHON, SEGMENTATION_MODEL, EMBEDDING_MODEL, WORKER_PATH)
        if not path.is_file()
    ]
    if missing:
        raise DiarizationError(
            "Local speaker detection is not installed. Follow the diarization setup in README.md."
        )


def run_local_diarization(audio_path: Path, progress_callback=None):
    _require_local_assets()
    prepared_path = _prepare_audio(audio_path)
    command = [
        str(DIARIZATION_PYTHON),
        str(WORKER_PATH),
        "--audio",
        str(prepared_path),
        "--segmentation-model",
        str(SEGMENTATION_MODEL),
        "--embedding-model",
        str(EMBEDDING_MODEL),
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    result = None
    diagnostic_lines = []

    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if line.startswith("ORIS_PROGRESS "):
            event = json.loads(line.removeprefix("ORIS_PROGRESS "))
            if progress_callback is not None:
                progress_callback(event["processed_chunks"], event["total_chunks"])
        elif line.startswith("ORIS_RESULT "):
            result = json.loads(line.removeprefix("ORIS_RESULT "))
        elif line:
            diagnostic_lines.append(line)
            diagnostic_lines = diagnostic_lines[-20:]

    return_code = process.wait()
    if return_code != 0 or result is None:
        detail = diagnostic_lines[-1] if diagnostic_lines else "Speaker detection process failed."
        raise DiarizationError(detail)

    return result.get("turns", [])


def _speaker_for_segment(segment, turns):
    segment_start = float(segment["start"])
    segment_end = float(segment["end"])

    best_turn = None
    best_overlap = 0.0
    for turn in turns:
        overlap = max(
            0.0,
            min(segment_end, float(turn["end"])) - max(segment_start, float(turn["start"])),
        )
        if overlap > best_overlap:
            best_overlap = overlap
            best_turn = turn

    if best_turn is not None:
        return best_turn["speaker"]

    midpoint = (segment_start + segment_end) / 2
    nearest = min(
        turns,
        key=lambda turn: min(
            abs(midpoint - float(turn["start"])),
            abs(midpoint - float(turn["end"])),
        ),
    )
    return nearest["speaker"]


def label_transcript_segments(segments, turns):
    if not segments or not turns:
        raise DiarizationError("No speaker turns were detected.")

    ordered_turns = sorted(turns, key=lambda turn: (float(turn["start"]), float(turn["end"])))
    speaker_labels = {}
    for turn in ordered_turns:
        speaker = turn["speaker"]
        if speaker not in speaker_labels:
            speaker_labels[speaker] = f"Speaker {len(speaker_labels) + 1}"

    labeled_segments = []
    paragraphs = []
    for segment in segments:
        speaker = _speaker_for_segment(segment, ordered_turns)
        label = speaker_labels[speaker]
        labeled_segment = {**segment, "speaker": label}
        labeled_segments.append(labeled_segment)

        text = segment["text"].strip()
        if not text:
            continue
        if paragraphs and paragraphs[-1]["speaker"] == label:
            paragraphs[-1]["text"] = f'{paragraphs[-1]["text"]} {text}'
        else:
            paragraphs.append({"speaker": label, "text": text})

    if not paragraphs:
        raise DiarizationError("No transcribed speech could be aligned with speaker turns.")

    text = "\n\n".join(
        f'{paragraph["speaker"]}: {paragraph["text"]}' for paragraph in paragraphs
    )
    return {
        "text": text,
        "segments": labeled_segments,
        "speaker_count": len(speaker_labels),
        "speaker_turns": [
            {
                "start": float(turn["start"]),
                "end": float(turn["end"]),
                "speaker": speaker_labels[turn["speaker"]],
            }
            for turn in ordered_turns
        ],
    }


def diarize_transcript(audio_path: Path, transcription, progress_callback=None):
    turns = run_local_diarization(audio_path, progress_callback=progress_callback)
    return {**transcription, **label_transcript_segments(transcription["segments"], turns)}
