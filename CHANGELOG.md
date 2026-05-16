# Changelog

## v1.0.2

- Move automatic post-generation stitching into the batch generation job so it no longer depends on the browser session staying connected for the full run.
- Preserve browser-side reporting while making long auto-stitch runs more reliable after generation completes.
- Keep manual `Stitch Now` behavior intact for users who prefer to stitch after reviewing chunk outputs.

## v1.0.1

- Count only the files expected for the current run instead of every audio file already present in the output folder.
- Show the expected file count and any pre-existing matching filenames in run summaries.
- Stitch from an exact current-run manifest so stale audio files in reused output folders are not included accidentally.
- Allow intentionally skipped chunk numbers, such as a removed `overview 13.txt`, without treating the numbering gap as an error.

## v1.0

- Initial public release.
- Browser interface for batch VoxCPM2 cloning.
- Support for full source files or user-created chunk folders.
- Dynamic local voice-sample discovery from the `samples` folder.
- Reference-only and Hi-Fi cloning workflows.
- Dry runs, batch generation, optional stitching, and Windows launch helpers.
