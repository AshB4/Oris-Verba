import numpy as np
import queue
import threading
import time

from settings import SAMPLE_RATE, CHUNK_SECONDS

audio_queue = queue.Queue()
stream_cleanup_lock = threading.Lock()


def audio_callback(indata, frames, time_info, status):
    if status:
        print(status)
    audio_queue.put(indata.copy())


def start_capture():
    # Importing sounddevice initializes PortAudio, so defer it until the user
    # explicitly starts live transcription.
    import sounddevice as sd

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
    with stream_cleanup_lock:
        if stream is None or stream.closed:
            return

        try:
            if not stream.stopped:
                stream.stop()
        finally:
            if not stream.closed:
                stream.close()


def clear_audio_queue():
    while True:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            return


def get_audio_chunk(should_continue=lambda: True, should_flush=lambda: False):
    frames = []
    start = time.time()

    while time.time() - start < CHUNK_SECONDS and should_continue():
        try:
            frames.append(audio_queue.get(timeout=0.1))
        except queue.Empty:
            pass

    if should_flush():
        while True:
            try:
                frames.append(audio_queue.get_nowait())
            except queue.Empty:
                break

    if not frames:
        return None

    audio = np.concatenate(frames, axis=0)
    return audio.flatten()
