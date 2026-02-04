from faster_whisper import WhisperModel
import numpy as np

from settings import WHISPER_MODEL, LOW_CONF_THRESHOLD

model = WhisperModel(
    WHISPER_MODEL,
    device="cpu",
    compute_type="int8",
)


def looks_weird(text: str) -> bool:
    words = text.lower().split()

    if len(words) < 4:
        return False

    unique_ratio = len(set(words)) / len(words)
    return unique_ratio < 0.5  # lots of repetition = suspicious


def transcribe(audio: np.ndarray):
    segments, info = model.transcribe(
        audio,
        language="en",
        vad_filter=False,
        beam_size=5,
    )

    results = []

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

    return results
