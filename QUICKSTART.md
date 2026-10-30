# Framecraft quick start

See the [README](README.md) for the complete settings guide, rendering-character
comparison, requirements, and troubleshooting.

1. Install Python 3.12 or newer (below 3.15) and [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. For native rendering, use Windows 10/11, compatible GeForce RTX hardware,
   current drivers, and a trusted matching worker/model pair.
3. Download FFmpeg/ffprobe separately and obtain the native files from the
   compatible upstream distribution. Place them manually under the checkout:

   ```text
   runtime/nvngx.dll
   runtime/nvngx_dlssnr.dll
   bin/ffmpeg/bin/ffmpeg.exe
   bin/ffmpeg/bin/ffprobe.exe
   ```

   The video `nvngx.dll` is the special worker executable, not a generic driver
   DLL. Optional still-image previews additionally need `preview/dlssnr-image.exe`
   and `preview/caller/nvngx.dll`. See the [full placement instructions](README.md#download-and-place-the-external-files).
4. From the repository root, run:

   ```powershell
   uv sync --frozen
   uv run nvs doctor
   uv run nvs serve
   ```

5. Open **http://127.0.0.1:7860**. Add a short SDR video, select **Natural** in
   **Look**, choose **H.264 - Compatible (CQ20)** and **Source** FPS in **Export**,
   optionally enter `0-5` in **Cuts**, and click **Render with DLSS**.
6. For a completed job, watch the 12-second sample, download the full video, and
   inspect the JSON report. Stop the server with **Ctrl+C**.

The UI/API can run on Linux or without a GPU; the native Windows/D3D12 DLSS worker
cannot. Diagnostics passing does not prove inference works. Keep the server on
loopback: there is no authentication.
