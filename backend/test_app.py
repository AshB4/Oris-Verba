import math
import numpy as np
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient

import audio_capture
import main
import diarization
import scribe
import vad


class FakeStream:
    def __init__(self):
        self.stopped = False
        self.closed = False
        self.stop_calls = 0
        self.close_calls = 0

    def stop(self):
        self.stop_calls += 1
        self.stopped = True

    def close(self):
        self.close_calls += 1
        self.closed = True


class DeferredThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        pass

    def join(self):
        pass


class FakeSegment:
    start = 0.0
    end = 0.5
    text = " local test "
    avg_logprob = -0.1


class FakeInfo:
    language = "en"
    duration = 2.0


class FakeModel:
    def transcribe(self, source, **_options):
        self.options = _options
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
        with main.file_job_lock:
            main.file_jobs.clear()
        self.client = TestClient(main.app)

    def test_app_startup_does_not_initialize_sounddevice(self):
        self.assertNotIn("sounddevice", sys.modules)
        self.assertIsNone(main.active_stream)

    def test_status_and_transcript_polling_do_not_open_microphone(self):
        with patch.object(main, "start_capture") as start_capture:
            status = self.client.get("/status")
            transcript = self.client.get("/transcript")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(transcript.status_code, 200)
        start_capture.assert_not_called()
        self.assertIsNone(main.active_stream)

    def test_live_transcript_clear_is_rejected_until_capture_finishes(self):
        segment = {
            "start": 0.0,
            "end": 1.0,
            "text": "keep this",
            "confidence": -0.1,
            "needs_review": False,
        }
        with main.state_lock:
            main.transcript_buffer.append(segment)
            main.is_running = True

        rejected = self.client.delete("/transcript")
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(self.client.get("/transcript").json(), [segment])

        with main.state_lock:
            main.is_running = False
            main.active_stream = FakeStream()

        still_stopping = self.client.delete("/transcript")
        self.assertEqual(still_stopping.status_code, 409)
        self.assertEqual(self.client.get("/transcript").json(), [segment])

        with main.state_lock:
            main.active_stream = None

        cleared = self.client.delete("/transcript")
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["status"], "cleared")
        self.assertEqual(cleared.json()["transcript_count"], 0)
        self.assertEqual(self.client.get("/transcript").json(), [])

    def test_microphone_start_pause_resume_stop(self):
        stream = FakeStream()
        with patch.object(main, "start_capture", return_value=stream) as start_capture, patch.object(
            main.threading, "Thread", DeferredThread
        ):
            started = self.client.post("/start")
            self.assertEqual(started.status_code, 200)
            self.assertTrue(started.json()["is_running"])
            start_capture.assert_called_once_with()

            paused = self.client.post("/pause")
            self.assertTrue(paused.json()["should_pause"])

            resumed = self.client.post("/resume")
            self.assertFalse(resumed.json()["should_pause"])

            with main.state_lock:
                main.transcript_buffer.append(
                    {"start": 0.0, "end": 1.0, "text": "keep me", "confidence": -0.1, "needs_review": False}
                )

            stopped = self.client.post("/stop")
            self.assertFalse(stopped.json()["is_running"])
            self.assertFalse(stopped.json()["is_stopping"])
            self.assertTrue(stream.stopped)
            self.assertTrue(stream.closed)
            self.assertEqual(stream.stop_calls, 1)
            self.assertEqual(stream.close_calls, 1)
            self.assertIsNone(main.active_stream)
            self.assertEqual(self.client.get("/transcript").json()[0]["text"], "keep me")

            main.run_loop(stream)
            self.assertTrue(stream.stopped)
            self.assertTrue(stream.closed)
            self.assertEqual(stream.stop_calls, 1)
            self.assertEqual(stream.close_calls, 1)
            self.assertFalse(self.client.get("/status").json()["is_stopping"])

            stopped_again = self.client.post("/stop")
            self.assertEqual(stopped_again.status_code, 200)
            self.assertEqual(stream.stop_calls, 1)
            self.assertEqual(stream.close_calls, 1)

    def test_microphone_cleanup_is_idempotent(self):
        stream = FakeStream()

        audio_capture.stop_capture(stream)
        audio_capture.stop_capture(stream)

        self.assertEqual(stream.stop_calls, 1)
        self.assertEqual(stream.close_calls, 1)

    def test_final_buffered_speech_is_processed_during_shutdown(self):
        stream = FakeStream()
        final_segment = {
            "start": 0.0,
            "end": 0.5,
            "text": "hello hello",
            "confidence": -0.1,
            "needs_review": False,
        }
        with patch.object(main, "start_capture", return_value=stream), patch.object(
            main, "is_speech", return_value=True
        ), patch.object(
            main, "transcribe", return_value=[final_segment]
        ) as transcribe:
            self.assertEqual(self.client.post("/start").status_code, 200)
            audio_capture.audio_queue.put(np.ones((480, 1), dtype=np.float32))
            stopped = self.client.post("/stop")

        self.assertEqual(stopped.status_code, 200)
        transcribe.assert_called_once()
        self.assertEqual(self.client.get("/transcript").json(), [final_segment])
        self.assertIsNone(main.active_stream)
        self.assertEqual(stream.stop_calls, 1)
        self.assertEqual(stream.close_calls, 1)

    def test_start_works_again_after_completed_stop(self):
        first_stream = FakeStream()
        second_stream = FakeStream()
        with patch.object(
            main,
            "start_capture",
            side_effect=[first_stream, second_stream],
        ), patch.object(main.threading, "Thread", DeferredThread):
            self.assertEqual(self.client.post("/start").status_code, 200)
            self.assertEqual(self.client.post("/stop").status_code, 200)
            restarted = self.client.post("/start")
            self.assertEqual(restarted.status_code, 200)
            self.assertTrue(restarted.json()["is_running"])
            self.assertIs(main.active_stream, second_stream)
            self.assertEqual(self.client.post("/stop").status_code, 200)

        self.assertEqual(first_stream.close_calls, 1)
        self.assertEqual(second_stream.close_calls, 1)

    def test_live_session_normalizes_and_propagates_vocabulary_hints(self):
        stream = FakeStream()
        with patch.object(main, "start_capture", return_value=stream), patch.object(
            main.threading, "Thread", DeferredThread
        ):
            started = self.client.post(
                "/start",
                params={"vocabulary_hints": "  Siobhan   NASA  "},
            )

        self.assertEqual(started.status_code, 200)
        self.assertEqual(main.capture_thread.args, (stream, "Siobhan NASA"))

        chunk = object()
        chunks = iter([chunk, None])

        def fake_get_audio_chunk(_should_continue, _should_flush=None):
            item = next(chunks)
            if item is None:
                with main.state_lock:
                    main.is_running = False
            return item

        with patch.object(main, "get_audio_chunk", side_effect=fake_get_audio_chunk), patch.object(
            main, "is_speech", return_value=True
        ), patch.object(main, "transcribe", return_value=[]) as transcribe:
            main.run_loop(stream, main.capture_thread.args[1])

        transcribe.assert_called_once_with(chunk, hotwords="Siobhan NASA")

    def test_vocabulary_hints_are_bounded(self):
        too_long = "x" * (main.MAX_VOCABULARY_HINTS_CHARS + 1)

        live = self.client.post("/start", params={"vocabulary_hints": too_long})
        uploaded = self.client.post(
            "/transcribe-file",
            params={"vocabulary_hints": too_long},
            files={"file": ("sample.wav", b"audio bytes", "audio/wav")},
        )

        self.assertEqual(live.status_code, 422)
        self.assertEqual(uploaded.status_code, 422)
        self.assertIn("500 characters or fewer", live.json()["detail"])
        self.assertIn("500 characters or fewer", uploaded.json()["detail"])

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

        def fake_get_audio_chunk(_should_continue, _should_flush=None):
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

    def test_live_chunks_receive_bounded_previous_transcript_context(self):
        stream = FakeStream()
        first_chunk = object()
        second_chunk = object()
        chunks = iter([first_chunk, second_chunk, None])
        first_words = [f"word{index}" for index in range(main.LIVE_CONTEXT_MAX_WORDS + 5)]

        def fake_get_audio_chunk(_should_continue, _should_flush=None):
            chunk = next(chunks)
            if chunk is None:
                with main.state_lock:
                    main.is_running = False
            return chunk

        with main.state_lock:
            main.is_running = True
            main.active_stream = stream

        first_segments = [
            {
                "start": 0.0,
                "end": 1.0,
                "text": " ".join(first_words),
                "confidence": -0.1,
                "needs_review": False,
            }
        ]
        second_segments = [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "continued",
                "confidence": -0.1,
                "needs_review": False,
            }
        ]
        with patch.object(main, "get_audio_chunk", side_effect=fake_get_audio_chunk), patch.object(
            main, "is_speech", return_value=True
        ), patch.object(
            main, "transcribe", side_effect=[first_segments, second_segments]
        ) as transcribe:
            main.run_loop(stream, "Siobhan")

        self.assertEqual(transcribe.call_args_list[0].args, (first_chunk,))
        self.assertEqual(transcribe.call_args_list[0].kwargs, {"hotwords": "Siobhan"})
        self.assertEqual(transcribe.call_args_list[1].args, (second_chunk,))
        self.assertEqual(
            transcribe.call_args_list[1].kwargs,
            {
                "hotwords": "Siobhan",
                "initial_prompt": " ".join(first_words[-main.LIVE_CONTEXT_MAX_WORDS :]),
            },
        )

    def test_vad_checks_a_single_complete_frame(self):
        frame_samples = int(0.03 * 16000)
        fake_vad = unittest.mock.Mock()
        fake_vad.is_speech.return_value = True

        with patch.object(vad, "vad", fake_vad):
            self.assertTrue(vad.is_speech(np.zeros(frame_samples, dtype=np.float32)))

        fake_vad.is_speech.assert_called_once()

    def test_upload_returns_transcript_and_removes_temporary_files(self):
        observed = {}

        def fake_transcribe_file(
            input_path,
            work_dir,
            extension,
            progress_callback=None,
            postprocess_callback=None,
        ):
            observed["input"] = input_path
            observed["work_dir"] = work_dir
            self.assertTrue(input_path.exists())
            self.assertEqual(extension, ".mp3")
            if progress_callback is not None:
                progress_callback(1.0, 2.0, "transcribing")
            return {"text": "hello", "language": "en", "segments": [], "duration": 2.0}

        with patch.object(main, "transcribe_file", side_effect=fake_transcribe_file):
            response = self.client.post(
                "/transcribe-file?job_id=progress-test",
                files={"file": ("sample.mp3", b"audio bytes", "audio/mpeg")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "hello")
        self.assertFalse(observed["input"].exists())
        self.assertFalse(observed["work_dir"].exists())
        progress = self.client.get("/transcribe-file/progress/progress-test")
        self.assertEqual(progress.status_code, 200)
        self.assertEqual(progress.json()["status"], "complete")
        self.assertEqual(progress.json()["percent"], 100.0)
        self.assertEqual(progress.json()["duration_seconds"], 2.0)

    def test_upload_failure_still_removes_temporary_files(self):
        observed = {}

        def failing_transcription(
            input_path,
            work_dir,
            _extension,
            progress_callback=None,
            postprocess_callback=None,
        ):
            observed["input"] = input_path
            observed["work_dir"] = work_dir
            raise RuntimeError("test failure")

        with patch.object(main, "transcribe_file", side_effect=failing_transcription):
            response = self.client.post(
                "/transcribe-file?job_id=failure-test",
                files={"file": ("sample.wav", b"audio bytes", "audio/wav")},
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(observed["input"].exists())
        self.assertFalse(observed["work_dir"].exists())
        progress = self.client.get("/transcribe-file/progress/failure-test").json()
        self.assertEqual(progress["status"], "error")
        self.assertIn("test failure", progress["error"])

    def test_unsupported_extension_is_rejected(self):
        response = self.client.post(
            "/transcribe-file",
            files={"file": ("notes.txt", b"not audio", "text/plain")},
        )
        self.assertEqual(response.status_code, 415)
        self.assertIn("Unsupported file type", response.json()["detail"])

    def test_oversized_upload_is_rejected_cleanly(self):
        with patch.object(main, "MAX_UPLOAD_BYTES", 4):
            response = self.client.post(
                "/transcribe-file?job_id=large-file-test",
                files={"file": ("sample.wav", b"12345", "audio/wav")},
            )

        self.assertEqual(response.status_code, 413)
        self.assertIn("2 GiB", response.json()["detail"])
        progress = self.client.get("/transcribe-file/progress/large-file-test").json()
        self.assertEqual(progress["status"], "error")

    def test_progress_percentage_uses_processed_media_time(self):
        main.update_transcription_progress("active-test", 75.0, 300.0, "transcribing")

        progress = self.client.get("/transcribe-file/progress/active-test")
        self.assertEqual(progress.status_code, 200)
        self.assertEqual(progress.json()["percent"], 30.0)
        self.assertEqual(progress.json()["stage_percent"], 25.0)
        self.assertEqual(progress.json()["processed_seconds"], 75.0)
        self.assertEqual(progress.json()["duration_seconds"], 300.0)
        self.assertEqual(progress.json()["progress_metric"], "source_media_time")

    def test_progress_is_monotonic_and_stays_below_complete(self):
        main.update_transcription_progress("monotonic-test", 80.0, 100.0, "transcribing")
        main.update_transcription_progress("monotonic-test", 40.0, 100.0, "transcribing")

        active = self.client.get("/transcribe-file/progress/monotonic-test").json()
        self.assertEqual(active["percent"], 74.0)
        self.assertEqual(active["stage_percent"], 80.0)
        self.assertEqual(active["processed_seconds"], 80.0)
        self.assertLess(active["percent"], 100.0)

        main.update_file_job(
            "monotonic-test",
            status="complete",
            percent=100.0,
            stage_percent=100.0,
        )
        complete = self.client.get("/transcribe-file/progress/monotonic-test").json()
        self.assertEqual(complete["percent"], 100.0)

    def test_finished_progress_jobs_expire_and_internal_timestamps_are_hidden(self):
        main.update_file_job("expired-test", status="complete", percent=100.0)
        snapshot = self.client.get("/transcribe-file/progress/expired-test")
        self.assertNotIn("created_at", snapshot.json())
        self.assertNotIn("updated_at", snapshot.json())

        with main.file_job_lock:
            main.file_jobs["expired-test"]["updated_at"] -= main.FILE_JOB_TTL_SECONDS + 1

        self.assertEqual(
            self.client.get("/transcribe-file/progress/expired-test").status_code,
            404,
        )

    def test_diarization_progress_uses_completed_chunks(self):
        main.update_diarization_progress("diarization-test", 31, 50)

        progress = self.client.get("/transcribe-file/progress/diarization-test").json()
        self.assertEqual(progress["status"], "diarizing")
        self.assertEqual(progress["percent"], 95.6)
        self.assertEqual(progress["stage_percent"], 62.0)
        self.assertEqual(progress["progress_metric"], "diarization_chunks")

    def test_upload_returns_speaker_labeled_transcript(self):
        def fake_transcribe_file(
            input_path,
            work_dir,
            extension,
            progress_callback=None,
            postprocess_callback=None,
        ):
            transcription = {
                "text": "Morning. We are ready.",
                "language": "en",
                "duration": 4.0,
                "segments": [
                    {"start": 0.0, "end": 1.5, "text": "Morning.", "confidence": -0.1, "needs_review": False},
                    {"start": 2.0, "end": 4.0, "text": "We are ready.", "confidence": -0.1, "needs_review": False},
                ],
            }
            return postprocess_callback(input_path, transcription)

        def fake_diarize(_audio_path, transcription, progress_callback=None):
            progress_callback(3, 4)
            return {
                **transcription,
                "text": "Speaker 1: Morning.\n\nSpeaker 2: We are ready.",
                "segments": [
                    {**transcription["segments"][0], "speaker": "Speaker 1"},
                    {**transcription["segments"][1], "speaker": "Speaker 2"},
                ],
                "speaker_count": 2,
                "speaker_turns": [],
            }

        with patch.object(main, "transcribe_file", side_effect=fake_transcribe_file), patch.object(
            main, "diarize_transcript", side_effect=fake_diarize
        ):
            response = self.client.post(
                "/transcribe-file?job_id=speakers-test&detect_speakers=true",
                files={"file": ("meeting.wav", b"audio bytes", "audio/wav")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["speaker_count"], 2)
        self.assertEqual(
            response.json()["text"],
            "Speaker 1: Morning.\n\nSpeaker 2: We are ready.",
        )
        progress = self.client.get("/transcribe-file/progress/speakers-test").json()
        self.assertEqual(progress["status"], "complete")
        self.assertEqual(progress["percent"], 100.0)

    def test_upload_skips_speaker_detection_when_disabled(self):
        plain_transcription = {
            "text": "No speaker labels here.",
            "language": "en",
            "duration": 3.0,
            "segments": [
                {
                    "start": 0.0,
                    "end": 3.0,
                    "text": "No speaker labels here.",
                    "confidence": -0.1,
                    "needs_review": False,
                }
            ],
        }

        def fake_transcribe_file(
            _input_path,
            _work_dir,
            _extension,
            progress_callback=None,
            postprocess_callback=None,
        ):
            self.assertIsNone(postprocess_callback)
            progress_callback(3.0, 3.0, "transcribing")
            return plain_transcription

        with patch.object(main, "transcribe_file", side_effect=fake_transcribe_file), patch.object(
            main, "diarize_transcript"
        ) as diarize:
            response = self.client.post(
                "/transcribe-file?job_id=no-speakers-test&detect_speakers=false",
                files={"file": ("meeting.wav", b"audio bytes", "audio/wav")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["text"], plain_transcription["text"])
        self.assertNotIn("speaker_count", response.json())
        self.assertNotIn("diarization_warning", response.json())
        diarize.assert_not_called()

        progress = self.client.get("/transcribe-file/progress/no-speakers-test").json()
        self.assertEqual(progress["status"], "complete")
        self.assertEqual(progress["percent"], 100.0)
        self.assertEqual(progress["progress_metric"], "complete")

    def test_upload_propagates_vocabulary_hints(self):
        observed = {}

        def fake_transcribe_file(
            _input_path,
            _work_dir,
            _extension,
            progress_callback=None,
            postprocess_callback=None,
            hotwords=None,
        ):
            observed["hotwords"] = hotwords
            self.assertIsNone(postprocess_callback)
            progress_callback(1.0, 1.0, "transcribing")
            return {"text": "Oris Verba", "language": "en", "segments": [], "duration": 1.0}

        with patch.object(main, "transcribe_file", side_effect=fake_transcribe_file):
            response = self.client.post(
                "/transcribe-file",
                params={
                    "job_id": "hinted-file-test",
                    "detect_speakers": "false",
                    "vocabulary_hints": "  Oris   Verba, CUDA  ",
                },
                files={"file": ("meeting.wav", b"audio bytes", "audio/wav")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(observed["hotwords"], "Oris Verba, CUDA")
        self.assertEqual(response.json()["text"], "Oris Verba")

    def test_diarization_failure_preserves_transcript(self):
        transcription = {
            "text": "The original transcript survives.",
            "language": "en",
            "duration": 5.0,
            "segments": [{"start": 0.0, "end": 5.0, "text": "The original transcript survives."}],
        }

        with patch.object(main, "diarize_transcript", side_effect=RuntimeError("model failed")):
            result = main.add_speaker_labels(Path("unused.wav"), transcription, "fallback-test")

        self.assertEqual(result["text"], transcription["text"])
        self.assertEqual(result["segments"], transcription["segments"])
        self.assertEqual(
            result["diarization_warning"],
            "Transcript completed, but speaker detection was unavailable.",
        )


class DiarizationAlignmentTests(unittest.TestCase):
    def test_speaker_labels_are_consistent_and_ordered_by_first_turn(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Morning."},
            {"start": 1.1, "end": 2.0, "text": "What did we decide?"},
            {"start": 2.1, "end": 3.0, "text": "We are waiting."},
            {"start": 3.1, "end": 4.0, "text": "Perfect."},
        ]
        turns = [
            {"start": 0.0, "end": 2.0, "speaker": 7},
            {"start": 2.0, "end": 3.0, "speaker": 2},
            {"start": 3.0, "end": 4.0, "speaker": 7},
        ]

        result = diarization.label_transcript_segments(segments, turns)

        self.assertEqual(result["speaker_count"], 2)
        self.assertEqual(
            [segment["speaker"] for segment in result["segments"]],
            ["Speaker 1", "Speaker 1", "Speaker 2", "Speaker 1"],
        )
        self.assertEqual(
            result["text"],
            "Speaker 1: Morning. What did we decide?\n\n"
            "Speaker 2: We are waiting.\n\n"
            "Speaker 1: Perfect.",
        )

    def test_alignment_handles_one_hour_timeline_without_expanding_audio(self):
        result = diarization.label_transcript_segments(
            [{"start": 3598.0, "end": 3600.0, "text": "Final note."}],
            [{"start": 3590.0, "end": 3600.0, "speaker": 4}],
        )

        self.assertEqual(result["text"], "Speaker 1: Final note.")


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

    def test_progress_reports_processed_audio_time(self):
        events = []
        with tempfile.TemporaryDirectory() as work_dir_name:
            work_dir = Path(work_dir_name)
            wav_path = work_dir / "tone.wav"
            self.write_tone(wav_path)

            with patch.object(scribe, "get_model", return_value=FakeModel()):
                scribe.transcribe_file(
                    wav_path,
                    work_dir,
                    ".wav",
                    progress_callback=lambda processed, duration, stage: events.append(
                        (processed, duration, stage)
                    ),
                )

        self.assertEqual(events[0], (0.0, 0.0, "preparing"))
        self.assertEqual(events[1], (0.0, 2.0, "transcribing"))
        self.assertEqual(events[-1], (0.5, 2.0, "transcribing"))

    def test_hotwords_reach_faster_whisper_and_empty_hints_keep_defaults(self):
        hinted_model = FakeModel()
        with patch.object(scribe, "get_model", return_value=hinted_model):
            scribe.transcribe(np.zeros(1600, dtype=np.float32), hotwords="Siobhan NASA")

        self.assertEqual(hinted_model.options["hotwords"], "Siobhan NASA")

        default_model = FakeModel()
        with patch.object(scribe, "get_model", return_value=default_model):
            scribe.transcribe(np.zeros(1600, dtype=np.float32), hotwords=None)

        self.assertNotIn("hotwords", default_model.options)

    def test_live_context_reaches_faster_whisper_as_initial_prompt(self):
        model = FakeModel()
        with patch.object(scribe, "get_model", return_value=model):
            scribe.transcribe(
                np.zeros(1600, dtype=np.float32),
                initial_prompt="previous live words",
            )

        self.assertEqual(model.options["initial_prompt"], "previous live words")

    def test_vad_restored_timestamps_report_original_media_coverage(self):
        class VadInfo:
            language = "en"
            duration = 120.0
            duration_after_vad = 20.0

        class RestoredSegment:
            start = 88.0
            end = 90.0
            text = " mapped back to the source timeline "
            avg_logprob = -0.1

        class VadModel:
            def transcribe(self, _source, **options):
                self.assert_vad = options["vad_filter"]
                return iter([RestoredSegment()]), VadInfo()

        events = []
        model = VadModel()
        with patch.object(scribe, "get_model", return_value=model):
            scribe._transcribe_source(
                "unused.wav",
                language=None,
                vad_filter=True,
                progress_callback=lambda processed, duration, stage: events.append(
                    (processed, duration, stage)
                ),
            )

        self.assertTrue(model.assert_vad)
        self.assertEqual(events[-1], (90.0, 120.0, "transcribing"))


if __name__ == "__main__":
    unittest.main()
