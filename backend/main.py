from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import threading

from audio_capture import start_capture, get_audio_chunk
from vad import is_speech
from scribe import transcribe

app = FastAPI()

# Add CORS middleware to allow frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

transcript_buffer = []
is_running = False
should_pause = False


@app.post("/start")
def start():
    global is_running, should_pause
    if not is_running:
        is_running = True
        should_pause = False
        threading.Thread(target=run_loop, daemon=True).start()
        return {"status": "started", "is_running": True}
    else:
        return {"status": "already_running", "is_running": True}


@app.post("/pause")
def pause():
    global should_pause
    should_pause = True
    return {"status": "paused", "is_running": is_running, "should_pause": should_pause}


@app.post("/resume") 
def resume():
    global should_pause
    should_pause = False
    return {"status": "resumed", "is_running": is_running, "should_pause": should_pause}


@app.post("/stop")
def stop():
    global is_running, should_pause
    is_running = False
    should_pause = False
    return {"status": "stopped", "is_running": False}


@app.get("/status")
def status():
    return {
        "is_running": is_running,
        "should_pause": should_pause,
        "transcript_count": len(transcript_buffer)
    }


def run_loop():
    print("▶ capture loop started")
    stream = start_capture()

    while is_running:
        if should_pause:
            import time
            time.sleep(0.1)
            continue

        chunk = get_audio_chunk()

        if chunk is None:
            print("… no chunk")
            continue

        print("✔ got chunk", len(chunk))

        if not is_speech(chunk):
            print("… not speech")
            continue

        print("🗣 speech detected")

        segments = transcribe(chunk)
        print("✍ transcribed", segments)

        transcript_buffer.extend(segments)
    
    print("🛑 capture loop stopped")


@app.get("/transcript")
def transcript():
    return transcript_buffer


# To run the backend server:
# spython3 -m venv .venv
# source .venv/bin/activate
# uvicorn backend.main:app --reload
# Go to:
# http://localhost:5173
