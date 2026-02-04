# Oris-Verba 🎙️

Real-time speech transcription using OpenAI's Whisper model.

## Quick Start

### Prerequisites
- Python 3.8+ 
- Node.js 16+
- Microphone access

### One-Command Setup
```bash
./setup-and-test.sh
```

This will:
- Install all Python dependencies
- Install all Node.js dependencies  
- Start the backend API server
- Start the frontend development server
- Test all components

### Manual Setup

**Backend:**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r ../requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**
```bash
cd frontend  
npm install
npm run dev
```

## Usage

1. Open **http://localhost:5173** in your browser
2. Click the **"▶ Start"** button  
3. Allow microphone permissions
4. Speak clearly and watch the transcription appear in real-time!

## API Endpoints

- `POST /start` - Start transcription
- `GET /transcript` - Get current transcript buffer
- `GET /docs` - Interactive API documentation

## Current Features

- ✅ Real-time audio capture
- ✅ Voice Activity Detection (VAD)
- ✅ Whisper transcription with confidence scoring
- ✅ Low-confidence transcription highlighting
- ✅ Simple React frontend
- ✅ FastAPI backend with CORS support

## Next Steps

See `README-CAPTIONING-PLAN.txt` for the comprehensive roadmap to turn this into a professional closed captioning system.

## Troubleshooting

**Microphone not working?**
- Check microphone permissions in your browser
- Ensure your system has a working microphone

**Backend not starting?**
- Check if port 8000 is already in use
- Ensure all Python dependencies installed correctly

**Frontend not connecting?**
- Verify backend is running on http://localhost:8000
- Check browser console for CORS errors

## Architecture

- **Backend**: Python FastAPI + Whisper + WebRTC VAD
- **Frontend**: React + Vite
- **Audio Processing**: sounddevice + numpy
- **Transcription**: faster-whisper (optimized OpenAI Whisper)