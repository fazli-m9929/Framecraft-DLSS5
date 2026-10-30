## v0.3.2

- Replace false-negative tiny synthetic Main10 NVENC probe with FFmpeg build encoder discovery.
- Let actual NVENC job determine GPU support and surface stderr.
- Move MP4 `hvc1` tagging from intermediate MKV to final MP4.
- Introduce five export recipes, one Custom option, and expose FPS independently.
- Preserve v0.3.1 frame counting/seek fix and old job option names.
- CLI `--host` / `--port` and documented LAN binding/security limitations.
- Remove game-specific preset labels.

# Changelog

## 0.3.1 — counting stage correction

- Seek over removed footage rather than decoding every source frame in the counting pass.
- Use the exact same clip selection iterator for pre-counting and native rendering, maintaining the worker header contract.
- Report progress from 1% through 9% with current clip, source timestamp, and decoded-frame count.
- Enable PyAV decoding threads during counting.
- Test seek behavior, exact selected frame count, and cancellation using a simulated reader.

### Important

Selected footage **still needs one preliminary decode pass**, because the existing native worker expects an exact frame count up front. Long 4K clips can still require some time. This change has only been exercised with unit tests here, not your Windows DLSS worker or live PyAV decoder.

### Upgrade

1. Stop the Framecraft server and cancel the previous job.
2. Extract the new ZIP over the v0.3.0 project, keeping `.env`, `runtime/`, `preview/`, and `data/` intact. Alternatively, replace only `src/nvs/pipeline.py`.
3. Run `uv sync --extra dev` then `uv run nvs serve`.
4. Retry a 5–10-second clip first.
