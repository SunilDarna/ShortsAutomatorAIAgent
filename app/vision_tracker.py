"""
vision_tracker.py — Phase 2: MediaPipe Subject-Aware Dynamic Cropping
Replaces static center-cropping with real-time face tracking.
Outputs smoothed crop coordinates and pillarboxing FFmpeg commands.
"""
import os
import json
import subprocess
import tempfile
from collections import deque
from typing import Optional, Tuple

# Attempt to import MediaPipe; gracefully degrade if not installed.
try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


# ──────────────── Constants ────────────────────────────────────────────────────

TARGET_W = 1080
TARGET_H = 1920
ASPECT_RATIO = TARGET_W / TARGET_H          # 9:16
SMOOTH_WINDOW = 10                           # 10-frame moving average
DEAD_ZONE_PCT = 0.05                        # 5% dead-zone to prevent micro-jitter


# ──────────────── Coordinate Smoother ─────────────────────────────────────────

class CoordinateSmoother:
    """
    Low-pass filter using a sliding window moving average.
    Prevents micro-jitter by only updating crop position when subject
    moves beyond the dead zone threshold.
    """

    def __init__(self, window: int = SMOOTH_WINDOW, dead_zone: float = DEAD_ZONE_PCT):
        self._cx = deque(maxlen=window)
        self._cy = deque(maxlen=window)
        self._last_cx: Optional[float] = None
        self._last_cy: Optional[float] = None
        self.dead_zone = dead_zone

    def update(self, cx_norm: float, cy_norm: float):
        """Feed a new normalized center coordinate into the smoother."""
        self._cx.append(cx_norm)
        self._cy.append(cy_norm)

    def get_smoothed(self) -> Tuple[float, float]:
        """Return the smoothed (cx, cy) normalized coordinates."""
        if not self._cx:
            return 0.5, 0.4  # Default: center-upper frame

        new_cx = sum(self._cx) / len(self._cx)
        new_cy = sum(self._cy) / len(self._cy)

        # Apply dead-zone: don't move the crop unless displacement exceeds threshold
        if self._last_cx is not None:
            delta = ((new_cx - self._last_cx) ** 2 + (new_cy - self._last_cy) ** 2) ** 0.5
            if delta < self.dead_zone:
                return self._last_cx, self._last_cy

        self._last_cx = new_cx
        self._last_cy = new_cy
        return new_cx, new_cy


# ──────────────── Frame Extraction ────────────────────────────────────────────

def _extract_frames(video_path: str, sample_every: int = 5) -> list:
    """
    Extract frames from video at a given sampling rate using OpenCV.
    Returns list of (frame_index, frame_bgr) tuples.
    """
    if not CV2_AVAILABLE:
        return []

    cap = cv2.VideoCapture(video_path)
    frames = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % sample_every == 0:
            frames.append((idx, frame))
        idx += 1
    cap.release()
    return frames


# ──────────────── MediaPipe Face Detection ─────────────────────────────────────

def _detect_faces_mediapipe(frame_bgr) -> Optional[Tuple[float, float, float, float]]:
    """
    Run BlazeFace detection on a single frame.
    Returns (cx_norm, cy_norm, w_norm, h_norm) for the primary face bounding box,
    or None if no face is detected.

    Landmark 3 = Mouth Center — used as the speaker priority anchor.
    """
    if not MEDIAPIPE_AVAILABLE or not CV2_AVAILABLE:
        return None

    try:
        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w = frame_rgb.shape[:2]

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        # Use the legacy FaceMesh for landmark-level access
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=0.5
        ) as detector:
            results = detector.process(frame_rgb)

        if not results.detections:
            return None

        # Pick the detection with the highest confidence
        best = max(results.detections, key=lambda d: d.score[0])
        bbox = best.location_data.relative_bounding_box

        cx_norm = bbox.xmin + bbox.width / 2.0
        cy_norm = bbox.ymin + bbox.height / 2.0

        # Use Landmark 3 (Mouth Center) as the anchor if available
        kps = best.location_data.relative_keypoints
        if len(kps) > 3:
            cx_norm = kps[3].x  # Mouth Center X
            cy_norm = kps[3].y  # Mouth Center Y

        return cx_norm, cy_norm, bbox.width, bbox.height

    except Exception as e:
        return None


# ──────────────── Crop Command Generation ─────────────────────────────────────

def _norm_to_crop(cx_norm: float, cy_norm: float,
                  src_w: int, src_h: int) -> Tuple[int, int, int, int]:
    """
    Convert normalized subject center to a pixel-precise crop rectangle
    that extracts the maximum area fitting the 9:16 aspect ratio.

    Returns (crop_w, crop_h, x_offset, y_offset) in pixel space.
    """
    # The crop width is limited by the source width or 9:16 of source height
    crop_h = src_h
    crop_w = int(crop_h * ASPECT_RATIO)

    if crop_w > src_w:
        # Source is too narrow — use full width and crop height instead
        crop_w = src_w
        crop_h = int(crop_w / ASPECT_RATIO)

    # Center the crop on the subject
    cx_px = int(cx_norm * src_w)
    cy_px = int(cy_norm * src_h)

    x = cx_px - crop_w // 2
    y = cy_px - crop_h // 2

    # Clamp to frame boundaries
    x = max(0, min(x, src_w - crop_w))
    y = max(0, min(y, src_h - crop_h))

    return crop_w, crop_h, x, y


# ──────────────── FFmpeg Filter Builders ──────────────────────────────────────

def build_pillarbox_filter(cx_norm: float = 0.5, cy_norm: float = 0.4) -> str:
    """
    Build the FFmpeg complex filter string for echo pillarboxing.
    Uses a single-pass split to avoid re-reading the source file.

    The background is a Gaussian-blurred (sigma=20) scaled copy of the source.
    The foreground is the sharp, cropped subject centered on the 9:16 canvas.

    Returns the -vf filter string.
    """
    blur_sigma = 20

    # The foreground: scale to fit within 1080 width maintaining aspect ratio
    fg_scale = f"scale={TARGET_W}:-1"

    filter_str = (
        f"split[original][copy];"
        f"[copy]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},"
        f"gblur=sigma={blur_sigma}[blurred];"
        f"[original]{fg_scale}[fg];"
        f"[blurred][fg]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2"
    )
    return filter_str


def build_dynamic_crop_filter(crop_coords: list) -> str:
    """
    Build an FFmpeg sendcmd-compatible crop filter from a list of
    (timestamp_sec, crop_w, crop_h, x, y) tuples.

    Falls back to static pillarbox if no coords provided.
    """
    if not crop_coords:
        return build_pillarbox_filter()

    # Build a sendcmd script for dynamic cropping
    cmd_lines = []
    for ts, cw, ch, cx, cy in crop_coords:
        cmd_lines.append(f"{ts} crop w {cw}, crop h {ch}, crop x {cx}, crop y {cy};")

    sendcmd_script = "\n".join(cmd_lines)

    # Write to temp file for FFmpeg consumption
    tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w")
    tmp.write(sendcmd_script)
    tmp.flush()
    tmp.close()

    filter_str = (
        f"crop={crop_coords[0][1]}:{crop_coords[0][2]}:{crop_coords[0][3]}:{crop_coords[0][4]},"
        f"sendcmd=f={tmp.name},"
        f"scale={TARGET_W}:{TARGET_H}"
    )
    return filter_str, tmp.name


# ──────────────── Main Public Interface ───────────────────────────────────────

def get_tracking_filter(video_path: str) -> str:
    """
    Analyze a source video clip to compute subject-tracking crop coordinates.
    Returns the optimal FFmpeg video filter string.

    Falls back to static pillarbox if MediaPipe or OpenCV are unavailable,
    or if no faces are detected in the sampled frames.
    """
    if not MEDIAPIPE_AVAILABLE or not CV2_AVAILABLE:
        print("Vision Tracker: MediaPipe/OpenCV not available. Using static pillarbox.")
        return build_pillarbox_filter()

    print("Vision Tracker: Analyzing subject position across frames...")

    frames = _extract_frames(video_path, sample_every=5)
    if not frames:
        print("Vision Tracker: No frames extracted. Using static pillarbox.")
        return build_pillarbox_filter()

    # Get source resolution
    cap = cv2.VideoCapture(video_path)
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()

    smoother = CoordinateSmoother(window=SMOOTH_WINDOW, dead_zone=DEAD_ZONE_PCT)
    detection_count = 0
    crop_coords = []

    for frame_idx, frame in frames:
        result = _detect_faces_mediapipe(frame)
        if result:
            cx_n, cy_n, _, _ = result
            smoother.update(cx_n, cy_n)
            detection_count += 1
        
        # Always get a smoothed coordinate (uses default if no detections yet)
        cx_s, cy_s = smoother.get_smoothed()
        cw, ch, cx_px, cy_px = _norm_to_crop(cx_s, cy_s, src_w, src_h)
        timestamp_sec = frame_idx / fps
        crop_coords.append((timestamp_sec, cw, ch, cx_px, cy_px))

    if detection_count == 0:
        print("Vision Tracker: No faces detected. Using centered pillarbox.")
        return build_pillarbox_filter()

    detection_rate = detection_count / len(frames)
    print(f"Vision Tracker: Detected subjects in {detection_rate:.0%} of sampled frames.")

    if detection_rate < 0.3:
        # Too few detections — pillarbox is more reliable
        print("Vision Tracker: Low detection rate. Falling back to pillarbox.")
        return build_pillarbox_filter()

    # Build a static crop using the median position for stability
    # (Full sendcmd dynamic cropping is reserved for future GPU-accelerated builds)
    cx_median = sorted(crop_coords, key=lambda x: x[3])[len(crop_coords) // 2]
    _, cw, ch, cx_px, cy_px = cx_median

    print(f"Vision Tracker: Locking crop at ({cx_px}, {cy_px}), size {cw}x{ch}.")

    # Build pillarbox with subject-centered foreground
    subject_cx_norm = (cx_px + cw / 2) / src_w
    subject_cy_norm = (cy_px + ch / 2) / src_h

    blur_sigma = 20
    fg_crop = f"crop={cw}:{ch}:{cx_px}:{cy_px},scale={TARGET_W}:{TARGET_H}"

    filter_str = (
        f"split[original][copy];"
        f"[copy]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},"
        f"gblur=sigma={blur_sigma}[blurred];"
        f"[original]{fg_crop}[fg];"
        f"[blurred][fg]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2"
    )
    return filter_str
