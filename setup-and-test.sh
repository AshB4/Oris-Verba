#!/bin/bash

# Oris-Verba Setup and Test Script
# This script sets up and tests the entire transcription pipeline

echo "🎙️  Setting up Oris-Verba..."

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
cd "$PROJECT_ROOT"

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo "❌ Error: Please run this script from the Oris-Verba root directory"
    exit 1
fi

# Backend setup
echo "📦 Setting up backend..."

# Create virtual environment if it doesn't exist
if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Use the project interpreter explicitly for every backend command.
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_ROOT/requirements.txt"
echo "Using Python: $("$VENV_DIR/bin/python" -c 'import sys; print(sys.executable)')"

cd "$PROJECT_ROOT/backend"

# Test backend components
echo "🧪 Testing backend components..."
"$VENV_DIR/bin/python" -c "
import sys
from audio_capture import start_capture
from vad import is_speech  
from settings import WHISPER_MODEL
from faster_whisper import WhisperModel
print('✅ All backend modules import successfully')
print(f'Using project Python: {sys.executable}')

# Download once when absent, or validate the existing Hugging Face cache.
WhisperModel(WHISPER_MODEL, device='cpu', compute_type='int8')
print(f'✅ Whisper model {WHISPER_MODEL!r} is cached and loads successfully')

# Test audio capture
stream = start_capture()
print('✅ Audio capture initialized')
stream.stop()
stream.close()
"

# Start backend server
echo "🚀 Starting backend server..."
"$VENV_DIR/bin/python" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Wait for backend to start
sleep 5

# Test backend endpoints
echo "🔍 Testing backend endpoints..."
curl -s -X POST http://localhost:8000/start
echo ""
curl -s -X GET http://localhost:8000/transcript
echo ""

# Frontend setup
echo "📦 Setting up frontend..."
cd "$PROJECT_ROOT/frontend"

# Install frontend dependencies
npm install

# Start frontend server
echo "🚀 Starting frontend server..."
npm run dev &
FRONTEND_PID=$!

# Wait for frontend to start
sleep 5

# Test frontend
echo "🔍 Testing frontend..."
curl -s http://localhost:5173 > /dev/null
if [ $? -eq 0 ]; then
    echo "✅ Frontend is running"
else
    echo "❌ Frontend failed to start"
fi

echo ""
echo "🎉 Oris-Verba is ready!"
echo ""
echo "📍 Services running:"
echo "   Backend API: http://localhost:8000"
echo "   API Docs: http://localhost:8000/docs"
echo "   Frontend: http://localhost:5173"
echo ""
echo "🎯 To test transcription:"
echo "   1. Open http://localhost:5173 in your browser"
echo "   2. Click the '▶ Start' button"
echo "   3. Allow microphone permissions when prompted"
echo "   4. Speak clearly and watch the transcription appear!"
echo ""
echo "🛑 To stop all services:"
echo "   kill $BACKEND_PID $FRONTEND_PID"
echo ""
echo "💡 Pro tip: The first transcription might take 10-15 seconds as Whisper loads the model"
