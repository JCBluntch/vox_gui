import datetime as dt
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import gradio as gr


SCRIPT_DIR = Path(__file__).resolve().parent
BATCH_SCRIPT = SCRIPT_DIR / "batch_ultimate_clone.py"
CONCAT_SCRIPT = SCRIPT_DIR / "concat_audio_chunks.py"
DEFAULT_RUNS_ROOT = SCRIPT_DIR / "runs"
SAMPLES_DIR = SCRIPT_DIR / "samples"
AUDIO_SAMPLE_EXTENSIONS = {".wav", ".mp3", ".ogg", ".m4a"}
NO_SAMPLE_LABEL = "No Voice Samples Found"
NO_SAMPLE_VALUE = "__no_voice_samples__"
CUSTOM_CSS = """
#stitch-card {
  background: var(--block-background-fill);
  border: var(--block-border-width) solid var(--block-border-color);
  border-radius: var(--block-radius);
  padding: 12px 0 0 0;
  gap: 0;
}
.stitch-card-title {
  margin-top: 5px !important;
  margin-bottom: 6px !important;
  padding-left: 12px !important;
}
.stitch-card-title p {
  margin: 0 !important;
  font-weight: 600;
}
#stitch-bottom-row {
  align-items: center !important;
}
#stitch-button-column {
  justify-content: center !important;
}
.folder-picker-row {
  align-items: center !important;
  flex-wrap: nowrap !important;
  min-width: 0 !important;
}
.folder-picker-cell {
  background: var(--block-background-fill);
  border: var(--block-border-width) solid var(--block-border-color);
  border-radius: var(--block-radius);
  padding: var(--block-padding);
  gap: 4px !important;
}
.folder-picker-label {
  margin: 0 !important;
}
.folder-picker-label p {
  margin: 0 !important;
  font-weight: 600;
}
.folder-picker-btn {
  min-width: 110px !important;
  max-width: 110px !important;
  flex: 0 0 110px !important;
}
.folder-picker-field {
  min-width: 0 !important;
  flex: 1 1 auto !important;
}
#auto-stitch-toggle {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  height: 100% !important;
}
#reference-audio-toggle .info {
  font-size: 0.95rem !important;
  line-height: 1.35 !important;
}
.gradio-container {
  padding-bottom: 56px !important;
}
#site-footer {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1000;
  background: var(--block-background-fill);
  border-top: var(--block-border-width) solid var(--block-border-color);
  color: var(--body-text-color);
  padding: 12px 20px;
  text-align: center;
}
"""


def _timestamp_name() -> str:
    return dt.datetime.now().strftime("run_%Y%m%d_%H%M%S")


def _existing_fs_roots():
    roots = []
    for i in range(65, 91):  # A-Z
        root = f"{chr(i)}:\\"
        if os.path.exists(root):
            roots.append(root)
    # Always include workspace and runs root explicitly.
    roots.append(str(SCRIPT_DIR.resolve()))
    roots.append(str(DEFAULT_RUNS_ROOT.resolve()))
    # Deduplicate while preserving order.
    seen = set()
    out = []
    for p in roots:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _recommended_runs_root() -> str:
    prod_base = Path(r"E:\Inceptal\vox")
    if prod_base.exists():
        return str((prod_base / "runs").resolve())
    return str(DEFAULT_RUNS_ROOT.resolve())


def _to_path_string(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, dict):
        return v.get("path") or v.get("name") or ""
    if isinstance(v, list):
        if not v:
            return ""
        return _to_path_string(v[0])
    return str(v)


def _discover_voice_samples():
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    samples = {}
    for path in sorted(SAMPLES_DIR.iterdir(), key=lambda item: item.name.lower()):
        if path.is_file() and path.suffix.lower() in AUDIO_SAMPLE_EXTENSIONS:
            samples[path.name] = path.resolve()
    return samples


def _voice_sample_choices():
    samples = _discover_voice_samples()
    if not samples:
        return [(NO_SAMPLE_LABEL, NO_SAMPLE_VALUE)]
    return [(path.stem, name) for name, path in samples.items()]


def _default_voice_sample():
    samples = _discover_voice_samples()
    return next(iter(samples), NO_SAMPLE_VALUE)


def _sample_transcript_path(sample_name):
    sample_path = _discover_voice_samples().get(sample_name)
    return sample_path.with_suffix(".txt") if sample_path else None


def _load_sample_transcript(sample_name):
    transcript_path = _sample_transcript_path(sample_name)
    if transcript_path and transcript_path.exists():
        return transcript_path.read_text(encoding="utf-8").strip()
    return ""


def _resolve_run_paths(mode, run_name, runs_root, source_text_file, chunks_input_dir, output_dir_override):
    run_name = (run_name or "").strip() or _timestamp_name()
    runs_root_path = Path((runs_root or "").strip() or str(DEFAULT_RUNS_ROOT)).resolve()
    run_root = runs_root_path / run_name
    chunks_auto = run_root / "chunks"
    output_auto = run_root / "audio"

    if output_dir_override and output_dir_override.strip():
        output_dir = Path(output_dir_override.strip()).resolve()
    else:
        output_dir = output_auto

    if mode == "source":
        src = Path(_to_path_string(source_text_file)).resolve()
        if not src.exists():
            raise ValueError(f"Source text file not found: {src}")
        chunk_input_dir = chunks_auto
    else:
        chunk_input_dir = Path((chunks_input_dir or "").strip()).resolve()
        if not chunk_input_dir.exists():
            raise ValueError(f"Chunks folder not found: {chunk_input_dir}")
        src = None

    run_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    if mode == "source":
        chunk_input_dir.mkdir(parents=True, exist_ok=True)

    return run_name, run_root, src, chunk_input_dir, output_dir


def _build_cmd(
    *,
    mode,
    clone_mode,
    voice,
    use_custom_ref,
    custom_ref_audio,
    custom_ref_transcript,
    transcript_override,
    source_path,
    chunk_input_dir,
    output_dir,
    max_chars,
    fmt,
    speed,
    cfg,
    steps,
    dry_run,
):
    cmd = [sys.executable, str(BATCH_SCRIPT)]

    if use_custom_ref:
        ref = Path(_to_path_string(custom_ref_audio)).resolve()
        if not ref.exists():
            raise ValueError(f"Custom reference audio not found: {ref}")
        cmd += ["--ref", str(ref)]
        if clone_mode == "hifi":
            t = (custom_ref_transcript or "").strip()
            if not t:
                raise ValueError("Hi-Fi mode requires transcript. Fill 'Transcript For Custom Reference Audio'.")
            cmd += ["--transcript", t]
    else:
        samples = _discover_voice_samples()
        sample_path = samples.get(voice)
        if not sample_path:
            raise ValueError(
                "No voice sample is selected. Add a clean reference clip to the samples folder "
                "or enable custom reference audio."
            )
        cmd += ["--ref", str(sample_path)]
        if clone_mode == "hifi":
            t = (transcript_override or "").strip()
            if not t:
                raise ValueError("Hi-Fi mode requires transcript. Fill 'Transcript For Selected Sample'.")
            cmd += ["--transcript", t]

    cmd += ["--clone-mode", clone_mode]

    if mode == "source":
        cmd += ["--source-text-file", str(source_path), "--chunks-dir", str(chunk_input_dir)]
    else:
        cmd += ["--input-dir", str(chunk_input_dir)]

    cmd += [
        "--output-dir",
        str(output_dir),
        "--max-chars",
        str(int(max_chars)),
        "--format",
        fmt,
        "--speed",
        str(float(speed)),
        "--cfg",
        str(float(cfg)),
        "--steps",
        str(int(steps)),
    ]

    if dry_run:
        cmd.append("--dry-run")

    return cmd


def _collect_audio_files(out_dir: Path):
    exts = {".wav", ".mp3", ".ogg", ".m4a"}
    files = [p for p in out_dir.glob("*") if p.is_file() and p.suffix.lower() in exts]
    return [str(p) for p in sorted(files, key=lambda x: x.name.lower())]


def _natural_key(path: Path):
    parts = re.split(r"(\d+)", path.stem.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def _expected_audio_paths(chunk_dir: Path, out_dir: Path, output_format: str):
    ext = f".{(output_format or 'mp3').strip().lower()}"
    chunks = sorted([p for p in chunk_dir.glob("*.txt") if p.is_file()], key=_natural_key)
    return [out_dir / f"{chunk.stem}{ext}" for chunk in chunks]


def _collect_expected_audio_files(expected_paths):
    return [str(path) for path in expected_paths if path.exists()]


def _read_tail(path: Path, max_chars=20000):
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= max_chars else text[-max_chars:]


def _resolve_stitched_target(out_dir: Path, stitched_output: str, output_format: str) -> Path:
    out_name = (stitched_output or "").strip()
    ext = (output_format or "mp3").strip().lower()
    if out_name:
        target = Path(out_name)
        if not target.is_absolute():
            target = out_dir / target
    else:
        target = out_dir / f"master.{ext}"

    if target.suffix == "":
        target = target.with_suffix(f".{ext}")
    return target.resolve()


def _write_stitch_manifest(run_root: Path, audio_paths):
    manifest_path = run_root / "stitch_manifest.txt"
    manifest_path.write_text("\n".join(str(path) for path in audio_paths), encoding="utf-8")
    return manifest_path


def _run_stitch_process(out_dir: Path, stitched_target: Path, stitch_gap_ms: int, output_format: str, manifest_path: Path | None = None):
    pattern = f"*.{(output_format or 'mp3').strip().lower()}"
    cmd = [
        sys.executable,
        str(CONCAT_SCRIPT),
        "--input-dir",
        str(out_dir),
        "--output",
        str(stitched_target),
        "--pattern",
        pattern,
        "--gap-ms",
        str(int(stitch_gap_ms)),
    ]
    if manifest_path:
        cmd += ["--manifest", str(manifest_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    logs = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    status = "Stitch Completed" if proc.returncode == 0 else "Stitch Failed"
    summary = (
        f"Status: {status}\n"
        f"Input Folder: {out_dir}\n"
        f"Output File: {stitched_target}\n"
        f"Pattern: {pattern}\n"
        f"Manifest: {manifest_path or 'Not used'}\n"
        f"Gap (ms): {int(stitch_gap_ms)}\n"
        f"Exit Code: {proc.returncode}\n"
        f"Command: {' '.join(cmd)}"
    )
    return summary, logs, proc.returncode


def run_stitch(output_dir, resolved_chunks, run_name, runs_root, stitched_output, stitch_gap_ms, output_format):
    try:
        out_dir = Path((output_dir or "").strip()).resolve()
        if not out_dir.exists():
            return "Status: Error\nResolved Output Folder does not exist.", ""
        chunk_dir = Path((resolved_chunks or "").strip()).resolve()
        if not chunk_dir.exists():
            return "Status: Error\nResolved Chunks Folder does not exist.", ""
        expected_paths = _expected_audio_paths(chunk_dir, out_dir, output_format)
        missing = [path.name for path in expected_paths if not path.exists()]
        if missing:
            return f"Status: Error\nMissing expected generated files: {', '.join(missing)}", ""
        run_root = Path((runs_root or "").strip() or str(DEFAULT_RUNS_ROOT)).resolve() / ((run_name or "").strip() or _timestamp_name())
        manifest_path = _write_stitch_manifest(run_root, expected_paths)
        stitched_target = _resolve_stitched_target(out_dir, stitched_output, output_format)
        return _run_stitch_process(out_dir, stitched_target, int(stitch_gap_ms), output_format, manifest_path)[:2]
    except Exception as e:
        return f"Status: Error\n{e}", ""


def _run_stream(
    mode,
    source_text_file,
    chunks_input_dir,
    run_name,
    runs_root,
    output_dir_override,
    voice,
    clone_mode,
    use_custom_ref,
    custom_ref_audio,
    custom_ref_transcript,
    transcript_override,
    max_chars,
    fmt,
    speed,
    cfg,
    steps,
    auto_stitch,
    stitched_output_name,
    stitch_gap_ms,
    dry_run,
):
    try:
        run_name, run_root, src, chunk_dir, out_dir = _resolve_run_paths(
            mode, run_name, runs_root, source_text_file, chunks_input_dir, output_dir_override
        )
        cmd = _build_cmd(
            mode=mode,
            clone_mode=clone_mode,
            voice=voice,
            use_custom_ref=use_custom_ref,
            custom_ref_audio=custom_ref_audio,
            custom_ref_transcript=custom_ref_transcript,
            transcript_override=transcript_override,
            source_path=src,
            chunk_input_dir=chunk_dir,
            output_dir=out_dir,
            max_chars=max_chars,
            fmt=fmt,
            speed=speed,
            cfg=cfg,
            steps=steps,
            dry_run=dry_run,
        )
        auto_stitched_target = None
        if (not dry_run) and auto_stitch:
            auto_stitched_target = _resolve_stitched_target(out_dir, stitched_output_name, fmt)
            cmd += [
                "--auto-stitch-output",
                str(auto_stitched_target),
                "--stitch-gap-ms",
                str(int(stitch_gap_ms)),
            ]

        log_path = run_root / "run.log"
        expected_paths = _expected_audio_paths(chunk_dir, out_dir, fmt)
        existing_conflicts = sorted(path.name for path in expected_paths if path.exists())
        start = time.time()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        with open(log_path, "w", encoding="utf-8", errors="replace") as f:
            proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, text=True, env=env)

        while True:
            rc = proc.poll()
            elapsed = int(time.time() - start)
            logs = _read_tail(log_path)
            files = [] if dry_run else _collect_expected_audio_files(expected_paths)
            status = "Dry Run In Progress" if dry_run else "Generation In Progress"
            summary = (
                f"Status: {status}\n"
                f"Elapsed: {elapsed}s\n"
                f"Run Name: {run_name}\n"
                f"Run Root: {run_root}\n"
                f"Chunks Folder: {chunk_dir}\n"
                f"Output Folder: {out_dir}\n"
                f"Generated Files So Far: {len(files)}\n"
                f"Expected Files This Run: {len(expected_paths)}\n"
                f"Pre-existing Matching Files: {', '.join(existing_conflicts) if existing_conflicts else 'None'}\n"
                f"Log File: {log_path}\n"
                f"Command: {' '.join(cmd)}"
            )
            yield summary, logs, str(chunk_dir), str(out_dir), files, "", "", gr.update(interactive=False)
            if rc is not None:
                break
            time.sleep(2)

        final_logs = _read_tail(log_path, max_chars=50000)
        final_files = [] if dry_run else _collect_expected_audio_files(expected_paths)
        final_status = "Dry Run Completed" if (dry_run and proc.returncode == 0) else (
            "Generation Completed" if proc.returncode == 0 else "Failed"
        )
        final_summary = (
            f"Status: {final_status}\n"
            f"Elapsed: {int(time.time() - start)}s\n"
            f"Run Name: {run_name}\n"
            f"Run Root: {run_root}\n"
            f"Chunks Folder: {chunk_dir}\n"
            f"Output Folder: {out_dir}\n"
            f"Generated Files: {len(final_files)}\n"
            f"Expected Files This Run: {len(expected_paths)}\n"
            f"Pre-existing Matching Files: {', '.join(existing_conflicts) if existing_conflicts else 'None'}\n"
            f"Exit Code: {proc.returncode}\n"
            f"Log File: {log_path}\n"
            f"Command: {' '.join(cmd)}"
        )
        stitch_summary = ""
        stitch_logs = ""
        stitch_btn = gr.update(interactive=False)

        if (not dry_run) and auto_stitch:
            stitch_ok = bool(auto_stitched_target and auto_stitched_target.exists() and proc.returncode == 0)
            stitch_status = "Completed" if stitch_ok else "Failed"
            final_summary += f"\nAuto-Stitch: {stitch_status}"
            stitch_summary = (
                f"Status: Stitch {stitch_status}\n"
                f"Output File: {auto_stitched_target}\n"
                f"Gap (ms): {int(stitch_gap_ms)}\n"
                "Mode: Auto-stitch ran inside the generation job."
            )
            stitch_logs = "Auto-stitch details are included in the main run log above."
            stitch_btn = gr.update(interactive=False)
        elif (not dry_run) and proc.returncode == 0 and (not auto_stitch):
            stitch_summary = "Auto-stitch disabled. Click 'Stitch Now' to stitch with current settings."
            stitch_logs = ""
            stitch_btn = gr.update(interactive=True)

        yield final_summary, final_logs, str(chunk_dir), str(out_dir), final_files, stitch_summary, stitch_logs, stitch_btn
    except Exception as e:
        yield f"Status: Error\n{e}", "", "", "", [], "", "", gr.update(interactive=True)


def run_plan(*args):
    yield from _run_stream(*args, dry_run=True)


def run_generation(*args):
    yield from _run_stream(*args, dry_run=False)


def _toggle_stitch_button(auto_stitch, resolved_output):
    return gr.update(interactive=bool((resolved_output or "").strip()) and not auto_stitch)


def _on_mode_change(mode):
    is_source = mode == "source"
    max_info = "Applied only in Source Text File mode." if is_source else "Not used in Existing Chunks mode."
    return (
        gr.update(visible=is_source),
        gr.update(visible=not is_source),
        gr.update(visible=not is_source),
        gr.update(interactive=is_source, info=max_info),
    )


def _on_custom_ref_change(checked):
    return (
        gr.update(interactive=(not checked) and bool(_discover_voice_samples())),
        gr.update(visible=checked),
        gr.update(visible=checked),
    )


def _refresh_voice_samples():
    samples = _discover_voice_samples()
    if not samples:
        return gr.update(
            choices=[(NO_SAMPLE_LABEL, NO_SAMPLE_VALUE)],
            value=NO_SAMPLE_VALUE,
            interactive=False,
        )
    return gr.update(
        choices=[(path.stem, name) for name, path in samples.items()],
        value=next(iter(samples)),
        interactive=True,
    )


def _suggest_sample_transcript(voice, use_custom_ref, clone_mode, current_value):
    if use_custom_ref:
        return gr.update()
    if clone_mode != "hifi":
        return gr.update()
    if (current_value or "").strip():
        return gr.update()
    return gr.update(value=_load_sample_transcript(voice))


def _apply_production_profile():
    return (
        gr.update(value="chunks"),      # mode
        gr.update(value="reference"),   # clone_mode
        gr.update(value=False),         # use_custom_ref
        gr.update(value=320),           # max_chars
        gr.update(value="mp3"),         # format
        gr.update(value=1.0),           # speed
        gr.update(value=2.0),           # cfg
        gr.update(value=10),            # steps
        gr.update(value=_recommended_runs_root()),  # runs_root
    )


def _nearest_existing_dir(path_value: str | None) -> Path:
    if not (path_value or "").strip():
        return Path.home()

    current = Path((path_value or "").strip()).expanduser()
    if current.exists():
        return current if current.is_dir() else current.parent

    for parent in current.parents:
        if parent.exists():
            return parent

    return Path.home()


def _pick_folder(current_value, title):
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            initialdir=str(_nearest_existing_dir(current_value)),
            title=title,
            mustexist=True,
        )
        root.destroy()
        return selected or current_value or ""
    except Exception as e:
        raise gr.Error(f"Could not open the folder picker: {e}") from e


def _browse_output_folder(current_value):
    return _pick_folder(current_value, "Select output folder")


def _browse_chunks_folder(current_value):
    return _pick_folder(current_value, "Select existing chunks folder")


def build_ui():
    with gr.Blocks(title="VoxCPM Batch Cloning", css=CUSTOM_CSS) as demo:
        gr.Markdown(
            "## VoxCPM Batch Cloning\n"
            "Docs-aligned modes: `reference` (recommended) and `hifi` (requires exact transcript)."
        )

        with gr.Row():
            mode = gr.Radio(
                choices=[("Source Text File (auto-split)", "source"), ("Existing Chunks Folder", "chunks")],
                value="chunks",
                label="Input Mode",
            )
            run_name = gr.Textbox(value="", label="Run Name (optional)")

        with gr.Row():
            runs_root = gr.Textbox(value=str(DEFAULT_RUNS_ROOT), label="Runs Root Folder")
            with gr.Column(elem_classes=["folder-picker-cell"]):
                gr.Markdown("Output Folder Override (optional)", elem_classes=["folder-picker-label"])
                with gr.Row(elem_classes=["folder-picker-row"]):
                    output_dir_override = gr.Textbox(
                        value="",
                        show_label=False,
                        container=False,
                        scale=4,
                        min_width=0,
                        elem_classes=["folder-picker-field"],
                    )
                    output_dir_browse_btn = gr.Button(
                        "Browse...",
                        variant="primary",
                        min_width=110,
                        elem_classes=["folder-picker-btn"],
                    )

        source_text_file = gr.File(label="Source Text File", file_count="single", type="filepath", visible=False)
        with gr.Column(elem_classes=["folder-picker-cell"]):
            gr.Markdown("Existing Chunks Folder Path", elem_classes=["folder-picker-label"])
            with gr.Row(elem_classes=["folder-picker-row"]):
                chunks_input_dir = gr.Textbox(
                    value="",
                    show_label=False,
                    container=False,
                    visible=True,
                    scale=4,
                    min_width=0,
                    elem_classes=["folder-picker-field"],
                )
                chunks_dir_browse_btn = gr.Button(
                    "Browse...",
                    variant="primary",
                    min_width=110,
                    visible=True,
                    elem_classes=["folder-picker-btn"],
                )

        with gr.Row():
            voice = gr.Dropdown(
                choices=_voice_sample_choices(),
                value=_default_voice_sample(),
                label="Voice Sample",
                interactive=bool(_discover_voice_samples()),
            )
            clone_mode = gr.Radio(
                choices=[("Reference-only cloning (recommended)", "reference"), ("Hi-Fi cloning (exact transcript required)", "hifi")],
                value="reference",
                label="Clone Mode",
            )
            use_custom_ref = gr.Checkbox(
                value=False,
                label="Reference Audio",
                info=(
                    "Use this when you want to upload a reference clip instead of choosing one from the samples folder. "
                    "Check it, then upload a clear reference clip below."
                ),
                elem_id="reference-audio-toggle",
            )

        custom_ref_audio = gr.File(label="Custom Reference Audio", file_count="single", type="filepath", visible=False)
        custom_ref_transcript = gr.Textbox(label="Transcript For Custom Reference (required only in Hi-Fi mode)", lines=2, visible=False)
        transcript_override = gr.Textbox(
            label="Transcript For Selected Sample (used only in Hi-Fi mode)",
            lines=2,
            info="For Hi-Fi mode, this must match the exact spoken words in the selected sample.",
        )

        with gr.Row():
            max_chars = gr.Slider(minimum=120, maximum=600, value=320, step=10, label="Max Chars Per Chunk")
            fmt = gr.Dropdown(choices=["wav", "mp3", "ogg", "m4a"], value="mp3", label="Output Format")
            speed = gr.Slider(minimum=0.75, maximum=1.25, value=1.0, step=0.05, label="Playback Speed")

        with gr.Row():
            cfg = gr.Slider(minimum=1.0, maximum=3.0, value=2.0, step=0.1, label="CFG")
            steps = gr.Slider(minimum=4, maximum=30, value=10, step=1, label="Inference Steps")

        with gr.Column(elem_id="stitch-card"):
            gr.Markdown("**Stitch Settings**", elem_classes=["stitch-card-title"])
            with gr.Row(equal_height=True):
                with gr.Column(scale=1):
                    auto_stitch = gr.Checkbox(
                        value=False,
                        label="Auto-Stitch After Generation",
                        elem_id="auto-stitch-toggle",
                    )
                with gr.Column(scale=2):
                    stitched_output_name = gr.Textbox(value="", label="Output File Name (optional)")
            with gr.Row(equal_height=False, elem_id="stitch-bottom-row"):
                with gr.Column(scale=1, elem_id="stitch-button-column"):
                    stitch_btn = gr.Button(
                        "Stitch Now",
                        variant="primary",
                        size="lg",
                        interactive=False,
                    )
                with gr.Column(scale=2):
                    stitch_gap_ms = gr.Slider(minimum=0, maximum=1000, value=100, step=10, label="Gap Between Chunks (ms)")

        with gr.Row():
            profile_btn = gr.Button("Apply Production Profile", variant="secondary")
            plan_btn = gr.Button("Plan (Dry Run)", variant="secondary")
            run_btn = gr.Button("Run Generation", variant="primary")

        summary = gr.Textbox(label="Summary", lines=8)
        logs = gr.Textbox(label="Logs", lines=16)
        resolved_chunks = gr.Textbox(label="Resolved Chunks Folder")
        resolved_output = gr.Textbox(label="Resolved Output Folder")
        output_files = gr.Files(label="Generated Audio Files")
        stitch_summary = gr.Textbox(label="Stitch Summary", lines=6)
        stitch_logs = gr.Textbox(label="Stitch Logs", lines=10)
        gr.HTML(f'<footer id="site-footer">Copyright &copy; TIC Tools {dt.datetime.now().year}</footer>')

        demo.load(fn=_refresh_voice_samples, outputs=[voice])
        mode.change(fn=_on_mode_change, inputs=[mode], outputs=[source_text_file, chunks_input_dir, chunks_dir_browse_btn, max_chars])
        use_custom_ref.change(fn=_on_custom_ref_change, inputs=[use_custom_ref], outputs=[voice, custom_ref_audio, custom_ref_transcript])
        voice.change(fn=_suggest_sample_transcript, inputs=[voice, use_custom_ref, clone_mode, transcript_override], outputs=[transcript_override])
        clone_mode.change(fn=_suggest_sample_transcript, inputs=[voice, use_custom_ref, clone_mode, transcript_override], outputs=[transcript_override])
        output_dir_browse_btn.click(fn=_browse_output_folder, inputs=[output_dir_override], outputs=[output_dir_override])
        chunks_dir_browse_btn.click(fn=_browse_chunks_folder, inputs=[chunks_input_dir], outputs=[chunks_input_dir])
        auto_stitch.change(fn=_toggle_stitch_button, inputs=[auto_stitch, resolved_output], outputs=[stitch_btn])
        resolved_output.change(fn=_toggle_stitch_button, inputs=[auto_stitch, resolved_output], outputs=[stitch_btn])
        profile_btn.click(
            fn=_apply_production_profile,
            outputs=[mode, clone_mode, use_custom_ref, max_chars, fmt, speed, cfg, steps, runs_root],
        ).then(
            fn=_on_mode_change,
            inputs=[mode],
            outputs=[source_text_file, chunks_input_dir, chunks_dir_browse_btn, max_chars],
        )

        inputs = [
            mode,
            source_text_file,
            chunks_input_dir,
            run_name,
            runs_root,
            output_dir_override,
            voice,
            clone_mode,
            use_custom_ref,
            custom_ref_audio,
            custom_ref_transcript,
            transcript_override,
            max_chars,
            fmt,
            speed,
            cfg,
            steps,
            auto_stitch,
            stitched_output_name,
            stitch_gap_ms,
        ]

        plan_btn.click(
            fn=run_plan,
            inputs=inputs,
            outputs=[summary, logs, resolved_chunks, resolved_output, output_files, stitch_summary, stitch_logs, stitch_btn],
        )
        run_btn.click(
            fn=run_generation,
            inputs=inputs,
            outputs=[summary, logs, resolved_chunks, resolved_output, output_files, stitch_summary, stitch_logs, stitch_btn],
        )
        stitch_btn.click(
            fn=run_stitch,
            inputs=[resolved_output, resolved_chunks, run_name, runs_root, stitched_output_name, stitch_gap_ms, fmt],
            outputs=[stitch_summary, stitch_logs],
        )

    return demo


if __name__ == "__main__":
    app = build_ui()
    app.queue(max_size=10, default_concurrency_limit=1).launch(
        server_name="127.0.0.1",
        server_port=8820,
        allowed_paths=_existing_fs_roots(),
    )
