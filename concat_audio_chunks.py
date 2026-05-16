"""
Concatenate chunk audio files into a single master track.

Examples:
  python concat_audio_chunks.py --input-dir "E:\\Inceptal\\vox\\overview v1 05.2026 output" --output "E:\\Inceptal\\vox\\overview v1 05.2026 master.wav"
  python concat_audio_chunks.py --input-dir "E:\\Inceptal\\vox\\overview v1 05.2026 output" --output "E:\\Inceptal\\vox\\overview v1 05.2026 master.mp3" --gap-ms 150
"""

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


def natural_key(path: Path):
    parts = re.split(r"(\d+)", path.stem.lower())
    out = []
    for p in parts:
        out.append(int(p) if p.isdigit() else p)
    return out


def main():
    parser = argparse.ArgumentParser(description="Concatenate chunk audio files into one master audio file")
    parser.add_argument("--input-dir", required=True, help="Folder containing chunk audio files")
    parser.add_argument("--output", required=True, help="Output file path (.wav, .mp3, .ogg, .m4a)")
    parser.add_argument("--pattern", default="*.mp3", help="Glob pattern for chunk files (default: *.mp3)")
    parser.add_argument("--gap-ms", type=int, default=120, help="Silence gap inserted between chunks (ms)")
    parser.add_argument("--sample-rate", type=int, default=48000, help="Target sample rate")
    args = parser.parse_args()

    in_dir = Path(args.input_dir).resolve()
    out_path = Path(args.output).resolve()
    if not in_dir.exists():
        raise FileNotFoundError(f"Input dir not found: {in_dir}")

    files = sorted([p for p in in_dir.glob(args.pattern) if p.is_file()], key=natural_key)
    if not files:
        raise FileNotFoundError(f"No files found in {in_dir} matching pattern {args.pattern}")

    gap_samples = int(max(0, args.gap_ms) * args.sample_rate / 1000)
    gap = np.zeros(gap_samples, dtype=np.float32)

    chunks = []
    print(f"Reading {len(files)} file(s) from: {in_dir}")
    for i, f in enumerate(files, start=1):
        audio, _ = librosa.load(str(f), sr=args.sample_rate, mono=True)
        chunks.append(audio.astype(np.float32))
        if i < len(files) and gap_samples > 0:
            chunks.append(gap)
        print(f"[{i:03d}/{len(files):03d}] {f.name} ({len(audio)} samples)")

    merged = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ext = out_path.suffix.lower()
    if ext == ".wav":
        sf.write(str(out_path), merged, args.sample_rate)
    else:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(out_path.parent)) as tmp:
            tmp_wav = Path(tmp.name)
        try:
            sf.write(str(tmp_wav), merged, args.sample_rate)
            ffmpeg_cmd = ["ffmpeg", "-y", "-i", str(tmp_wav), str(out_path)]
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
        finally:
            if tmp_wav.exists():
                os.unlink(tmp_wav)

    duration_sec = len(merged) / float(args.sample_rate)
    print(f"Saved: {out_path}")
    print(f"Duration: {duration_sec:.2f} sec")


if __name__ == "__main__":
    main()

