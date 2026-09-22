function FileUploader({
  selectedFile,
  fileStatus,
  fileError,
  isDragging,
  fileInputRef,
  onChooseFile,
  onDraggingChange,
  onTranscribe,
  onReset,
  acceptedExtensions,
}) {
  return (
    <section className="work-card file-card" id="file-panel" role="tabpanel">
      <div className="card-heading-row file-heading">
        <div>
          <p className="section-kicker">Audio / video file</p>
          <h2>Transcribe a local recording</h2>
          <p>Choose a recording from your Mac. Nothing is uploaded to an external service.</p>
        </div>
      </div>

      <label
        className={`drop-zone ${isDragging ? "dragging" : ""}`}
        htmlFor="media-file"
        onDragEnter={(event) => {
          event.preventDefault();
          onDraggingChange(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => onDraggingChange(false)}
        onDrop={(event) => {
          event.preventDefault();
          onDraggingChange(false);
          onChooseFile(event.dataTransfer.files[0]);
        }}
      >
        <div className="upload-visual" aria-hidden="true">
          <span /><span /><span /><span /><span /><span /><span />
          <svg viewBox="0 0 24 24">
            <path d="M12 15.5V5m0 0L8 9m4-4 4 4M5 14.5v3.75A1.75 1.75 0 0 0 6.75 20h10.5A1.75 1.75 0 0 0 19 18.25V14.5" />
          </svg>
        </div>
        <strong>Drop audio or video here</strong>
        <p>Drag a file into this area, or <span className="browse-link">click to browse</span></p>
        <small>WAV · MP3 · M4A · MP4 · FLAC · OGG · WebM</small>
        <input
          id="media-file"
          ref={fileInputRef}
          className="visually-hidden"
          type="file"
          accept={acceptedExtensions}
          onChange={(event) => onChooseFile(event.target.files[0])}
        />
      </label>

      {selectedFile && (
        <div className="selected-file-card">
          <div className="file-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M7 3.75h6.8L18 8v12.25H7zM13.5 3.75V8H18" /></svg>
          </div>
          <div className="selected-file-copy">
            <span>Ready to transcribe</span>
            <strong>{selectedFile.name}</strong>
          </div>
          <span className={`file-state state-${fileStatus}`}>{fileStatus}</span>
          <div className="file-actions">
            <button className="btn btn-primary" onClick={onTranscribe}>Transcribe</button>
            <button className="btn btn-ghost" onClick={onReset}>Clear</button>
          </div>
        </div>
      )}

      {fileError && <div className="error-banner">{fileError}</div>}
    </section>
  );
}

export default FileUploader;
