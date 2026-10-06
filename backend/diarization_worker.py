import argparse
import json
import wave

import numpy as np
import sherpa_onnx


def emit(prefix, payload):
    print(f"{prefix} {json.dumps(payload, separators=(',', ':'))}", flush=True)


def load_wave(path):
    with wave.open(path, "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 16000:
            raise RuntimeError("Speaker detection requires 16 kHz, 16-bit mono WAV audio.")
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    return samples.astype(np.float32) / 32768.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--segmentation-model", required=True)
    parser.add_argument("--embedding-model", required=True)
    args = parser.parse_args()

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=args.segmentation_model,
                window_shift_ratio=0.1,
            ),
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=args.embedding_model),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.5),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RuntimeError("Speaker detection model configuration is invalid.")

    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    samples = load_wave(args.audio)

    def progress(processed_chunks, total_chunks):
        emit(
            "ORIS_PROGRESS",
            {
                "processed_chunks": processed_chunks,
                "total_chunks": total_chunks,
            },
        )
        return 0

    result = diarizer.process(samples, callback=progress).sort_by_start_time()
    emit(
        "ORIS_RESULT",
        {
            "turns": [
                {
                    "start": float(turn.start),
                    "end": float(turn.end),
                    "speaker": int(turn.speaker),
                }
                for turn in result
            ]
        },
    )


if __name__ == "__main__":
    main()
