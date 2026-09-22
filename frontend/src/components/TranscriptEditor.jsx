function TranscriptEditor({ result, transcript, copyLabel, error, onTranscriptChange, onCopy, onDownload, onReset }) {
  return (
    <section className="transcript-card" id="file-panel" role="tabpanel">
      <div className="transcript-card-header">
        <div>
          <p className="section-kicker">Transcription complete</p>
          <h2>Transcript</h2>
        </div>
        <div className="transcript-meta">
          <strong>{result.filename}</strong>
          <span>
            {result?.language && `Language: ${result.language}`}
            {result?.segments && ` · ${result.segments.length} segments`}
          </span>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <textarea
        className="transcript-editor"
        value={transcript}
        onChange={(event) => onTranscriptChange(event.target.value)}
        aria-label="Editable transcript"
        placeholder="The transcript will appear here."
      />

      <div className="transcript-action-row">
        <p>Edit the text above before copying or downloading.</p>
        <div className="result-actions">
          <button className="btn btn-copy" onClick={onCopy} disabled={!transcript}>{copyLabel}</button>
          <button className="btn btn-secondary" onClick={onDownload} disabled={!transcript}>Download .txt</button>
          <button className="btn btn-ghost" onClick={onReset}>New File</button>
        </div>
      </div>
    </section>
  );
}

export default TranscriptEditor;
