import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient

import main
import scribe


class FakeStream:
    stopped = False
    closed = False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class DeferredThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        pass


class FakeSegment:
    start = 0.0
    end = 0.5
    text = " local test "
    avg_logprob = -0.1


class FakeInfo:
    language = "en"


class FakeModel:
    def transcribe(self, source, **_options):
        if isinstance(source, str):
            assert Path(source).exists()
            assert Path(source).suffix == ".wav"
        return iter([FakeSegment()]), FakeInfo()


class ApiTests(unittest.TestCase):
    def setUp(self):
        with main.state_lock:
            main.transcript_buffer.clear()
            main.is_running = False
            main.is_starting = False
            main.should_pause = False
            main.last_error = None
            main.active_stream = None
            main.capture_thread = None
        main.clear_audio_queue()
        self.client = TestClient(main.app)

    def test_microphone_start_pause_resume_stop(self):
        stream = FakeStream()
        with patch.object(main, "start_capture", return_value=stream), patch.object(
            main.threading, "Thread", DeferredThread
        ):
            started = self.client.post("/start")
            self.assertEqual(started.status_code, 200)
            self.assertTrue(started.json()["is_running"])

            paused = self.client.post("/pause")
            self.assertTrue(paused.json()["should_pause"])

            resumed = self.client.post("/resume")
            self.assertFalse(resumed.json()["should_pause"])

            stopped = self.client.post("/stop")
            self.assertFalse(stopped.json()["is_running"])

            main.run_loop(stream)
            self.assertTrue(stream.stopped)
            self.assertTrue(stream.closed)
            self.assertFalse(self.client.get("/status").json()["is_stopping"])

    def test_microphone_start_error_is_visible(self):
        with patch.object(main, "start_capture", side_effect=RuntimeError("no input device")):
            response = self.client.post("/start")

        self.assertEqual(response.status_code, 503)
        self.assertIn("no input device", response.json()["detail"])
        status = self.client.get("/status").json()
        self.assertFalse(status["is_running"])
        self.assertIn("no input device", status["error"])

    def test_microphone_segments_reach_transcript_endpoint(self):
        stream = FakeStream()
        chunks = iter([object(), None])

        def fake_get_audio_chunk(_should_continue):
            chunk = next(chunks)
            if chunk is None:
                with main.state_lock:
                    main.is_running = False
            return chunk

        with main.state_lock:
            main.is_running = True
            main.active_stream = stream

        with patch.object(main, "get_audio_chunk", side_effect=fake_get_audio_chunk), patch.object(
            main, "is_speech", return_value=True
        ), patch.object(
            main,
            "transcribe",
            return_value=[{"start": 0.0, "end": 1.0, "text": "hello", "confidence": -0.1, "needs_review": False}],
        ):
            main.run_loop(stream)

        response = self.client.get("/transcript")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["text"], "hello")

    def test_upload_returns_transcript_and_removes_temporary_files(self):
        observed = {}

        def fake_transcribe_file(input_path, work_dir, extension):
            observed["input"] = input_path
            observed["work_dir"] = work_dir
            self.assertTrue(input_path.exists())
            self.assertEqual(extension, ".mp3")
            return {"text": "hello", "language": "en", "segments": []}

        with patch.object(main, "transcribe_file", side_effect=fake_transcribe_file):
            response = self.client.post(
                "/transcribe-file",
                files={"file": ("sample.mp3", b"audio bytes", "audio/mpeg")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "hello")
        self.assertFalse(observed["input"].exists())
        self.assertFalse(observed["work_dir"].exists())

    def test_upload_failure_still_removes_temporary_files(self):
        observed = {}

        def failing_transcription(input_path, work_dir, _extension):
            observed["input"] = input_path
            observed["work_dir"] = work_dir
            raise RuntimeError("test failure")

        with patch.object(main, "transcribe_file", side_effect=failing_transcription):
            response = self.client.post(
                "/transcribe-file",
                files={"file": ("sample.wav", b"audio bytes", "audio/wav")},
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(observed["input"].exists())
        self.assertFalse(observed["work_dir"].exists())

    def test_unsupported_extension_is_rejected(self):
        response = self.client.post(
            "/transcribe-file",
            files={"file": ("notes.txt", b"not audio", "text/plain")},
        )
        self.assertEqual(response.status_code, 415)
        self.assertIn("Unsupported file type", response.json()["detail"])


class MediaDecodeTests(unittest.TestCase):
    @staticmethod
    def write_tone(path):
        sample_rate = 16000
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            frames = bytearray()
            for index in range(sample_rate // 2):
                sample = int(4000 * math.sin(2 * math.pi * 440 * index / sample_rate))
                frames.extend(struct.pack("<h", sample))
            output.writeframes(frames)

    def test_wav_mp3_and_m4a_decode_through_shared_transcriber(self):
        ffmpeg = shutil.which("ffmpeg")
        self.assertIsNotNone(ffmpeg, "FFmpeg is required for the media format test")

        with tempfile.TemporaryDirectory() as source_dir_name:
            source_dir = Path(source_dir_name)
            wav_path = source_dir / "tone.wav"
            self.write_tone(wav_path)

            media_paths = [(wav_path, ".wav")]
            for extension in (".mp3", ".m4a"):
                output_path = source_dir / f"tone{extension}"
                subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(wav_path),
                        str(output_path),
                    ],
                    check=True,
                )
                media_paths.append((output_path, extension))

            with patch.object(scribe, "get_model", return_value=FakeModel()):
                for source_path, extension in media_paths:
                    with self.subTest(extension=extension), tempfile.TemporaryDirectory() as work_dir_name:
                        result = scribe.transcribe_file(
                            source_path,
                            Path(work_dir_name),
                            extension,
                        )
                        self.assertEqual(result["text"], "local test")
                        self.assertEqual(result["language"], "en")
                        self.assertEqual(len(result["segments"]), 1)
                        self.assertFalse(result["segments"][0]["needs_review"])

    def test_missing_ffmpeg_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as work_dir_name, patch.object(
            scribe.shutil, "which", return_value=None
        ):
            with self.assertRaisesRegex(scribe.FFmpegUnavailableError, "brew install ffmpeg"):
                scribe.transcribe_file(
                    Path(work_dir_name) / "input.mp3",
                    Path(work_dir_name),
                    ".mp3",
                )


if __name__ == "__main__":
    unittest.main()
