import { useEffect, useState } from "react";
import "./index.css";

function App() {
  const [segments, setSegments] = useState([]);
  const [status, setStatus] = useState({
    is_running: false,
    should_pause: false,
    transcript_count: 0
  });

  const start = async () => {
    await fetch("http://localhost:8000/start", {
      method: "POST",
    });
    updateStatus();
  };

  const pause = async () => {
    await fetch("http://localhost:8000/pause", {
      method: "POST",
    });
    updateStatus();
  };

  const resume = async () => {
    await fetch("http://localhost:8000/resume", {
      method: "POST",
    });
    updateStatus();
  };

  const stop = async () => {
    await fetch("http://localhost:8000/stop", {
      method: "POST",
    });
    updateStatus();
  };

  const updateStatus = async () => {
    const res = await fetch("http://localhost:8000/status");
    const data = await res.json();
    setStatus(data);
  };

  useEffect(() => {
    const interval = setInterval(async () => {
      // Get transcription data
      const transRes = await fetch("http://localhost:8000/transcript");
      const transData = await transRes.json();
      setSegments(transData);
      
      // Get status
      await updateStatus();
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="transcript">
      <div className="controls">
        <div className="buttons">
          {!status.is_running ? (
            <button onClick={start} className="btn btn-start">
              ▶ Start
            </button>
          ) : (
            <>
              {status.should_pause ? (
                <button onClick={resume} className="btn btn-resume">
                  ▶ Resume
                </button>
              ) : (
                <button onClick={pause} className="btn btn-pause">
                  ⏸ Pause
                </button>
              )}
              <button onClick={stop} className="btn btn-stop">
                ⏹ Stop
              </button>
            </>
          )}
        </div>
        
        <div className="status">
          <div className={`status-indicator ${status.is_running ? 'running' : 'stopped'}`}>
            <span className="status-dot"></span>
            {status.is_running ? (status.should_pause ? 'Paused' : 'Recording') : 'Stopped'}
          </div>
          <div className="transcript-count">
            {status.transcript_count} segments
          </div>
        </div>
      </div>

      <div className="transcript-display">
        {segments.length === 0 && !status.is_running && (
          <div className="placeholder">
            Click "Start" to begin transcription
          </div>
        )}
        
        {segments.length === 0 && status.is_running && (
          <div className="placeholder">
            🎙️ Listening... Speak clearly into your microphone
          </div>
        )}

        {segments.map((seg, i) => (
          <div
            key={i}
            className={`segment ${seg.needs_review ? "low-confidence" : ""}`}
            title={
              seg.needs_review
                ? `Low confidence (${seg.confidence})`
                : ""
            }
          >
            {seg.text}
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;
