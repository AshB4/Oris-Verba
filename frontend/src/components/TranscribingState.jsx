function formatFileSize(bytes) {
  if (!Number.isFinite(bytes)) return null;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  const rounded = Math.round(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainingSeconds = rounded % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`
    : `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

function TranscribingState({ filename, fileSize, progress }) {
  const percentage = Number.isFinite(progress?.percent) ? progress.percent : null;
  const stagePercentage = Number.isFinite(progress?.stage_percent) ? progress.stage_percent : null;
  const duration = formatDuration(progress?.duration_seconds);
  const processed = formatDuration(progress?.processed_seconds);
  const status = progress?.status || "preparing";
  const stageLabels = {
    uploading: "Uploading file",
    preparing: "Preparing audio and loading model",
    transcribing: "Transcribing audio",
    diarizing: "Identifying speakers",
    complete: "Complete",
  };
  const stageLabel = stageLabels[status] || "Preparing audio and loading model";
  let detailLabel = stageLabel;
  if (status === "uploading" && stagePercentage !== null) {
    detailLabel = `${stageLabel} · ${Math.round(stagePercentage)}% of file`;
  } else if (status === "transcribing" && processed && duration) {
    detailLabel = `${stageLabel} · ${processed} / ${duration} processed`;
  } else if (status === "diarizing" && stagePercentage !== null) {
    detailLabel = `${stageLabel} · ${Math.round(stagePercentage)}%`;
  }
  const ariaValueText = percentage === null
    ? `${stageLabel}, progress unavailable`
    : `${detailLabel}, ${Math.round(percentage)}% overall`;

  return (
    <section className="work-card transcribing-card" id="file-panel" role="tabpanel" aria-live="polite">
      <div className="transcribing-orbit" aria-hidden="true">
        <div className="waveform-loader">
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((bar) => <span key={bar} />)}
        </div>
      </div>
      <p className="section-kicker">Local transcription</p>
      <h2>{stageLabel}</h2>
      <p className="transcribing-filename">{filename}</p>
      <div className="processing-details">
        {formatFileSize(fileSize) && <span>{formatFileSize(fileSize)}</span>}
        {duration && <span>{duration} duration</span>}
      </div>
      <div className="progress-block">
        <div className="progress-copy">
          <span>{detailLabel}</span>
          {percentage !== null && <strong>{Math.round(percentage)}% overall</strong>}
        </div>
        <div
          className={`progress-track ${percentage === null ? "is-waiting" : ""}`}
          role="progressbar"
          aria-label="File transcription progress"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow={percentage === null ? undefined : Math.round(percentage)}
          aria-valuetext={ariaValueText}
        >
          <span style={{ width: `${percentage ?? 0}%` }} />
        </div>
      </div>
      <small>Your recording stays on this computer while Oris Verba turns it into text.</small>
    </section>
  );
}

export default TranscribingState;
