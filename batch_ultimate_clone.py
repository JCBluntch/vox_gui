"""
Batch cloning for VoxCPM2.

This script can:
1) Split a long source text into numbered chunk .txt files.
2) Generate one output audio file per chunk in matching order/name.

Examples:
  python batch_ultimate_clone.py --ref samples\\my_voice.wav --source-text-file long_script.txt --chunks-dir chunks --output-dir outs
  python batch_ultimate_clone.py --ref samples\\my_voice.wav --input-dir chunks --output-dir outs --steps 16
  python batch_ultimate_clone.py --ref samples\\my_voice.wav --transcript "exact ref transcript" --clone-mode hifi --input-dir chunks --output-dir outs
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

import soundfile as sf
from voxcpm import VoxCPM


def natural_key(path: Path):
    name = path.stem
    m = re.match(r"^\D*(\d+)", name)
    if m:
        return (0, int(m.group(1)), name.lower())
    return (1, 10**9, name.lower())


def slug_from_text(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return "chunk"
    slug = "_".join(words[:max_words]).lower()
    return slug[:60]


def split_long_sentence(sentence: str, max_chars: int) -> List[str]:
    words = sentence.split()
    if not words:
        return []
    parts = []
    cur = []
    cur_len = 0
    for w in words:
        add_len = len(w) if not cur else len(w) + 1
        if cur and (cur_len + add_len > max_chars):
            parts.append(" ".join(cur).strip())
            cur = [w]
            cur_len = len(w)
        else:
            cur.append(w)
            cur_len += add_len
    if cur:
        parts.append(" ".join(cur).strip())
    return parts


def split_text_into_chunks(text: str, max_chars: int) -> List[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
        for sentence in sentences:
            if len(sentence) > max_chars:
                sentence_parts = split_long_sentence(sentence, max_chars)
            else:
                sentence_parts = [sentence]

            for part in sentence_parts:
                if not current:
                    current = part
                    continue
                if len(current) + 1 + len(part) <= max_chars:
                    current = f"{current} {part}"
                else:
                    chunks.append(current.strip())
                    current = part
        if current:
            chunks.append(current.strip())
            current = ""

    if current:
        chunks.append(current.strip())
    return [c for c in chunks if c]


def write_chunks(source_text_file: Path, chunks_dir: Path, max_chars: int) -> List[Path]:
    text = source_text_file.read_text(encoding="utf-8")
    chunks = split_text_into_chunks(text, max_chars=max_chars)
    if not chunks:
        raise ValueError("No chunk text generated from source text.")

    chunks_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for i, chunk in enumerate(chunks, start=1):
        slug = slug_from_text(chunk)
        out_name = f"{i:03d}_{slug}.txt"
        out_path = chunks_dir / out_name
        out_path.write_text(chunk + "\n", encoding="utf-8")
        written.append(out_path)
    return written


def save_audio(wav, sr: int, output: Path, speed: float):
    output.parent.mkdir(parents=True, exist_ok=True)
    ext = output.suffix.lower()
    needs_ffmpeg = ext != ".wav" or speed != 1.0

    if needs_ffmpeg:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(output.parent)) as tmp:
            tmp_path = Path(tmp.name)
        sf.write(str(tmp_path), wav, sr)
        ffmpeg_cmd = ["ffmpeg", "-y", "-i", str(tmp_path)]
        if speed != 1.0:
            ffmpeg_cmd += ["-filter:a", f"atempo={speed}"]
        ffmpeg_cmd.append(str(output))
        try:
            subprocess.run(ffmpeg_cmd, capture_output=True, check=True)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
    else:
        sf.write(str(output), wav, sr)


def main():
    parser = argparse.ArgumentParser(description="Batch cloning for VoxCPM2")
    parser.add_argument("--ref", required=True, help="Reference voice audio path")
    parser.add_argument("--transcript", help="Exact transcript of reference audio (required for --clone-mode hifi)")
    parser.add_argument(
        "--clone-mode",
        choices=["reference", "hifi"],
        default="reference",
        help="reference: timbre cloning with reference_wav only (recommended). hifi: prompt+transcript+reference (ultimate style).",
    )

    parser.add_argument("--source-text-file", help="Single long source text file to split into chunks")
    parser.add_argument("--chunks-dir", help="Directory to write chunk .txt files (used with --source-text-file)")
    parser.add_argument("--input-dir", help="Directory containing pre-split .txt chunk files")
    parser.add_argument("--output-dir", required=True, help="Directory to write generated audio files")

    parser.add_argument("--format", choices=["wav", "mp3", "ogg", "m4a"], default="wav", help="Output audio format")
    parser.add_argument("--max-chars", type=int, default=320, help="Max chars per chunk when auto-splitting")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed (1.0 normal)")
    parser.add_argument("--cfg", type=float, default=2.0, help="Classifier-free guidance")
    parser.add_argument("--steps", type=int, default=10, help="Inference timesteps")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, do not generate audio")
    args = parser.parse_args()

    ref = args.ref
    transcript = args.transcript or ""

    ref_path = Path(ref).resolve()
    if not ref_path.exists():
        print(f"Error: reference audio not found: {ref_path}")
        sys.exit(1)

    if args.clone_mode == "hifi" and not (transcript or "").strip():
        print("Error: --clone-mode hifi requires --transcript (exact words in reference audio).")
        sys.exit(1)

    if args.source_text_file:
        source_text = Path(args.source_text_file).resolve()
        if not source_text.exists():
            print(f"Error: source text file not found: {source_text}")
            sys.exit(1)
        if args.chunks_dir:
            chunk_dir = Path(args.chunks_dir).resolve()
        else:
            chunk_dir = source_text.parent / f"{source_text.stem}_chunks"
        generated_chunks = write_chunks(source_text, chunk_dir, max_chars=args.max_chars)
        print(f"Wrote {len(generated_chunks)} chunk file(s) to: {chunk_dir}")
        input_dir = chunk_dir
    elif args.input_dir:
        input_dir = Path(args.input_dir).resolve()
    else:
        parser.error("Provide --source-text-file OR --input-dir")

    if not input_dir.exists():
        print(f"Error: input dir not found: {input_dir}")
        sys.exit(1)

    txt_files = sorted([p for p in input_dir.glob("*.txt") if p.is_file()], key=natural_key)
    if not txt_files:
        print(f"Error: no .txt files found in {input_dir}")
        sys.exit(1)

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Input chunks: {len(txt_files)}")
    print(f"Output dir: {out_dir}")
    print(f"Reference audio: {ref_path}")
    print(f"Clone mode: {args.clone_mode}")
    print(f"Steps: {args.steps}, CFG: {args.cfg}, Speed: {args.speed}")

    plan_rows = []
    for idx, txt_path in enumerate(txt_files, start=1):
        text = txt_path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        out_name = f"{txt_path.stem}.{args.format}"
        out_path = out_dir / out_name
        plan_rows.append((idx, txt_path, out_path, text))

    print(f"Planned generations: {len(plan_rows)}")
    if args.dry_run:
        for idx, txt_path, out_path, _ in plan_rows:
            print(f"[DRY RUN] {idx:03d}: {txt_path.name} -> {out_path.name}")
        return

    print("Loading model...")
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)

    for idx, txt_path, out_path, text in plan_rows:
        print(f"[{idx:03d}/{len(plan_rows):03d}] Generating: {txt_path.name}")
        kwargs = {
            "text": text,
            "reference_wav_path": str(ref_path),
            "cfg_value": args.cfg,
            "inference_timesteps": args.steps,
        }
        if args.clone_mode == "hifi":
            kwargs["prompt_wav_path"] = str(ref_path)
            kwargs["prompt_text"] = transcript

        wav = model.generate(**kwargs)
        save_audio(wav, model.tts_model.sample_rate, out_path, speed=args.speed)
        print(f"Saved: {out_path}")

    print("Done.")


if __name__ == "__main__":
    main()
