function LiveControls({
  liveStatus,
  liveBusy,
  liveError,
  segments,
  liveTranscript,
  copyLabel,
  onAction,
  onClear,
  onCopy,
  onDownload,
  vocabularyHints,
  onVocabularyHintsChange,
}) {
  const liveLabel = liveStatus.is_starting
    ? "Starting"
    : liveStatus.is_stopping
      ? "Stopping"
      : liveStatus.is_running
        ? liveStatus.should_pause
          ? "Paused"
          : "Listening"
        : "Ready";

  return (
    <section className="work-card live-card" id="live-panel" role="tabpanel">
      <div className="card-heading-row">
        <div>
          <p className="section-kicker">Live microphone</p>
          <h2>Capture speech as it happens</h2>
          <p>Use your Mac’s selected input device. Transcription stays on this computer.</p>
        </div>
        <div className={`status-pill ${liveStatus.is_running ? "is-active" : ""}`}>
          <span className="status-dot" aria-hidden="true" />
          {liveLabel}
        </div>
      </div>

      <label className="vocabulary-field">
        <span>
          <strong>Vocabulary hints</strong>
          <small>Words the transcriber may need help recognizing.</small>
        </span>
        <input
          type="text"
          value={vocabularyHints}
          onChange={(event) => onVocabularyHintsChange(event.target.value)}
          maxLength={500}
          placeholder="Names, acronyms, unusual words"
          autoComplete="off"
          disabled={liveBusy || liveStatus.is_running || liveStatus.is_starting || liveStatus.is_stopping}
        />
      </label>

      <div className={`live-stage ${liveStatus.is_running ? "is-listening" : ""}`}>
        <div className="live-waveform" aria-hidden="true">
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((bar) => <span key={bar} />)}
        </div>
        <div className="live-stage-copy">
          <strong>{liveStatus.is_running ? (liveStatus.should_pause ? "Microphone paused" : "Listening for speech") : "Microphone ready"}</strong>
          <span>
            {liveStatus.is_running
              ? liveStatus.should_pause
                ? "Resume when you’re ready to continue."
                : "Speak naturally. Completed phrases will appear below."
              : "Start when you’re ready to begin a live transcript."}
          </span>
        </div>
        <div className="live-stat">
          <strong>{liveStatus.transcript_count}</strong>
          <span>segments</span>
        </div>
      </div>

      <div className="live-action-row">
        <div className="buttons">
          {!liveStatus.is_running ? (
            <button
              onClick={() => onAction("start")}
              className="btn btn-primary"
              disabled={liveBusy || liveStatus.is_starting || liveStatus.is_stopping}
            >
              Start transcription
            </button>
          ) : (
            <>
              {liveStatus.should_pause ? (
                <button onClick={() => onAction("resume")} className="btn btn-secondary" disabled={liveBusy}>
                  Resume
                </button>
              ) : (
                <button onClick={() => onAction("pause")} className="btn btn-secondary" disabled={liveBusy}>
                  Pause
                </button>
              )}
              <button onClick={() => onAction("stop")} className="btn btn-stop" disabled={liveBusy}>
                Stop
              </button>
            </>
          )}
          <button
            onClick={onClear}
            className="btn btn-ghost"
            disabled={
              liveBusy
              || liveStatus.is_running
              || liveStatus.is_starting
              || liveStatus.is_stopping
              || !liveTranscript
            }
          >
            New session / Clear transcript
          </button>
        </div>
        <span className="live-note">WebRTC voice activity detection enabled</span>
      </div>

      {liveError && <div className="error-banner">{liveError}</div>}

      {segments.length > 0 && (
        <div className="live-transcript">
          <div className="transcript-heading">
            <div>
              <p className="section-kicker">Live transcript</p>
              <h3>Captured text</h3>
            </div>
            <div className="live-transcript-tools">
              <span>{segments.length} {segments.length === 1 ? "segment" : "segments"}</span>
              <button className="btn btn-copy btn-small" onClick={onCopy} disabled={!liveTranscript}>{copyLabel}</button>
              <button className="btn btn-secondary btn-small" onClick={onDownload} disabled={!liveTranscript}>Download .txt</button>
            </div>
          </div>
          <div className="segment-list" aria-live="polite">
            {segments.map((segment, index) => (
              <p
                key={`${segment.start}-${index}`}
                className={`segment ${segment.needs_review ? "low-confidence" : ""}`}
                title={segment.needs_review ? `Low confidence (${segment.confidence})` : ""}
              >
                {segment.text}
              </p>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

export default LiveControls;
