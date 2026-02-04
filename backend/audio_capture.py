import sounddevice as sd
import numpy as np
import queue
import time

from settings import SAMPLE_RATE, CHUNK_SECONDS

audio_queue = queue.Queue()


def audio_callback(indata, frames, time_info, status):
    if status:
        print(status)
    audio_queue.put(indata.copy())


def start_capture():
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        callback=audio_callback,
    )
    stream.start()
    return stream


def get_audio_chunk():
    frames = []
    start = time.time()

    while time.time() - start < CHUNK_SECONDS:
        try:
            frames.append(audio_queue.get(timeout=0.5))
        except queue.Empty:
            pass

    if not frames:
        return None

    audio = np.concatenate(frames, axis=0)
    return audio.flatten()
