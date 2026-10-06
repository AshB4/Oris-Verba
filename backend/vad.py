import webrtcvad
import numpy as np

from settings import SAMPLE_RATE, VAD_AGGRESSIVENESS

vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)


def is_speech(audio: np.ndarray) -> bool:
    pcm = (audio * 32768).astype("int16").tobytes()
    frame_len = int(0.03 * SAMPLE_RATE) * 2

    for i in range(0, len(pcm) - frame_len + 1, frame_len):
        frame = pcm[i : i + frame_len]
        if vad.is_speech(frame, SAMPLE_RATE):
            return True
    return False
