from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .config import Settings
from .export_presets import selected_recipe
from .native import ProcessControl, ProcessLog
from .schemas import Clip, RenderOptions


@dataclass(frozen=True, slots=True)
class VideoInfo:
    width: int
    height: int
    rotation: int
    frame_count: int
    frame_rate: Fraction
    time_base: Fraction
    duration: float
    hdr: bool
    has_audio: bool

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height, "rotation": self.rotation,
                "frames": self.frame_count, "fps": float(self.frame_rate),
                "duration": self.duration, "hdr": self.hdr, "has_audio": self.has_audio}


def run_command(command: list[str], *, timeout: int | None = 180) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out: {command[0]}") from exc


def ffprobe(settings: Settings, args: list[str], *, timeout: int = 300) -> dict:
    exe = settings.resolve_command("ffprobe")
    if not exe:
        raise RuntimeError("ffprobe not found")
    proc = run_command([str(exe), "-v", "error", *args, "-of", "json"], timeout=timeout)
    if proc.returncode:
        raise RuntimeError("ffprobe failed: " + proc.stderr[-1200:])
    return json.loads(proc.stdout)


def probe_video(settings: Settings, video: Path) -> VideoInfo:
    info = ffprobe(settings, ["-show_entries",
        "stream=codec_type,width,height,avg_frame_rate,r_frame_rate,time_base,nb_frames,color_transfer:stream_tags=rotate:stream_side_data=rotation:format=duration",
        str(video)])
    streams = info.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not video_stream:
        raise ValueError("File does not contain a video stream")
    rotation = int((video_stream.get("tags") or {}).get("rotate", 0) or 0)
    for entry in video_stream.get("side_data_list") or []:
        if "rotation" in entry:
            rotation = int(entry["rotation"])
    rotation %= 360
    width, height = int(video_stream["width"]), int(video_stream["height"])
    if rotation in (90, 270):
        width, height = height, width
    if width <= 0 or height <= 0:
        raise ValueError("Invalid video dimensions")
    count = int(video_stream.get("nb_frames") or 0)
    if count <= 0:
        exact = ffprobe(settings, ["-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_frames", str(video)], timeout=3600)
        count = int((exact.get("streams") or [{}])[0].get("nb_read_frames") or 0)
    if count <= 0:
        raise ValueError("Could not determine source frame count")
    rate_text = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "30/1"
    rate = Fraction(rate_text) if rate_text != "0/0" else Fraction(30, 1)
    if rate <= 0:
        raise ValueError("Invalid video framerate")
    return VideoInfo(
        width=width, height=height, rotation=rotation, frame_count=count,
        frame_rate=rate, time_base=Fraction(video_stream.get("time_base") or "1/1000"),
        duration=float((info.get("format") or {}).get("duration") or 0),
        hdr=video_stream.get("color_transfer") in {"smpte2084", "arib-std-b67"},
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def exact_frame_count(settings: Settings, path: Path) -> int:
    result = ffprobe(settings, ["-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames", str(path)], timeout=3600)
    return int((result.get("streams") or [{}])[0].get("nb_read_frames") or 0)


def encoder_available(settings: Settings, encoder: str, *, main10: bool = False) -> bool:
    """Check that FFmpeg was compiled with an encoder, not whether a tiny
    synthetic NVENC job happens to work. The actual job validates the GPU.

    The previous 64x64/1fps probe produced false negatives on RTX machines.
    main10 remains for backward-compatible callers; it is not simulated here.
    """
    exe = settings.resolve_command("ffmpeg")
    if not exe:
        return False
    proc = run_command([str(exe), "-hide_banner", "-encoders"], timeout=30)
    if proc.returncode:
        return False
    return re.search(r"^\s*V\S*\s+" + re.escape(encoder) + r"\s", proc.stdout, re.M) is not None


def encoder_args(settings: Settings, options: RenderOptions) -> tuple[list[str], str]:
    recipe = selected_recipe(options.export_preset)
    if recipe is not None:
        if not encoder_available(settings, recipe.encoder):
            raise RuntimeError(
                f"FFmpeg does not provide {recipe.encoder}. Check the FFmpeg build "
                "selected by NVS_FFMPEG."
            )
        args = ["-c:v", recipe.encoder, "-preset", recipe.preset, "-tune", "hq",
                "-rc", "vbr", "-cq", str(recipe.cq), "-b:v", "0",
                "-pix_fmt", recipe.pix_fmt]
        if recipe.main10:
            args.extend(["-profile:v", "main10"])
        # Never put -tag:v hvc1 in the *intermediate MKV*. Set it on final MP4.
        return args, recipe.encoder

    cq = {"High": "17", "Balanced": "20", "Small": "24"}.get(options.quality)
    names = {
        "H.264": ("h264_nvenc", "libx264"),
        "HEVC": ("hevc_nvenc", "libx265"), "AV1": ("av1_nvenc", None)
    }
    nvenc, cpu = names[options.codec]
    if encoder_available(settings, nvenc):
        if options.quality == "Lossless":
            return ["-c:v", nvenc, "-preset", "p6", "-tune", "lossless", "-pix_fmt", "yuv444p"], nvenc
        return [
            "-c:v", nvenc, "-preset", "p6", "-tune", "hq", "-rc", "vbr",
            "-cq", cq, "-b:v", "0", "-pix_fmt", "yuv420p"
        ], nvenc
    if cpu is None:
        raise RuntimeError("AV1 needs av1_nvenc support in your FFmpeg build")
    if not encoder_available(settings, cpu):
        raise RuntimeError(f"No encoder available for {options.codec}")
    if options.quality == "Lossless":
        return ["-c:v", cpu, "-preset", "slow", "-crf", "0", "-pix_fmt", "yuv444p"], cpu
    return ["-c:v", cpu, "-preset", "slow", "-crf", cq, "-pix_fmt", "yuv420p"], cpu


def start_encoder(
    settings: Settings, path: Path, options: RenderOptions,
    control: ProcessControl
) -> tuple[subprocess.Popen, ProcessLog, str]:
    exe = settings.resolve_command("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found")
    args, name = encoder_args(settings, options)
    video_filters = (["-vf", "fps=60"] if options.target_fps == "60" else [])
    fps_mode = "cfr" if options.target_fps == "60" else "passthrough"
    command = [
        str(exe), "-hide_banner", "-loglevel", "warning", "-y", "-f", "nut",
        "-i", "pipe:0", "-map", "0:v:0", "-an", *video_filters, *args,
        "-fps_mode", fps_mode, str(path)
    ]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    control.add(proc)
    return proc, ProcessLog(proc), name


def effective_clips(clips: list[Clip], duration: float) -> list[tuple[float, float]]:
    """Return validated, half-open clips. Empty clips means complete source."""
    if not clips:
        return [(0., duration)]
    result: list[tuple[float, float]] = []
    for clip in clips:
        end = duration if clip.end is None else clip.end
        if end > duration + 0.1 or clip.start >= duration or end <= clip.start:
            raise ValueError(f"Clip [{clip.start}, {end}) is outside video duration {duration:.3f}s")
        result.append((clip.start, min(end, duration)))
    return result


def audio_filter(clips: list[tuple[float, float]]) -> str:
    """Use exactly the selected source intervals for audio, including sample-accurate trimming."""
    nodes = []
    for i, (start, end) in enumerate(clips):
        nodes.append(f"[1:a:0]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{i}]")
    labels = "".join(f"[a{i}]" for i in range(len(clips)))
    if len(clips) == 1:
        nodes.append(f"{labels}aresample=async=1:first_pts=0,apad[a]")
    else:
        nodes.append(f"{labels}concat=n={len(clips)}:v=0:a=1,aresample=async=1:first_pts=0,apad[a]")
    return ";".join(nodes)


def mux_output(
    settings: Settings, processed: Path, original: Path, final: Path,
    options: RenderOptions, control: ProcessControl,
    clips: list[tuple[float, float]], has_audio: bool
) -> None:
    exe = settings.resolve_command("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg unavailable")
    cmd = [
        str(exe), "-hide_banner", "-loglevel", "warning", "-y",
        "-i", str(processed), "-i", str(original)
    ]
    recipe = selected_recipe(options.export_preset)
    if recipe is not None:
        # Already encoded video: only copy video into final MP4, without quality loss.
        cmd += ["-map", "0:v:0", "-c:v", "copy"]
        if recipe.codec == "HEVC":
            cmd += ["-tag:v", "hvc1"]
        if has_audio:
            cmd += ["-filter_complex", audio_filter(clips), "-map", "[a]",
                    "-c:a", "aac", "-b:a", recipe.audio_bitrate,
                    "-ar", str(recipe.audio_rate), "-shortest"]
        cmd += ["-movflags", "+faststart", "-use_editlist", "0"]
    elif options.clips:
        cmd += ["-map", "0:v:0", "-c:v", "copy"]
        if has_audio:
            cmd += ["-filter_complex", audio_filter(clips), "-map", "[a]",
                    "-c:a", "aac", "-b:a", "192k", "-shortest"]
        if options.container == "MP4":
            cmd += ["-movflags", "+faststart"]
    elif options.container == "MKV":
        cmd += ["-map", "0:v:0", "-map", "1:a?", "-map", "1:s?", "-c:v", "copy",
                "-c:a", "copy", "-c:s", "copy"]
    else:
        cmd += ["-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", "-c:a", "aac",
                "-b:a", "192k", "-movflags", "+faststart"]
    cmd += ["-map_metadata", "1"]
    if not options.clips:
        cmd += ["-map_chapters", "1"]
    else:
        cmd += ["-map_chapters", "-1"]
    cmd += [str(final)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    control.add(proc)
    logs = ProcessLog(proc)
    try:
        rc = proc.wait(timeout=3600)
        logs.thread.join(timeout=2)
        control.check()
        if rc:
            raise RuntimeError("Audio/metadata mux failed:\n" + logs.tail())
    finally:
        control.remove(proc)


def verify_export(
    settings: Settings, path: Path, options: RenderOptions,
    expected_audio: bool
) -> dict:
    """Check actual file metadata; never trust extension/command arguments alone."""
    result = ffprobe(settings, ["-show_entries",
        "stream=codec_type,codec_name,profile,pix_fmt,sample_rate,avg_frame_rate,duration:format=duration",
        str(path)])
    streams = result.get("streams", [])
    vs = next((s for s in streams if s.get("codec_type") == "video"), None)
    au = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not vs:
        raise RuntimeError("Final file has no video stream")
    if expected_audio and not au:
        raise RuntimeError("Final file lost the audio stream")
    recipe = selected_recipe(options.export_preset)
    if recipe is not None:
        codec_name = {"HEVC": "hevc", "H.264": "h264", "AV1": "av1"}[recipe.codec]
        expected_pix_fmt = "yuv420p10le" if recipe.main10 else "yuv420p"
        if vs.get("codec_name") != codec_name or vs.get("pix_fmt") != expected_pix_fmt:
            raise RuntimeError(f"Expected {recipe.codec} / {expected_pix_fmt}, got {vs}")
        if expected_audio and (au.get("codec_name") != "aac" or au.get("sample_rate") != str(recipe.audio_rate)):
            raise RuntimeError(f"Expected {recipe.audio_rate} Hz AAC audio, got {au}")
    if options.target_fps == "60":
        rate = Fraction(vs.get("avg_frame_rate") or "0/1")
        if not (59.95 <= float(rate) <= 60.05):
            raise RuntimeError(f"Output not 60 fps: {rate}")
    return result
