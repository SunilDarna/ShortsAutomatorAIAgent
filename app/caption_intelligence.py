"""
caption_intelligence.py — burned-in caption heuristics and render QA.

This avoids blindly stacking generated captions on source footage that already
contains subtitles. The detector is intentionally lightweight: it uses OpenCV
when available, and degrades to safe defaults when not available.
"""
import json
import os
import subprocess
import tempfile
from typing import Dict, List

try:
    import cv2
    import numpy as np
    CV_AVAILABLE = True
except Exception:
    CV_AVAILABLE = False


def _ffmpeg_bin() -> str:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_bin = os.path.join(project_root, "node_modules/@ffmpeg-installer/darwin-arm64/ffmpeg")
    return local_bin if os.path.exists(local_bin) else "ffmpeg"


def _ffprobe_bin() -> str:
    ffmpeg = _ffmpeg_bin()
    if ffmpeg.endswith("/ffmpeg"):
        probe = ffmpeg[:-len("ffmpeg")] + "ffprobe"
        if os.path.exists(probe):
            return probe
    return "ffprobe"


def _subtitle_band_score(frame, y0: int, y1: int) -> Dict:
    h, w = frame.shape[:2]
    crop = frame[y0:y1, int(w * 0.08):int(w * 0.92)]
    if crop.size == 0:
        return {
            "subtitle_like": False,
            "confidence": 0.0,
            "component_count": 0,
            "line_count": 0,
            "coverage": 0.0,
            "large_component_ratio": 0.0,
        }

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    bright = cv2.inRange(gray, 190, 255)
    dark = cv2.inRange(gray, 0, 65)
    # Captions are usually compact high-contrast glyphs. Post screenshots have
    # larger dense blocks, many rows, and wide text columns.
    mask = cv2.bitwise_or(bright, dark)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 2))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    components = []
    large_components = 0
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cw * ch
        if area < 12:
            continue
        if ch > crop.shape[0] * 0.45 or cw > crop.shape[1] * 0.75:
            large_components += 1
            continue
        if 4 <= ch <= 70 and 2 <= cw <= crop.shape[1] * 0.45:
            components.append((x, y, cw, ch))

    if not components:
        return {
            "subtitle_like": False,
            "confidence": 0.0,
            "component_count": 0,
            "line_count": 0,
            "coverage": 0.0,
            "large_component_ratio": 1.0 if large_components else 0.0,
        }

    ys = sorted(y + ch / 2 for _, y, _, ch in components)
    line_buckets = []
    for y in ys:
        if not line_buckets or abs(line_buckets[-1][-1] - y) > 18:
            line_buckets.append([y])
        else:
            line_buckets[-1].append(y)

    x_min = min(x for x, _, _, _ in components)
    x_max = max(x + cw for x, _, cw, _ in components)
    y_min = min(y for _, y, _, _ in components)
    y_max = max(y + ch for _, y, _, ch in components)
    bbox_w = x_max - x_min
    bbox_h = y_max - y_min
    coverage = float(cv2.countNonZero(mask)) / max(mask.size, 1)
    center_x = (x_min + x_max) / 2
    centered = abs(center_x - crop.shape[1] / 2) < crop.shape[1] * 0.28
    compact_height = bbox_h <= crop.shape[0] * 0.65
    compact_lines = 1 <= len(line_buckets) <= 3
    enough_glyphs = 8 <= len(components) <= 220
    reasonable_width = crop.shape[1] * 0.12 <= bbox_w <= crop.shape[1] * 0.86
    sparse_enough = 0.004 <= coverage <= 0.18
    large_ratio = large_components / max(len(components) + large_components, 1)

    confidence = 0.0
    confidence += 0.18 if centered else 0.0
    confidence += 0.18 if compact_height else 0.0
    confidence += 0.18 if compact_lines else 0.0
    confidence += 0.16 if enough_glyphs else 0.0
    confidence += 0.15 if reasonable_width else 0.0
    confidence += 0.15 if sparse_enough else 0.0
    confidence -= min(0.35, large_ratio * 0.5)

    return {
        "subtitle_like": confidence >= 0.72,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "component_count": len(components),
        "line_count": len(line_buckets),
        "coverage": round(coverage, 4),
        "large_component_ratio": round(large_ratio, 3),
    }


def detect_burned_in_captions(video_path: str, start_seconds: float = 0.0,
                              duration: float = 45.0, samples: int = 7) -> Dict:
    """
    Detect likely source captions by looking for dense high-contrast text-like
    edges in the lower and center video bands.
    """
    result = {
        "burned_in_captions": False,
        "confidence": 0.0,
        "caption_zone": "none",
        "samples_checked": 0,
    }
    if not CV_AVAILABLE or not os.path.exists(video_path):
        result["reason"] = "opencv_unavailable_or_missing_video"
        return result

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        result["reason"] = "video_open_failed"
        return result

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    video_duration = frame_count / fps if frame_count else duration
    actual_duration = min(duration, max(video_duration - start_seconds, 1.0))
    offsets = [
        start_seconds + (actual_duration * (idx + 1) / (samples + 1))
        for idx in range(samples)
    ]

    zone_hits = {"subtitle": 0}
    confidences: List[float] = []
    diagnostics = []
    checked = 0

    for ts in offsets:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(ts, 0) * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        checked += 1
        h, w = frame.shape[:2]
        # Only inspect the subtitle-safe band. Center text is usually slides,
        # screenshots, charts, or post content, not captions.
        band = _subtitle_band_score(frame, int(h * 0.68), int(h * 0.88))
        diagnostics.append(band)
        confidences.append(band["confidence"])
        if band["subtitle_like"]:
            zone_hits["subtitle"] += 1

    cap.release()
    result["samples_checked"] = checked
    if checked == 0:
        result["reason"] = "no_frames_sampled"
        return result

    strongest_zone = "subtitle"
    confidence = sum(confidences) / max(len(confidences), 1)
    required_hits = max(3, int(checked * 0.6))
    result.update({
        "burned_in_captions": zone_hits[strongest_zone] >= required_hits,
        "confidence": round(confidence, 3),
        "caption_zone": "lower" if zone_hits[strongest_zone] else "none",
        "subtitle_like_frames": zone_hits[strongest_zone],
        "required_hits": required_hits,
        "diagnostics": diagnostics[:5],
    })
    return result


def choose_caption_strategy(detection: Dict) -> Dict:
    if detection.get("burned_in_captions"):
        return {
            "render_generated_captions": False,
            "caption_zone": detection.get("caption_zone", "lower"),
            "reason": "source_already_has_captions",
        }
    return {
        "render_generated_captions": True,
        "caption_zone": "lower",
        "reason": "no_source_captions_detected",
    }


def probe_video(output_path: str) -> Dict:
    probe = _ffprobe_bin()
    cmd = [
        probe,
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout or "{}")
    except Exception as exc:
        return {"error": str(exc)}


def run_render_qa(output_path: str, expected_min_duration: float = 30.0,
                  expected_max_duration: float = 60.5,
                  burned_in_captions: bool = False,
                  caption_zone: str = "none") -> Dict:
    data = probe_video(output_path)
    warnings = []
    width = height = 0
    duration = 0.0
    has_audio = False

    if "error" in data:
        warnings.append(f"ffprobe_failed:{data['error']}")
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 0) or 0)
            height = int(stream.get("height", 0) or 0)
            duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
        elif stream.get("codec_type") == "audio":
            has_audio = True

    if width != 1080 or height != 1920:
        warnings.append(f"unexpected_dimensions:{width}x{height}")
    if not (expected_min_duration <= duration <= expected_max_duration):
        warnings.append(f"duration_out_of_range:{duration:.2f}")
    if not has_audio:
        warnings.append("missing_audio")
    if burned_in_captions:
        warnings.append(f"source_caption_detected:{caption_zone}")

    blocking = [
        item for item in warnings
        if item.startswith("ffprobe_failed")
        or item.startswith("unexpected_dimensions")
        or item.startswith("duration_out_of_range")
        or item == "missing_audio"
    ]
    return {
        "width": width,
        "height": height,
        "duration": round(duration, 2),
        "has_audio": has_audio,
        "burned_in_captions": burned_in_captions,
        "caption_zone": caption_zone,
        "warnings": warnings,
        "passed": not blocking,
    }
