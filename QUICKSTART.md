# Framecraft v0.3.2 — quick update

Preserve your existing `runtime/`, `preview/`, `data/` and `.env` folders when
updating the source, then from PowerShell:

```powershell
uv sync --extra dev
uv run nvs doctor
uv run nvs serve --host 0.0.0.0 --port 7860
```

Use `http://127.0.0.1:7860` locally; use `http://<Windows-PC-LAN-IP>:7860`
from another LAN machine. **No authentication exists; never directly expose
this service to the public internet.** Windows Firewall may need TCP 7860.

On the Export tab choose an HEVC, H.264, AV1 or Custom recipe. Select 60 FPS
or Source independently. The balanced HEVC recipe uses P7, CQ20 and `p010le`.
Your known-good `ffmpeg` with `hevc_nvenc` must be the one the app uses. Check
`uv run nvs doctor` for the resolved `ffmpeg` path or set `NVS_FFMPEG`.

---

# Framecraft v0.3 — Windows quick start

## 1. Requirements

- Windows 10/11, Python 3.12 or 3.13, and `uv` (https://docs.astral.sh/uv/).
- Working FFmpeg, FFprobe, NVIDIA drivers, and a *compatible GeForce RTX GPU*.
- Your already-working DLSS native files from the upstream converter, including its **modified** `nvngx.dll` worker and matching `nvngx_dlssnr.dll` model. Use files from the same version.
- The program's UI can start without a GPU, but it cannot perform DLSS frame processing without the worker and a compatible RTX runtime. H100/H200/CPU aren't supported by this backend.

## 2. Install and launch

Open PowerShell in the extracted `neural-video-studio` directory:

```powershell
uv sync --extra dev
Copy-Item .env.example .env
.\scripts\import-runtime.ps1 -Source 'C:\Users\MohammadReza\Desktop\test\DLSS5-Video-Converter'
uv run nvs doctor
uv run nvs serve
```

If script execution is restricted by PowerShell, either run `powershell -ExecutionPolicy Bypass -File .\scripts\import-runtime.ps1 -Source 'C:\Users\MohammadReza\Desktop\test\DLSS5-Video-Converter'` or follow your organization's execution policy.

Navigate to **http://127.0.0.1:7860** in a browser. API docs are at `/docs`.

`doctor` must report `render_available: true` to enable Render. This only validates basic prerequisites; it does not prove actual DLSS inference works.

## 3. Inspect the neural result

1. Click **+ Add footage** or drop an SDR gameplay video (first test: 5–10 seconds at 1080p).
2. Source video is playable in the large Stage viewer.
3. In **Look**, choose the rendering character and strength. The optional **Generate before / after** button uses a *different, static image-preview worker*; skip it if `preview/dlssnr-image.exe` is missing.
4. In **Export**, select `HEVC 10-bit / NVENC P7 CQ20` if your GPU supports Main10 NVENC; otherwise use Standard/H.264 for a simpler smoke test. Use **Cuts** to keep intervals such as `0-5`.
5. Click **Render with DLSS**. Scroll to **Render queue** to watch progress. A completed job is eligible for download; a failed job shows its error.
6. On a **completed** job, click **▶ Watch 12s sample**. This creates a cached 12-second, browser-compatible H.264/AAC sample from the *actual rendered output* and plays it in Stage. It is a viewing proxy, not a different DLSS algorithm.
7. Click **Try full playback** to attempt playing the original exported MP4/MKV in the browser; browser support varies (HEVC/Main10 is especially inconsistent). Use **↓ Download full video** and play it in VLC if the browser does not support the codec.
8. Click **JSON report** to examine processed frame counts, runtime result codes, hashes and output verification.

Final video files are also stored under `data/outputs/`. The H.264 viewing samples are in `data/samples/`. Original uploads are in `data/uploads/`.

## 4. Troubleshooting

- **Render disabled:** run `uv run nvs doctor` and inspect `missing`, `gpus`, `reason`, and `render_available`.
- **FFmpeg missing:** provide valid paths using `NVS_FFMPEG` and `NVS_FFPROBE` in `.env`, or import them from the upstream package.
- **Still-image preview unavailable:** `preview/dlssnr-image.exe` and its `caller/nvngx.dll` are optional. Video rendering uses the worker in `runtime/`, which is separate.
- **Browser shows black/full output won't play:** use **Watch 12s sample** or VLC for the downloaded MP4; this commonly happens with HEVC 10-bit playback.
- **12s sample fails:** FFmpeg must include `libx264`; inspect the error message in the browser. It is an extra viewing export and never alters the verified full output.
- **No GPU, H100/H200 or Linux:** UI still opens but the original feature-18 video worker cannot render on these configurations.
- **Large recordings:** Uploading copies the source to `data/uploads/`; make sure disk space covers uploads, intermediate files, and outputs.

The program is intended for localhost use. It does not include NVIDIA's modified proprietary binaries and does not verify the trustworthiness of DLL files. Do not expose the server on a public network.
