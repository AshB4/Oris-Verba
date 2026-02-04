#!/bin/bash

# Oris-Verba Setup and Test Script
# This script sets up and tests the entire transcription pipeline

echo "🎙️  Setting up Oris-Verba..."

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo "❌ Error: Please run this script from the Oris-Verba root directory"
    exit 1
fi

# Backend setup
echo "📦 Setting up backend..."
cd backend

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment and install dependencies
source .venv/bin/activate
pip install -r ../requirements.txt

# Test backend components
echo "🧪 Testing backend components..."
python -c "
from audio_capture import start_capture
from vad import is_speech  
from scribe import transcribe
print('✅ All backend modules import successfully')

# Test audio capture
stream = start_capture()
print('✅ Audio capture initialized')
"

# Start backend server
echo "🚀 Starting backend server..."
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
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
cd ../frontend

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