# Framecraft v0.3.2 — Export presets and network binding

This patch fixes the false-negative HEVC Main10 detection in v0.3.1, moves
`hvc1` tagging to the final MP4 mux (not the intermediate MKV), provides
five clear NVENC export recipes, and adds `--host` / `--port` CLI flags.

**Windows launch:**

```powershell
uv sync --extra dev
uv run nvs doctor
uv run nvs serve --host 0.0.0.0 --port 7860
```

Open `http://127.0.0.1:7860` locally; from another machine on the same LAN
open `http://YOUR-WINDOWS-PC-LAN-IP:7860`. Windows Firewall may need an inbound
TCP 7860 rule. This app has **no login/authentication**: do not expose it to
the public internet. Anyone who can reach the service can upload files and
start GPU jobs.

Alternatively set `NVS_HOST=0.0.0.0` in `.env` and use `uv run nvs serve`.
Setting `0.0.0.0` is for binding, **not** a browser destination.

**Encoder detection:** `ffmpeg -encoders` checks encoder availability in the
selected FFmpeg build. It does not assume a 64x64/1fps synthetic encode is a
reliable hardware probe. The real encoding process provides the authoritative
hardware result and FFmpeg stderr is surfaced on failure. The native DLSS
worker remains Windows-only and needs compatible GPU hardware.

**Export recipes:**

| Recipe | Video settings |
| --- | --- |
| HEVC Main10 - Maximum quality (CQ18) | `hevc_nvenc`, P7, Main10, VBR CQ18, `p010le` |
| HEVC Main10 - Balanced (CQ20) | `hevc_nvenc`, P7, Main10, VBR CQ20, `p010le` |
| HEVC Main10 - Smaller files (CQ24) | `hevc_nvenc`, P7, Main10, VBR CQ24, `p010le` |
| H.264 - Compatible (CQ20) | `h264_nvenc`, P6, VBR CQ20, `yuv420p` |
| AV1 - Efficient (CQ20) | `av1_nvenc`, P6, VBR CQ20, `yuv420p`; hardware required |
| Custom | Existing manual encoder/quality/container logic |

All five recipes use MP4, AAC 384 kbps / 48 kHz when source audio exists, and
faststart. Choose output 60 FPS or retain source FPS independently in the UI.
60 FPS conversion does **not** interpolate with DLSS. The video is encoded
once, then copied to the final MP4 while source audio is synchronized.
Presets are **lossy**; Main10 packing does not restore precision absent from
the RGBA8 native render frames. The default Balanced preset mirrors a popular
HEVC P7 CQ20 workflow without referencing a particular game.

Legacy job files using `Standard` or `HEVC 10-bit / NVENC P7 CQ20` still load.
Existing `runtime/`, `preview/`, `.env`, `data/` should be preserved on update.

---

# Framecraft v0.3 — redesigned editor UI and browser result playback

The UI is a new **editor-style workspace** (Stage / Inspector / Render library) with an independent neutral/violet design rather than the earlier three dark cards. The Look, Export and Cuts inspector tabs preserve existing rendering options and DLSS native protocol. Upload, native frame render and HEVC P7/CQ20 settings remain unchanged.

**New verified result viewers:** completed jobs expose `/api/jobs/{id}/video` (full original, browser codec-dependent) and `/api/jobs/{id}/sample` (cached first 12 seconds, 720p-or-smaller H.264/AAC for browser inspection). The sample comes from the completed neural output, not from the source. It does not re-render with DLSS. The original full output is unchanged and always downloadable. Samples may take time to encode and require FFmpeg with libx264.

**Start here:** [QUICKSTART.md](QUICKSTART.md) contains exact PowerShell installation commands, GPU diagnostics, upload → render → view instructions and troubleshooting. The native feature-18 model cannot be validated without your working Windows RTX hardware.

---

## New in v0.2.0: YouTube-quality export / synchronized clips

**HEVC 10-bit / NVENC P7 CQ20** export profile reproduces the encoding settings used in the HEVC video processing workflow:

```text
-c:v hevc_nvenc -preset p7 -tune hq -profile:v main10
-rc vbr -cq 20 -b:v 0 -pix_fmt p010le -tag:v hvc1
-c:a aac -b:a 384k -ar 48000 -movflags +faststart -use_editlist 0
```

This is *high quality lossy* HEVC/AAC. The original DLSS runtime consumes RGBA8, so packing its rendered output in 10-bit HEVC does **not** restore missing 10-bit color information.

Choose **60 FPS** to match the sample command. FFmpeg will duplicate/drop frames if necessary; DLSS feature 18 itself does not interpolate to 60 FPS. Output validation distinguishes native processed frame count from the CFR-encoded frame count.

To keep exactly the intended portions of a recording, enter these segments in the English web UI:

```text
0-547
945-end
```

The app counts the selected decoded video frames first, seeks past excluded sections in both the counting and rendering passes, reports counting progress, resets optical flow at edits, and uses `atrim` / `asetpts` / `concat` / `aresample` / `apad` for synchronized original-source audio. The FFmpeg mux step copies already-compressed HEVC without re-encoding video again. Counting clips requires one additional source-video decode pass. Multiple clips are supported in chronological order, without overlaps.

`ffprobe` validates the output has HEVC 10-bit 4:2:0, AAC 48 kHz (if source had audio), chosen frame rate, and approximately the selected duration. A native DLSS render still requires the supplied Windows worker, model and a compatible RTX GPU; these binaries are not included.

The settings can also be submitted to `/api/jobs`:

```json
{
  "upload_id": "YOUR_UPLOAD_UUID_HEX",
  "options": {
    "profile": "Natural",
    "export_preset": "HEVC 10-bit / NVENC P7 CQ20",
    "target_fps": "60",
    "codec": "HEVC",
    "container": "MP4",
    "clips": [{"start": 0, "end": 547}, {"start": 945, "end": null}]
  }
}
```

**Important:** Actual end-to-end audio synchronization must be checked on the target Windows RTX PC with representative source clips. Handling of exotic/VFR source timestamps may require targeted adjustments. Do not treat metadata verification as proof of frame-perfect A/V synchronization.

---

# Neural Video Studio

A **local, English-first** FastAPI web application for processing recorded video using the **existing native NVIDIA DLSS Neural Rendering feature-18 worker** from [`perseval-BLR/DLSS5-Video-Converter`](https://github.com/perseval-BLR/DLSS5-Video-Converter).

**This is an independent, experimental integration.** It is not an NVIDIA product. The app does *not* include a neural model, a driver, a GPU implementation of DLSS, or any NVIDIA-modified DLLs. You provide the original worker and model yourself.

> **State of validation:** Python modules, local web/API behavior and packet-layout checks can be tested without an RTX GPU. A full native DLSS render can only be validated on a compatible Windows RTX PC with the actual runtime; no such verification was performed in the build environment. Do not assume that successful startup means feature 18 itself works.

## Supported and unsupported environments

| Host | Web UI / API | DLSS feature-18 worker | Notes |
|---|---|---|---|
| Windows 10/11 + RTX 50 | Yes | Expected; runtime-dependent | Check driver/runtime |
| Windows 10/11 + RTX 40 | Yes | Experimental; runtime-dependent | Upstream reported |
| Windows 10/11 + RTX 30 | Yes | Experimental, potentially slow | Upstream beta |
| Windows + H100 or H200 | Yes | Unverified, not supported by default | CUDA capability is not a replacement for NGX + D3D12 compatibility |
| Linux + H100/H200 | Yes | **No**, provided worker is Windows/D3D12-only | No Wine or CPU emulation claim |
| CPU-only | Yes | **No** | CPU FFmpeg encoding is not CPU DLSS inference |

The `NVS_ALLOW_UNVERIFIED_GPU=true` flag only disables name filtering *on Windows*. It **does not** create hardware compatibility, enable Linux, or prove that feature 18 can execute. Default is false.

## Setup on Windows (PowerShell)

Requirements: Python 3.12/3.13, [`uv`](https://docs.astral.sh/uv/), NVIDIA drivers and the **runtime files you already acquired and verified**.

```powershell
cd neural-video-studio
uv sync --extra dev
Copy-Item .env.example .env
```

### Import binaries from your working upstream installation

If the original converter is at `C:\Users\MohammadReza\Desktop\test\DLSS5-Video-Converter`, for example:

```powershell
.\scripts\import-runtime.ps1 -Source 'C:\Users\MohammadReza\Desktop\test\DLSS5-Video-Converter'
```

The script accepts an upstream source checkout containing `bin/`, or an extracted portable build at `dist\DLSS5VideoConverter`. It copies the following if present:

```text
neural-video-studio/
├── runtime/
│   ├── nvngx.dll            <-- native executable/worker, not a normal DLL entrypoint
│   └── nvngx_dlssnr.dll     <-- proprietary modified neural model
├── bin/ffmpeg/bin/
│   ├── ffmpeg.exe
│   └── ffprobe.exe
└── preview/
    ├── dlssnr-image.exe    <-- optional image preview
    └── caller/nvngx.dll    <-- optional image caller
```

If you have FFmpeg already installed, `bin/ffmpeg/` can be omitted. The app finds FFmpeg on `PATH` or through `NVS_FFMPEG` and `NVS_FFPROBE`. The optional preview image worker uses a *separate* `preview/caller/nvngx.dll` from the main video worker.

**Do not copy the original `nvngx.dll` from an arbitrary graphics driver.** In the upstream package, the main `nvngx.dll` is a modified executable used via stdin/stdout with the `--video` argument. The implementation requires *this exact interface*. Keep its model version and worker version together.

### Diagnose

```powershell
uv run nvs doctor
```

Expect `render_available: true` only if the OS, file presence and GPU-name prerequisites are met. It is **not** a real inference test.

### Run

```powershell
uv run nvs serve
```

Open `http://127.0.0.1:7860`. API documentation at `http://127.0.0.1:7860/docs`.

Alternatively run `./scripts/run.ps1` to sync development dependencies and start.

## Workflow

1. Add a local MP4/MKV/WEBM/MOV/AVI video. Upload is copied to `data/uploads/` in chunks, not buffered entirely into memory.
2. Select one of four original native profiles; use sliders to override parameters.
3. Configure encoder (H.264, HEVC, AV1), quality and container. NVENC is probed by actually encoding a test frame. H.264/HEVC fall back to CPU FFmpeg encoders if necessary; AV1 requires NVENC.
4. Optionally preview a frame with the **separate** `dlssnr-image.exe` (the preview accepts narrower parameter ranges; the UI reports this).
5. Click Render. A single render executes; further jobs queue. Polling updates progress, and Stop terminates active worker and encoder processes.
6. Completed files appear in `data/outputs/` with a JSON evidence report. Failed/cancelled work doesn't get a successful output.

**Reports include:** input metadata, chosen native parameters, feature-18 creation result, count of successful native frame evaluations, exact output frame count, CUDA driver GPU name (from `nvidia-smi`), SHA-256 hashes of both binaries, encoder and log tails.

**Limitations:** SDR/RGBA8 only. HDR inputs are *rejected* instead of silently losing HDR color. Engine motion vectors are not available in prerecorded videos, so optical flow is estimated using OpenCV DIS; ghosting and scene-transition artifacts are possible. The native image preview can differ from the temporal video model output. This project is not a DLSS image/video *upscaler*: output dimensions remain source dimensions. The worker may require unofficial patched binaries and may fail on other GPUs/versions.

## Architecture

```text
web/ (HTML/CSS/JS, English, no Node build)
   └── /api (FastAPI)
       ├── uploads.py      streamed input staging
       ├── jobs.py         single-GPU queue, cancellation, persistent status
       ├── schemas.py      Pydantic parameters and profiles
       ├── hardware.py     Windows/RTX/driver capability checks
       ├── preview.py      optional image-only native worker
       ├── pipeline.py     decode → optical flow → feature-18 → encode → mux → verify
       ├── guides.py       OpenCV DIS motion vectors (current → previous)
       ├── native.py       exact packet protocol + native subprocess + logs
       ├── media.py        ffprobe/ffmpeg wrappers, NVENC fallback, audio mux
       └── config.py       environment-based settings
```

### Native worker packet layout

The upstream code documents the binary protocol; this project uses the same constants and structures (little-endian):

```text
startup: <10I4f>    VIDEO_MAGIC, width, height, warmup, frame_count,
                     profile, preset, style, auto_mask, ui_correction,
                     intensity, tone, structure, skin

frame:   <4Iq>      FRAME_MAGIC, frame_index, reset, reserved, source_pts
         RGBA8      width * height * 4 bytes
         FP16 flow  width * height * 2 vectors * 2 bytes, current-to-previous

result:  <5Iq>      OUTPUT_MAGIC, index, ok, rgba_size, ngx_result, pts
         RGBA8      rgba_size bytes
```

`ngx_result == 1` and a valid response packet are required **on every frame**. The worker must also report successful feature-18 creation, and the output is decoded and counted by ffprobe before committing. Strict mode: a failed frame aborts the job. This package does not patch, emulate or reverse-engineer proprietary graphics binaries.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness |
| GET | `/api/capabilities` | GPU, runtime, FFmpeg and preview checks |
| GET | `/api/presets` | Default native parameters |
| POST | `/api/uploads` | Multipart `file` upload |
| POST | `/api/jobs` | `{ "upload_id": "...", "options": { ... } }` |
| GET | `/api/jobs` | All known jobs |
| GET | `/api/jobs/{id}` | Status and progress |
| POST | `/api/jobs/{id}/cancel` | Cancel a queued/running job |
| GET | `/api/jobs/{id}/download` | Verified video |
| GET | `/api/jobs/{id}/report` | Feature-18 JSON evidence |
| POST | `/api/preview` | `{ "upload_id": "...", "timestamp": 0, "options": { ... } }` |

## Configuration

Edit `.env` (all fields optional):

```dotenv
NVS_HOST=127.0.0.1
NVS_PORT=7860
NVS_RUNTIME_DIR=runtime
NVS_PREVIEW_DIR=preview
NVS_DATA_DIR=data
NVS_MAX_UPLOAD_GB=20
NVS_ALLOW_UNVERIFIED_GPU=false
# NVS_FFMPEG=C:/ffmpeg/bin/ffmpeg.exe
# NVS_FFPROBE=C:/ffmpeg/bin/ffprobe.exe
```

Paths relative to the project root. This is a **single-user localhost** application with no authentication. Do **not** bind to `0.0.0.0` or put it directly on the internet. The API can upload files and run native executables. If you later need remote or multi-user access, add authentication, authorization, rate limits, isolation and a persistent external queue.

Job metadata is stored under `data/jobs/`, and unfinished jobs are marked failed upon restart. Uploaded videos remain on disk until deleted manually (intentional so you can rerender). There is no cleanup policy yet. Avoid storing sensitive videos without access controls and backups.

## Development and tests

```powershell
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
```

Unit/API tests do not require NVIDIA hardware. Full end-to-end testing **does** require the original worker/model running on Windows with a compatible GPU; use a short 5–10 s SDR sample and compare results with the original upstream converter.

## Rights, safety, and provenance

- The application code in this package is an independent experimental wrapper; it does not bundle NVIDIA SDK code, model weights, modified DLLs or upstream source files.
- **The original binary files may be modified, unsigned or restricted by licensing.** Check `others/THIRD_PARTY.md` in the upstream repository for provenance, hashes, and relevant license notices. Do not publish, redistribute or run DLLs you haven't vetted. Use an isolated machine when examining unknown binaries.
- Reference repository: <https://github.com/perseval-BLR/DLSS5-Video-Converter> (consult original README, `core.py`, `guides.py`, and third-party notices).
- FFmpeg is independently licensed and may impose additional obligations depending on the build you distribute.

## Current scope / roadmap

Implemented: English web UI, upload, configurable native parameter mapping, strict video conversion protocol, motion guides, NVENC/CPU **encoding**, audio mux, report, SHA hashes, preview image worker, queue, cancellation, persisted status, tests, and runtime diagnostics.

Not implemented: Linux DLSS inference, CPU DLSS inference, direct H100/H200 DLSS support, authentication, multiple concurrent GPUs, adaptive optical-flow models, HDR, multiple audio/subtitle policies, distributed queue, browser upload resume, GPU scheduling. Those are separate engineering tasks and must not be advertised as functional.
