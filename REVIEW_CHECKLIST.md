# Manual review and validation checklist

Use this on your actual **Windows RTX** host. The automated tests check protocol format and app behavior but **do not** validate NVIDIA native inference.

## 0. Clean install

- [ ] `uv sync --extra dev` succeeds on Python 3.12 or 3.13.
- [ ] Download FFmpeg/ffprobe and place the matching native worker/model manually as shown in [README.md](README.md#download-and-place-the-external-files).
- [ ] `uv run nvs doctor` lists your GPU, detects FFmpeg/ffprobe, and reports `render_available: true`.
- [ ] `uv run pytest -q` passes.
- [ ] `uv run nvs serve` launches the app at `http://127.0.0.1:7860`.
- [ ] Browser page, API docs (`/docs`) and runtime diagnostics open.

## 1. Source upload and preview

- [ ] Upload a 5–10 second **SDR 1920×1080 H.264 MP4** from the web page.
- [ ] Confirm the preview player shows the original video and can seek.
- [ ] Try the image preview on a mid-video frame if `preview/dlssnr-image.exe` is present.
- [ ] Check Faithful, Natural, Strong and Extreme styles individually and confirm image output changes.
- [ ] Verify that the preview explicitly uses **clamped parameter ranges** if sliders exceed the image worker's limits.

## 2. End-to-end render

- [ ] Natural profile, H.264 High, MP4: render the 5–10 second sample.
- [ ] Native worker launches without DLL/driver errors.
- [ ] Progress changes, and JSON report is downloadable.
- [ ] Report `feature_18_confirmed = true`; `direct_create_result = 0x00000001`.
- [ ] Report's `successful_direct_evaluations == frames_processed == frames_verified`.
- [ ] Original source duration and processed output duration agree.
- [ ] Output video contains original audio and is seekable in standard video players.
- [ ] Run a second render with a different profile and compare output frames.

## 3. Failure and cancellation

- [ ] Queue two jobs and verify only one native render runs at a time.
- [ ] Cancel a queued job; verify status becomes cancelled.
- [ ] Cancel a running job; verify no successful output is exposed.
- [ ] Upload an unsupported file type; the API should reject it.
- [ ] Upload fake MP4 content; the job should fail rather than report success.
- [ ] Temporarily move the model out of `runtime/`; diagnostic check should fail and rendering should be blocked.
- [ ] Stop/restart app while jobs are queued; interrupted jobs should be reported as failed after restart.

## 4. Larger media and unusual formats

- [ ] 30-second gameplay 1080p60 (correct FPS and all frames verified).
- [ ] 4K30/4K60 sample (monitor VRAM, RAM, speed, correctness).
- [ ] HEVC input, HEVC output.
- [ ] MKV output with multiple audio/subtitle tracks (confirm FFmpeg stream copying and player compatibility).
- [ ] Source video with rotation metadata (check orientation).
- [ ] VFR / smartphone capture (PTS monotonic, output duration and synchronization).
- [ ] HDR input gets an explicit unsupported error (no false HDR preservation).
- [ ] AV1 or lossless selections are gracefully rejected if the GPU/FFmpeg build cannot support them.

## 5. Native runtime provenance

- [ ] Hash `runtime/nvngx.dll` and `runtime/nvngx_dlssnr.dll` with `Get-FileHash`.
- [ ] Compare hashes against trusted upstream release metadata and the report's SHA-256 fields.
- [ ] Understand modified/unsigned native binaries are **not included** in this project.
- [ ] Do not expose this localhost single-user API directly to the internet.

## Known unknowns until you test

- The actual NVIDIA feature-18 native worker is **not** available in the automated test environment.
- Performance, correctness, and driver compatibility on your specific RTX/H100/H200 must be established by measured tests.
- RTX 30 and 40 operation is experimental and may vary by driver/runtime.
- Image preview is a different program from the temporal video worker and need not match it pixel-for-pixel.
- Linux CPU/H100/H200 native inference is **not implemented**.

## What to share when a test fails

From the webpage, copy the failing job's error; also capture `uv run nvs doctor` and your GPU/driver versions. Never upload proprietary runtime files to a public issue without verifying redistribution rights.

## v0.2 HEVC/Audio/Cuts regression checks

- [ ] Set `HEVC 10-bit / NVENC P7 CQ20` and `60 FPS`, render a short sample; confirm `nvngx.dll` receives every selected frame and reports feature-18 creation success.
- [ ] Keep `0-2` and `4-end` of a 6-second sample; verify the output is ~4 seconds, no duplicate middle interval, and optical flow is reset at the cut.
- [ ] Check that native successful evaluation count is the **selected source frames**, whereas output frame count may differ if FFmpeg converts to 60 CFR.
- [ ] Use `ffprobe -v error -show_streams -show_format final.mp4` and verify HEVC, 10-bit 4:2:0 (reported as `yuv420p10le`), ~60 fps, AAC 48 kHz, MP4 `hvc1`, audio/video durations close.
- [ ] Play an actual fast-action sequence after the cut and verify lip/audio timing by ear and waveform. Metadata checks alone do not prove A/V sync.
- [ ] Test a source recorded at 59.94 fps, VFR, and a source with an initial timestamp offset; inspect sync.
- [ ] Check resulting file size and visual quality; CQ20 is quality-targeted lossy compression, not lossless video.
- [ ] Verify no second video encode happens during the muxing step (it should be `-c:v copy`).
- [ ] Verify a non-NVENC machine fails clearly for this export preset rather than silently downgrading to 8-bit CPU encoding.

## v0.3 editor and results

- [ ] Confirm the new editor-style UI is readable at desktop and mobile widths.
- [ ] Inspect the Look/Export/Cuts tab selections and ensure values survive tab changes.
- [ ] Upload local footage and scrub the source playhead.
- [ ] Run a small real native DLSS job to completion on your Windows RTX GPU.
- [ ] Click **Watch 12s sample** and confirm the scene shows changes compared with the original source.
- [ ] Try full HEVC playback; if browser decoding fails, confirm sample and download still work.
- [ ] Verify audio on the sample and final file and check synchronization.
- [ ] Confirm a failed job exposes neither download nor sample endpoint.
- [ ] Verify original output checksum/verification isn't modified by sample encoding.
