import { useCallback, useEffect, useRef, useState } from "react";
import FileUploader from "../components/FileUploader";
import Header from "../components/Header";
import LiveControls from "../components/LiveControls";
import ModeSelector from "../components/ModeSelector";
import TranscriptEditor from "../components/TranscriptEditor";
import TranscribingState from "../components/TranscribingState";

const API_BASE = "http://localhost:8000";
const ACCEPTED_EXTENSIONS = ".wav,.mp3,.m4a,.mp4,.flac,.ogg,.webm";
const MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024;

const initialLiveStatus = {
  is_running: false,
  is_starting: false,
  is_stopping: false,
  should_pause: false,
  transcript_count: 0,
  error: null,
};

async function readApiResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data;
}

function Home() {
  const [mode, setMode] = useState("live");
  const [segments, setSegments] = useState([]);
  const [liveStatus, setLiveStatus] = useState(initialLiveStatus);
  const [liveError, setLiveError] = useState("");
  const [liveBusy, setLiveBusy] = useState(false);
  const [livePollingActive, setLivePollingActive] = useState(false);

  const [selectedFile, setSelectedFile] = useState(null);
  const [fileStatus, setFileStatus] = useState("idle");
  const [fileError, setFileError] = useState("");
  const [fileTranscript, setFileTranscript] = useState("");
  const [fileResult, setFileResult] = useState(null);
  const [fileProgress, setFileProgress] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [copyLabel, setCopyLabel] = useState("Copy Transcript");
  const fileInputRef = useRef(null);
  const liveActionVersionRef = useRef(0);
  const progressTimerRef = useRef(null);
  const fileRequestRef = useRef(null);
  const fileJobIdRef = useRef(null);

  const stopFileProgressPolling = useCallback(() => {
    if (progressTimerRef.current) {
      window.clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
  }, []);

  useEffect(() => () => {
    stopFileProgressPolling();
    fileRequestRef.current?.abort();
  }, [stopFileProgressPolling]);

  const updateLiveStatus = useCallback(async (requestVersion = liveActionVersionRef.current) => {
    const statusResponse = await fetch(`${API_BASE}/status`);
    const statusData = await readApiResponse(statusResponse);
    if (requestVersion === liveActionVersionRef.current) {
      setLiveStatus(statusData);
      setLiveError(statusData.error || "");
    }
    return statusData;
  }, []);

  const updateLiveTranscript = useCallback(async (requestVersion = liveActionVersionRef.current) => {
    const transcriptResponse = await fetch(`${API_BASE}/transcript`);
    const transcriptData = await readApiResponse(transcriptResponse);
    if (requestVersion === liveActionVersionRef.current) {
      setSegments(transcriptData);
    }
    return transcriptData;
  }, []);

  useEffect(() => {
    let cancelled = false;

    const checkInitialStatus = async () => {
      const requestVersion = liveActionVersionRef.current;
      try {
        const statusData = await updateLiveStatus(requestVersion);
        if (requestVersion === liveActionVersionRef.current && statusData.is_running) {
          setLivePollingActive(true);
        }
      } catch (error) {
        if (!cancelled && requestVersion === liveActionVersionRef.current) {
          setLiveError(`Cannot reach the backend: ${error.message}`);
        }
      }
    };

    checkInitialStatus();
    return () => {
      cancelled = true;
    };
  }, [updateLiveStatus]);

  useEffect(() => {
    if (!livePollingActive) return undefined;

    let cancelled = false;
    const poll = async () => {
      const requestVersion = liveActionVersionRef.current;
      try {
        const [statusData] = await Promise.all([
          updateLiveStatus(requestVersion),
          updateLiveTranscript(requestVersion),
        ]);
        if (requestVersion === liveActionVersionRef.current && !statusData.is_running) {
          setLivePollingActive(false);
        }
      } catch (error) {
        if (!cancelled && requestVersion === liveActionVersionRef.current) {
          setLiveError(`Cannot reach the backend: ${error.message}`);
        }
      }
    };

    poll();
    const interval = window.setInterval(poll, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [livePollingActive, updateLiveStatus, updateLiveTranscript]);

  const runLiveAction = async (action) => {
    liveActionVersionRef.current += 1;
    setLiveBusy(true);
    setLiveError("");
    try {
      const response = await fetch(`${API_BASE}/${action}`, { method: "POST" });
      const data = await readApiResponse(response);
      setLiveStatus(data);
      setLiveError(data.error || "");
      if (action === "start") {
        setLivePollingActive(true);
      } else if (action === "stop") {
        setLivePollingActive(false);
        await updateLiveTranscript();
      }
    } catch (error) {
      setLiveError(error.message);
      try {
        const statusData = await updateLiveStatus();
        setLivePollingActive(statusData.is_running);
      } catch {
        // Keep the more useful action error visible.
      }
    } finally {
      setLiveBusy(false);
    }
  };

  const chooseFile = (file) => {
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      setSelectedFile(null);
      setFileStatus("error");
      setFileError("File is too large. The local limit is 2 GiB.");
      setFileTranscript("");
      setFileResult(null);
      setFileProgress(null);
      return;
    }
    const extension = `.${file.name.split(".").pop()?.toLowerCase()}`;
    if (!ACCEPTED_EXTENSIONS.split(",").includes(extension)) {
      setSelectedFile(null);
      setFileStatus("error");
      setFileError("Unsupported file type. Choose WAV, MP3, M4A, MP4, FLAC, OGG, or WebM.");
      setFileTranscript("");
      setFileResult(null);
      setFileProgress(null);
      return;
    }
    setSelectedFile(file);
    setFileStatus("ready");
    setFileError("");
    setFileTranscript("");
    setFileResult(null);
    setFileProgress(null);
    setCopyLabel("Copy Transcript");
  };

  const transcribeSelectedFile = () => {
    if (!selectedFile || fileRequestRef.current) return;

    setFileStatus("uploading");
    setFileError("");
    setFileTranscript("");
    setFileResult(null);
    setFileProgress({ status: "uploading", percent: null });

    const jobId = window.crypto.randomUUID();
    fileJobIdRef.current = jobId;

    const pollProgress = async () => {
      try {
        const response = await fetch(`${API_BASE}/transcribe-file/progress/${jobId}`);
        if (response.status === 404) return;
        const progress = await readApiResponse(response);
        if (fileJobIdRef.current !== jobId) return;
        setFileProgress(progress);
        if (["preparing", "transcribing", "diarizing"].includes(progress.status)) {
          setFileStatus(progress.status);
        }
        if (progress.status === "error" && progress.error) {
          setFileStatus("error");
          setFileError(progress.error);
          stopFileProgressPolling();
        }
      } catch {
        // The upload request reports connection failures with a clearer message.
      }
    };

    stopFileProgressPolling();
    progressTimerRef.current = window.setInterval(pollProgress, 500);
    pollProgress();

    const formData = new FormData();
    formData.append("file", selectedFile);
    const request = new XMLHttpRequest();
    fileRequestRef.current = request;
    request.open("POST", `${API_BASE}/transcribe-file?job_id=${encodeURIComponent(jobId)}`);
    request.timeout = 0;
    request.upload.onprogress = (event) => {
      if (fileJobIdRef.current !== jobId || !event.lengthComputable || event.total <= 0) return;
      const stagePercent = Math.min(100, Math.max(0, event.loaded / event.total * 100));
      setFileProgress({
        status: "uploading",
        percent: Math.min(9.9, stagePercent / 10),
        stage_percent: stagePercent,
        uploaded_bytes: event.loaded,
        total_bytes: event.total,
      });
    };
    request.upload.onload = () => {
      if (fileJobIdRef.current !== jobId) return;
      setFileStatus("preparing");
      setFileProgress({ status: "preparing", percent: null, stage_percent: null });
    };
    request.onload = () => {
      if (fileJobIdRef.current !== jobId) return;
      stopFileProgressPolling();
      fileRequestRef.current = null;
      let data = {};
      try {
        data = JSON.parse(request.responseText || "{}");
      } catch {
        data = {};
      }

      if (request.status < 200 || request.status >= 300) {
        setFileStatus("error");
        setFileError(data.detail || `Transcription failed (${request.status}).`);
        return;
      }

      setFileResult(data);
      setFileTranscript(data.text || "");
      setFileProgress({
        status: "complete",
        percent: 100,
        processed_seconds: data.duration,
        duration_seconds: data.duration,
      });
      setFileStatus("complete");
    };
    request.onerror = () => {
      if (fileJobIdRef.current !== jobId) return;
      stopFileProgressPolling();
      fileRequestRef.current = null;
      setFileStatus("error");
      setFileError("Could not reach the backend. Confirm it is running on port 8000.");
    };
    request.onabort = () => {
      if (fileJobIdRef.current !== jobId) return;
      stopFileProgressPolling();
      fileRequestRef.current = null;
      setFileStatus("error");
      setFileError("Transcription was interrupted. Retry or choose another file.");
    };
    request.send(formData);
  };

  const resetFile = () => {
    setSelectedFile(null);
    setFileStatus("idle");
    setFileError("");
    setFileTranscript("");
    setFileResult(null);
    setFileProgress(null);
    setCopyLabel("Copy Transcript");
    stopFileProgressPolling();
    fileJobIdRef.current = null;
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const copyTranscript = async () => {
    try {
      await navigator.clipboard.writeText(fileTranscript);
      setCopyLabel("Copied");
      window.setTimeout(() => setCopyLabel("Copy Transcript"), 1500);
    } catch {
      setFileError("Clipboard access was denied. Select the transcript and copy it manually.");
    }
  };

  const downloadTranscript = () => {
    const blob = new Blob([fileTranscript], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const baseName = (fileResult?.filename || "transcript").replace(/\.[^.]+$/, "");
    link.href = url;
    link.download = `${baseName}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const isFileBusy = ["uploading", "preparing", "transcribing", "diarizing"].includes(fileStatus);

  return (
    <main className="app-shell">
      <div className="app-frame">
        <Header />
        <ModeSelector mode={mode} onChange={setMode} />

        <div className="workspace">
          {mode === "live" ? (
            <LiveControls
              liveStatus={liveStatus}
              liveBusy={liveBusy}
              liveError={liveError}
              segments={segments}
              onAction={runLiveAction}
            />
          ) : isFileBusy ? (
            <TranscribingState
              filename={selectedFile?.name}
              fileSize={selectedFile?.size}
              progress={fileProgress}
            />
          ) : fileResult && fileStatus === "complete" ? (
            <TranscriptEditor
              result={fileResult}
              transcript={fileTranscript}
              copyLabel={copyLabel}
              error={fileError}
              warning={fileResult.diarization_warning}
              onTranscriptChange={setFileTranscript}
              onCopy={copyTranscript}
              onDownload={downloadTranscript}
              onReset={resetFile}
            />
          ) : (
            <FileUploader
              selectedFile={selectedFile}
              fileStatus={fileStatus}
              fileError={fileError}
              isDragging={isDragging}
              fileInputRef={fileInputRef}
              onChooseFile={chooseFile}
              onDraggingChange={setIsDragging}
              onTranscribe={transcribeSelectedFile}
              onReset={resetFile}
              acceptedExtensions={ACCEPTED_EXTENSIONS}
            />
          )}
        </div>
      </div>
    </main>
  );
}

export default Home;
