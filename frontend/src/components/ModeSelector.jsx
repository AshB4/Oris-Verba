function ModeSelector({ mode, onChange }) {
  return (
    <div className="mode-selector-wrap">
      <div className="mode-switch" role="tablist" aria-label="Transcription mode">
        <button
          className={mode === "live" ? "mode-button active" : "mode-button"}
          onClick={() => onChange("live")}
          role="tab"
          aria-selected={mode === "live"}
          aria-controls="live-panel"
        >
          <span className="mode-icon live-mode-icon" aria-hidden="true">
            <i /><i /><i />
          </span>
          Live microphone
        </button>
        <button
          className={mode === "file" ? "mode-button active" : "mode-button"}
          onClick={() => onChange("file")}
          role="tab"
          aria-selected={mode === "file"}
          aria-controls="file-panel"
        >
          <svg className="mode-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M7 3.75h6.8L18 8v12.25H7zM13.5 3.75V8H18" />
          </svg>
          Audio / video file
        </button>
      </div>
    </div>
  );
}

export default ModeSelector;
