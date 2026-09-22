function TranscribingState({ filename }) {
  return (
    <section className="work-card transcribing-card" id="file-panel" role="tabpanel" aria-live="polite">
      <div className="transcribing-orbit" aria-hidden="true">
        <div className="waveform-loader">
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((bar) => <span key={bar} />)}
        </div>
      </div>
      <p className="section-kicker">Local transcription</p>
      <h2>Transcribing…</h2>
      <p className="transcribing-filename">{filename}</p>
      <small>Your recording stays on this Mac while Oris Verba turns it into text.</small>
    </section>
  );
}

export default TranscribingState;
