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
    clear_audio_queue()
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=audio_callback,
    )
    try:
        stream.start()
    except Exception:
        stream.close()
        raise
    return stream


def stop_capture(stream):
    if stream is None:
        return

    try:
        if not stream.stopped:
            stream.stop()
    finally:
        stream.close()


def clear_audio_queue():
    while True:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            return


def get_audio_chunk(should_continue=lambda: True):
    frames = []
    start = time.time()

    while time.time() - start < CHUNK_SECONDS and should_continue():
        try:
            frames.append(audio_queue.get(timeout=0.1))
        except queue.Empty:
            pass

    if not frames:
        return None

    audio = np.concatenate(frames, axis=0)
    return audio.flatten()
