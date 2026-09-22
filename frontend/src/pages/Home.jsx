import { useCallback, useEffect, useRef, useState } from "react";
import FileUploader from "../components/FileUploader";
import Header from "../components/Header";
import LiveControls from "../components/LiveControls";
import ModeSelector from "../components/ModeSelector";
import TranscriptEditor from "../components/TranscriptEditor";
import TranscribingState from "../components/TranscribingState";

const API_BASE = "http://localhost:8000";
const ACCEPTED_EXTENSIONS = ".wav,.mp3,.m4a,.mp4,.flac,.ogg,.webm";

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

  const [selectedFile, setSelectedFile] = useState(null);
  const [fileStatus, setFileStatus] = useState("idle");
  const [fileError, setFileError] = useState("");
  const [fileTranscript, setFileTranscript] = useState("");
  const [fileResult, setFileResult] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [copyLabel, setCopyLabel] = useState("Copy Transcript");
  const fileInputRef = useRef(null);

  const updateLiveData = useCallback(async () => {
    const [statusResponse, transcriptResponse] = await Promise.all([
      fetch(`${API_BASE}/status`),
      fetch(`${API_BASE}/transcript`),
    ]);
    const statusData = await readApiResponse(statusResponse);
    const transcriptData = await readApiResponse(transcriptResponse);
    setLiveStatus(statusData);
    setSegments(transcriptData);
    setLiveError(statusData.error || "");
  }, []);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        await updateLiveData();
      } catch (error) {
        if (!cancelled) {
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
  }, [updateLiveData]);

  const runLiveAction = async (action) => {
    setLiveBusy(true);
    setLiveError("");
    try {
      const response = await fetch(`${API_BASE}/${action}`, { method: "POST" });
      const data = await readApiResponse(response);
      setLiveStatus(data);
      await updateLiveData();
    } catch (error) {
      setLiveError(error.message);
      try {
        await updateLiveData();
      } catch {
        // Keep the more useful action error visible.
      }
    } finally {
      setLiveBusy(false);
    }
  };

  const chooseFile = (file) => {
    if (!file) return;
    const extension = `.${file.name.split(".").pop()?.toLowerCase()}`;
    if (!ACCEPTED_EXTENSIONS.split(",").includes(extension)) {
      setSelectedFile(null);
      setFileStatus("error");
      setFileError("Unsupported file type. Choose WAV, MP3, M4A, MP4, FLAC, OGG, or WebM.");
      setFileTranscript("");
      setFileResult(null);
      return;
    }
    setSelectedFile(file);
    setFileStatus("ready");
    setFileError("");
    setFileTranscript("");
    setFileResult(null);
    setCopyLabel("Copy Transcript");
  };

  const transcribeSelectedFile = () => {
    if (!selectedFile) return;

    setFileStatus("uploading");
    setFileError("");
    setFileTranscript("");
    setFileResult(null);

    const formData = new FormData();
    formData.append("file", selectedFile);
    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE}/transcribe-file`);
    request.upload.onload = () => setFileStatus("transcribing");
    request.onload = () => {
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
      setFileStatus("complete");
    };
    request.onerror = () => {
      setFileStatus("error");
      setFileError("Could not reach the backend. Confirm it is running on port 8000.");
    };
    request.send(formData);
  };

  const resetFile = () => {
    setSelectedFile(null);
    setFileStatus("idle");
    setFileError("");
    setFileTranscript("");
    setFileResult(null);
    setCopyLabel("Copy Transcript");
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

  const isFileBusy = fileStatus === "uploading" || fileStatus === "transcribing";

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
            <TranscribingState filename={selectedFile?.name} />
          ) : fileResult && fileStatus === "complete" ? (
            <TranscriptEditor
              result={fileResult}
              transcript={fileTranscript}
              copyLabel={copyLabel}
              error={fileError}
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
