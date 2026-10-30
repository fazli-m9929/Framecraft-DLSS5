from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .config import Settings
from .export_presets import selected_recipe
from .guides import MotionGuide
from .media import (effective_clips, exact_frame_count, mux_output, probe_video,
                    start_encoder, verify_export)
from .native import NeuralWorker, ProcessControl, RenderCancelled, hash_file
from .schemas import RenderOptions

ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class RenderResult:
    video: Path
    report: Path
    frames: int
    elapsed: float


def rgba_frame(frame, width: int, height: int, rotation: int) -> np.ndarray:
    image = frame.to_ndarray(format="rgba")
    # Some input decoders automatically apply rotation metadata; avoid double rotation.
    if rotation in (90, 270) and image.shape[:2] == (width, height):
        image = np.rot90(image, 3 if rotation == 90 else 1)
    elif rotation == 180:
        image = np.rot90(image, 2)
    if image.shape[:2] != (height, width):
        src_h, src_w = image.shape[:2]
        scale = min(width / src_w, height / src_h)
        resized_w = max(1, min(width, round(src_w * scale)))
        resized_h = max(1, min(height, round(src_h * scale)))
        resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_LANCZOS4)
        image = np.zeros((height, width, 4), dtype=np.uint8)
        image[..., 3] = 255
        x, y = (width - resized_w) // 2, (height - resized_h) // 2
        image[y:y+resized_h, x:x+resized_w] = resized
    return np.ascontiguousarray(image, dtype=np.uint8)


def clip_for_timestamp(seconds: float, clips: list[tuple[float, float]]) -> int | None:
    for i, (start, end) in enumerate(clips):
        if start <= seconds < end:
            return i
    return None


def frame_seconds(frame, index: int, input_tb: Fraction, rate: Fraction) -> float:
    if frame.pts is not None:
        return float(frame.pts * input_tb)
    return float(Fraction(index, 1) / rate)


def iter_clip_frames(
    container, stream, clips: list[tuple[float, float]],
    input_tb: Fraction, rate: Fraction,
    control: ProcessControl
):
    """Decode only requested time ranges, seeking over removed footage.

    Both the preliminary frame counter and native renderer use this iterator.
    This ensures the exact frame count in the worker header matches the frames
    subsequently submitted, even for variable-frame-rate footage and cuts
    between keyframes.
    """
    for clip_index, (start, end) in enumerate(clips):
        control.check()
        if start > 0:
            # PyAV seeks in stream time_base units; backward seeks to a keyframe.
            # Never use any_frame=True: decoding an inter-frame codec needs its
            # reference frames. Decode/discard the frames before the cut.
            seek_time_base = stream.time_base or input_tb
            seek_position = int(Fraction(str(start)) / seek_time_base)
            container.seek(seek_position, backward=True, any_frame=False, stream=stream)
        elif clip_index:
            container.seek(0, backward=True, any_frame=False, stream=stream)
        for frame_index, frame in enumerate(container.decode(stream)):
            control.check()
            seconds = frame_seconds(frame, frame_index, input_tb, rate)
            if seconds < start:
                continue
            if seconds >= end:
                break
            yield clip_index, frame, seconds


def count_clip_frames(
    source: Path, clips: list[tuple[float, float]],
    input_tb: Fraction, rate: Fraction, control: ProcessControl,
    progress: ProgressCallback | None = None
) -> int:
    """Count the exact frames consumed by DLSS, with progress and fast cut-seeking.

    The native worker expects an exact total in the initial header. This still
    decodes *selected* footage once beforehand, but no longer decodes removed
    footage or silently remains at 1% for the entire pass.
    """
    import av
    count = 0
    total_seconds = sum(end - start for start, end in clips)
    durations_before = [sum(end - start for start, end in clips[:i]) for i in range(len(clips))]
    with av.open(str(source)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        input_tb = stream.time_base or input_tb
        for clip_index, _frame, seconds in iter_clip_frames(
            container, stream, clips,
            input_tb, rate, control
        ):
            count += 1
            if progress and (count == 1 or count % 128 == 0):
                start, end = clips[clip_index]
                elapsed = durations_before[clip_index] + max(0., seconds - start)
                fraction = max(0., min(1., elapsed / total_seconds)) if total_seconds else 0.
                progress(
                    .01 + .075 * fraction,
                    f"Counting selected frames · clip {clip_index + 1}/{len(clips)} "
                    f"· {seconds:.1f}/{end:.1f}s · {count:,} frames"
                )
    if progress:
        progress(.09, f"Count complete · {count:,} selected frames")
    return count


def render_video(
    settings: Settings, source: Path, original_name: str, job_id: str,
    options: RenderOptions, progress: ProgressCallback,
    control: ProcessControl
) -> RenderResult:
    """Strict full-video feature-18 render. Never exposes a partial output as successful."""
    import av  # optional on diagnostics-only machines, required for rendering

    started = time.monotonic()
    control.check()
    progress(.005, "Reading source metadata")
    video = probe_video(settings, source)
    if video.duration <= 0:
        raise ValueError("Source duration is unavailable; cannot safely synchronize clips and audio")
    clips = effective_clips(options.clips, video.duration)
    if video.hdr:
        raise ValueError("HDR input is not supported: the native output is SDR RGBA8. Convert to SDR first.")
    control.check()
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(original_name).stem).strip("_")[:65] or "video"
    suffix = ".mkv" if options.container == "MKV" else ".mp4"
    target = settings.data / "outputs" / f"{safe_name}_{job_id[:10]}{suffix}"
    report_file = target.with_name(target.name + ".report.json")
    work = Path(tempfile.mkdtemp(prefix=f"{job_id[:8]}_", dir=settings.data / "scratch"))
    staged = work / ("processed" + ".mkv")
    muxed = work / ("final" + suffix)
    worker = None
    encoder = None
    decode_container = None
    nut_container = None
    frames = 0
    cuts = 0
    expected_native_frames = video.frame_count
    result: RenderResult | None = None
    try:
        if options.clips:
            progress(.01, "Counting selected frames for native renderer")
            expected_native_frames = count_clip_frames(
                source, clips, video.time_base,
                video.frame_rate, control, progress
            )
            if not expected_native_frames:
                raise ValueError("The chosen segments contain no video frames")
        progress(
            .10 if options.clips else .02,
            f"Starting native feature-18 renderer ({video.width}×{video.height})"
        )
        worker = NeuralWorker(
            settings, video.width, video.height, expected_native_frames,
            options.warmup_frames, options.native(), control
        )
        encoder, encoder_log, encoder_name = start_encoder(settings, staged, options, control)
        if encoder.stdin is None:
            raise RuntimeError("FFmpeg input pipe unavailable")
        nut_container = av.open(encoder.stdin, mode="w", format="nut")
        decode_container = av.open(str(source))
        stream = decode_container.streams.video[0]
        stream.thread_type = "AUTO"
        rate = stream.average_rate or video.frame_rate
        raw = nut_container.add_stream("rawvideo", rate=rate)
        raw.width, raw.height = video.width, video.height
        raw.pix_fmt = "rgba"
        output_tb = Fraction(1, rate)
        input_tb = stream.time_base or video.time_base
        raw.time_base = output_tb
        guide = MotionGuide(video.width, video.height)
        last_pts = -1
        previous_clip = None
        durations_before = [sum(end - start for start, end in clips[:i]) for i in range(len(clips))]
        if options.clips:
            selected_frames = iter_clip_frames(
                decode_container, stream, clips,
                input_tb, video.frame_rate, control
            )
        else:
            selected_frames = (
                (0, frame, frame_seconds(frame, source_index, input_tb, video.frame_rate))
                for source_index, frame in enumerate(decode_container.decode(stream))
            )
        for clip_index, frame, seconds in selected_frames:
            control.check()
            if previous_clip is not None and clip_index != previous_clip:
                # A hard edit must never carry optical-flow history across the cut.
                guide.previous = None
            previous_clip = clip_index
            image = rgba_frame(frame, video.width, video.height, video.rotation)
            motion = guide.process(image)
            cuts += int(motion.reset and frames != 0)
            pts = int(frame.pts if frame.pts is not None else frames)
            rendered, native_pts = worker.process_frame(frames, image, motion.motion, motion.reset, pts)
            out = av.VideoFrame.from_ndarray(rendered, format="rgba")
            if options.clips or selected_recipe(options.export_preset) is not None:
                # Cut from source PTS, then remap intervals into one gapless timeline.
                # Also normalize the HEVC preset's full-source PTS to zero for AAC sync.
                start, _ = clips[clip_index]
                output_time = durations_before[clip_index] + (seconds - start)
                output_pts = round(output_time * float(rate))
            else:
                # Preserve original time base for full-length rendering.
                output_pts = (round(Fraction(native_pts) * input_tb / output_tb) if native_pts >= 0 else last_pts + 1)
            output_pts = max(last_pts + 1, output_pts)
            last_pts = output_pts
            out.pts, out.time_base = output_pts, output_tb
            for packet in raw.encode(out):
                nut_container.mux(packet)
            frames += 1
            if frames == 1 or frames % 5 == 0 or frames == expected_native_frames:
                progress(
                    (.10 if options.clips else .04)
                    + (.78 if options.clips else .82) * min(1, frames / expected_native_frames),
                    f"Neural rendering · {frames:,} / {expected_native_frames:,} frames"
                )
        if frames != expected_native_frames:
            raise RuntimeError(f"Decoded {frames} selected frames; expected {expected_native_frames}")
        for packet in raw.encode():
            nut_container.mux(packet)
        nut_container.close()
        nut_container = None
        if encoder.stdin and not encoder.stdin.closed:
            encoder.stdin.close()
        decode_container.close()
        decode_container = None
        worker.finish()
        worker_log = list(worker.log.lines)
        control.check()
        try:
            encoder_rc = encoder.wait(timeout=180)
        except Exception:
            control.stop()
            raise
        encoder_log.thread.join(timeout=2)
        control.remove(encoder)
        if encoder_rc:
            raise RuntimeError("Video encoder failed:\n" + encoder_log.tail())
        if not staged.is_file() or staged.stat().st_size == 0:
            raise RuntimeError("Encoder produced no video")
        progress(.90, "Muxing original audio and metadata")
        mux_output(settings, staged, source, muxed, options, control, clips, video.has_audio)
        control.check()
        progress(.96, "Verifying output frame count")
        output_count = exact_frame_count(settings, muxed)
        if options.target_fps == "Source" and output_count != frames:
            raise RuntimeError(f"Output verification failed: expected {frames}, got {output_count}")
        if options.target_fps == "60" and output_count < 1:
            raise RuntimeError("60 FPS encoder produced no frames")
        export_probe = verify_export(settings, muxed, options, video.has_audio)
        expected_duration = sum(end - start for start, end in clips)
        real_duration = float((export_probe.get("format") or {}).get("duration") or 0)
        # MP4/AAC duration rounding can differ by several audio samples / one video frame.
        if abs(real_duration - expected_duration) > max(0.15, expected_duration * 0.0002):
            raise RuntimeError(f"Output duration mismatch: expected ~{expected_duration:.3f}s, got {real_duration:.3f}s")
        if worker.evaluations != frames:
            raise RuntimeError("Not all frames have feature-18 success evidence")
        if worker.log.direct_create_result != "0x00000001":
            raise RuntimeError("Missing feature-18 creation success evidence")
        control.check()
        # Commit only fully validated files. Reports cannot claim success until this point.
        elapsed = round(time.monotonic() - started, 2)
        report_data = {
            "status": "success", "pipeline": "dlssnr-native-feature-18", "feature_id": 18,
            "job_id": job_id, "source_filename": original_name,
            "output_filename": target.name, "options": options.model_dump(mode="json"),
            "native_settings": options.native(), "video": video.to_dict(),
            "frames_processed": frames, "frames_encoded": output_count,
            "selected_segments": [{"start": start, "end": end} for start, end in clips],
            "export_probe": export_probe,
            "frames_verified": output_count,
            "successful_direct_evaluations": worker.evaluations,
            "feature_18_confirmed": True,
            "direct_create_result": worker.log.direct_create_result,
            "model_sha256": hash_file(settings.model), "worker_sha256": hash_file(settings.worker),
            "encoder": encoder_name, "scene_resets": cuts, "elapsed_seconds": elapsed,
            "average_fps": round(frames / max(elapsed, 0.001), 3),
            "worker_log_tail": worker_log[-120:], "encoder_log_tail": list(encoder_log.lines)[-120:],
            "note": "Estimated optical flow, not game-engine motion vectors; SDR RGBA8.",
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        muxed.replace(target)
        try:
            report_file.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            target.unlink(missing_ok=True)
            raise
        progress(1.0, "Complete · native feature 18 confirmed")
        result = RenderResult(target, report_file, frames, elapsed)
        return result
    except Exception as exc:
        if control.cancelled.is_set():
            raise RenderCancelled("Render cancelled") from exc
        # If FFmpeg died while PyAV was still writing, expose the real NVENC
        # error instead of a generic broken-pipe / invalid-packet exception.
        if encoder is not None and encoder.poll() not in (None, 0):
            encoder_log.thread.join(timeout=2)
            details = encoder_log.tail()
            if details:
                raise RuntimeError("FFmpeg encoder failed:\n" + details) from exc
        raise
    finally:
        if nut_container is not None:
            try: nut_container.close()
            except Exception: pass
        if decode_container is not None:
            try: decode_container.close()
            except Exception: pass
        if worker is not None:
            worker.abort()
        if encoder is not None:
            if encoder.poll() is None:
                ProcessControl._terminate(encoder)
                try: encoder.wait(timeout=3)
                except Exception: encoder.kill()
            control.remove(encoder)
        if result is None:
            target.unlink(missing_ok=True)
            report_file.unlink(missing_ok=True)
        shutil.rmtree(work, ignore_errors=True)
