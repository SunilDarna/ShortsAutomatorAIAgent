"""
video_processor.py — Phase 2: Subject-Aware Video Processing
v2.0 — Integrates vision_tracker for dynamic pillarboxing + 3-second CTA overlay.

Key changes from v1:
- Pillarboxing via vision_tracker (MediaPipe → FFmpeg; no intermediate files)
- -pix_fmt yuv420p enforced for mobile compatibility
- Hardware acceleration detection (VideoToolbox on macOS, NVENC on NVIDIA)
- 3-second affiliate CTA overlay injected before encoding (Phase 4)
- All existing text overlays (subscribe, hook, bridge, captions) preserved
"""
import subprocess
import yt_dlp
import os
import sys
import re

# Import Phase 2 vision tracker (gracefully degrades if MediaPipe not installed)
try:
    from app import vision_tracker
    VISION_AVAILABLE = True
except ImportError:
    try:
        import vision_tracker
        VISION_AVAILABLE = True
    except ImportError:
        VISION_AVAILABLE = False


# ──────────────── Utility Functions — PRESERVED ───────────────────────────────

def wrap_text(text: str, max_width: int = 25) -> str:
    """Manually wrap text to fit in vertical video."""
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        if not current_line:
            current_line.append(word)
        elif len(" ".join(current_line + [word])) <= max_width:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return "\n".join(lines)

def clean_text(text: str) -> str:
    """Removes [Music], [Applause], and validates text for captions."""
    # Remove bracketed text like [Music]
    text = re.sub(r'\[.*?\]', '', text)
    # Remove non-alphanumeric/punctuation garbage
    text = re.sub(r'[^\w\s.,!?\'-]', '', text)
    text = text.strip()
    
    # If the remaining text has no letters, reject it
    if not re.search(r'[a-zA-Z]', text):
        return ""
        
    return text


def parse_time(time_str: str) -> float:
    """Converts MM:SS or HH:MM:SS or plain seconds string to float seconds."""
    try:
        parts = list(map(float, str(time_str).split(":")))
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return float(time_str)
    except Exception:
        return 0.0


# ──────────────── FFmpeg Binary Resolution ────────────────────────────────────

def _get_ffmpeg_bin() -> str:
    """Resolve the best available FFmpeg binary path."""
    script_dir   = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    local_bin    = os.path.join(project_root, "node_modules/@ffmpeg-installer/darwin-arm64/ffmpeg")
    if os.path.exists(local_bin):
        return local_bin
    return "ffmpeg"


def _has_filter(ffmpeg_bin: str, filter_name: str) -> bool:
    """Check if a specific FFmpeg filter is available."""
    try:
        result = subprocess.run([ffmpeg_bin, "-filters"], capture_output=True, text=True)
        return filter_name in result.stdout
    except Exception:
        return False


def _detect_hw_encoder(ffmpeg_bin: str) -> str:
    """
    Detect available hardware-accelerated encoder.
    Priority: VideoToolbox (macOS) → NVENC (NVIDIA) → libx264 (CPU fallback)
    """
    try:
        result = subprocess.run([ffmpeg_bin, "-encoders"], capture_output=True, text=True)
        encoders = result.stdout
        if "h264_videotoolbox" in encoders:
            print("Encoder: VideoToolbox (macOS HW acceleration)")
            return "h264_videotoolbox"
        if "h264_nvenc" in encoders:
            print("Encoder: NVENC (NVIDIA HW acceleration)")
            return "h264_nvenc"
    except Exception:
        pass
    print("Encoder: libx264 (CPU)")
    return "libx264"


# ──────────────── Downloader — PRESERVED ─────────────────────────────────────

def download_video_section(url: str, start_time, end_time, output_path: str, unused_key=None):
    """Download a full video using local yt-dlp. Start/end unused (full download for FFmpeg trim)."""
    print(f"Local Acquisition: Downloading {url}...")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": output_path,
        "force_keyframes_at_cuts": True,
        "nocheckcertificate": True,
        "socket_timeout": 120,
        "retries": 15,
        "extractor_args": {"youtube": {"player_client": ["android", "ios"]}},
    }

    for attempt in range(3):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            print(f"Downloaded to {output_path}")
            return
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                raise e


# ──────────────── Core Shorts Processor ───────────────────────────────────────

def process_for_shorts(input_path: str, output_path: str,
                       start_time: str, end_time: str,
                       bridge_text: str, hook_text: str = "",
                       transcript_raw: list = None,
                       cta_overlay_text: str = "Want this tool? Link in bio 👆",
                       affiliate_link: str = ""):
    """
    Full Shorts rendering pipeline:
    1. Subject-aware pillarboxing via MediaPipe (Phase 2)
    2. Thumbnail injection frame (0–0.1s high-saturation)
    3. Hook overlay (0–3s)
    4. Subscribe bug (permanent)
    5. Smart captions from transcript
    6. Bridge CTA overlay (last 4s)
    7. Affiliate CTA overlay (last 3s) — Phase 4
    8. Hardware-accelerated encoding with yuv420p
    """
    print(f"Video Processor: Cutting {start_time} → {end_time} and formatting for Shorts...")

    seg_start = parse_time(start_time)
    seg_end   = parse_time(end_time)
    duration  = seg_end - seg_start

    ffmpeg_bin  = _get_ffmpeg_bin()
    has_drawtext = _has_filter(ffmpeg_bin, "drawtext")
    video_encoder = _detect_hw_encoder(ffmpeg_bin)

    # ── Phase 2: Get subject-aware pillarbox base filter ─────────────────────
    if VISION_AVAILABLE:
        base_filter = vision_tracker.get_tracking_filter(input_path)
        print("Video Processor: Using subject-aware pillarbox filter.")
    else:
        base_filter = (
            "split[v1][v2];"
            "[v1]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=40:10[bg];"
            "[v2]scale=1080:-1[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
        print("Video Processor: Using static pillarbox (MediaPipe not available).")

    font_path = "/System/Library/Fonts/Supplemental/Verdana Bold.ttf"

    if has_drawtext:
        def escape(t: str) -> str:
            return t.replace("'", "\u2019").replace(":", "\\:")

        safe_hook   = escape(wrap_text(hook_text,   20))
        safe_bridge = escape(wrap_text(bridge_text, 25))
        safe_cta    = escape(wrap_text(cta_overlay_text, 22))

        # ── 1. THUMBNAIL INJECTION (0–0.1s) ──────────────────────────────────
        thumb_text = escape(wrap_text(hook_text.upper(), 15))
        thumb_filter = (
            f"drawtext=text='{thumb_text}':fontfile='{font_path}':"
            f"fontcolor=white:fontsize=75:line_spacing=20:"
            f"box=1:boxcolor=red@0.9:boxborderw=30:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"enable='between(t,0,0.1)'"
        )

        # ── 2. HOOK OVERLAY (0–3s, yellow, top zone) ─────────────────────────
        hook_filter = (
            f"drawtext=text='{safe_hook}':fontfile='{font_path}':"
            f"fontcolor=yellow:fontsize=56:"
            f"box=1:boxcolor=black@0.7:boxborderw=15:"
            f"x=(w-text_w)/2:y=200:"
            f"enable='between(t,0,3)'"
        )

        # ── 3. SUBSCRIBE BUG (permanent, elevated safe zone) ─────────────────
        sub_filter = (
            f"drawtext=text='SUBSCRIBE':fontfile='{font_path}':"
            f"fontcolor=white:fontsize=42:"
            f"box=1:boxcolor=red@0.9:boxborderw=10:"
            f"x=(w-text_w)/2:y=h-th-600"
        )

        # ── 4. BRIDGE CTA (last 4s) ───────────────────────────────────────────
        bridge_filter = (
            f"drawtext=text='{safe_bridge}':fontfile='{font_path}':"
            f"fontcolor=white:fontsize=42:"
            f"box=1:boxcolor=black@0.5:boxborderw=10:"
            f"x=(w-text_w)/2:y=h-th-150:"
            f"enable='between(t,{duration - 4},{duration})'"
        )

        # ── 5. AFFILIATE CTA OVERLAY (last 3s) — Phase 4 ─────────────────────
        cta_filter = (
            f"drawtext=text='{safe_cta}':fontfile='{font_path}':"
            f"fontcolor=yellow:fontsize=46:"
            f"box=1:boxcolor=black@0.85:boxborderw=12:"
            f"x=(w-text_w)/2:y=h-th-400:"
            f"enable='between(t,{duration - 3},{duration})'"
        )

        # ── 6. SMART CAPTIONS from transcript (above subscribe zone) ──────────
        caption_filters = []
        last_cap_end = 0.0

        if transcript_raw:
            for entry in transcript_raw:
                if isinstance(entry, dict):
                    e_start = entry.get("start", 0)
                    e_dur   = entry.get("duration", 0)
                    e_text  = entry.get("text", "")
                else:
                    e_start = getattr(entry, "start", 0)
                    e_dur   = getattr(entry, "duration", 0)
                    e_text  = getattr(entry, "text", "")

                e_end = e_start + e_dur

                if e_start >= seg_start and e_end <= seg_end:
                    rel_start = round(e_start - seg_start, 2)
                    rel_end   = round(e_end   - seg_start, 2)

                    # No overlap with previous caption
                    if rel_start < last_cap_end:
                        rel_start = last_cap_end + 0.05

                    # Cap caption display duration to 2.5s
                    if (rel_end - rel_start) > 2.5:
                        rel_end = rel_start + 2.5

                    last_cap_end = rel_end

                    cleaned_text = clean_text(e_text)
                    if not cleaned_text:
                        continue

                    txt = escape(wrap_text(
                        cleaned_text.replace("'", "").replace(":", "").upper(), 22
                    ))
                    if txt and len(txt) < 120:
                        cap_f = (
                            f"drawtext=text='{txt}':fontfile='{font_path}':"
                            f"fontcolor=white:fontsize=42:"
                            f"box=1:boxcolor=black@0.6:"
                            f"x=(w-text_w)/2:y=h-th-750:"
                            f"enable='between(t,{rel_start},{rel_end})'"
                        )
                        caption_filters.append(cap_f)

        # ── Assemble all overlay filters ──────────────────────────────────────
        all_overlays = (
            [thumb_filter, hook_filter, sub_filter, bridge_filter, cta_filter]
            + caption_filters[:35]  # Cap to prevent command-line overflow
        )
        overlay_chain = ",".join(all_overlays)

        # Compose the final complex filter:
        # base_filter produces the 1080x1920 pillarboxed frame,
        # then all text overlays are chained on top.
        video_filter = f"{base_filter},{overlay_chain}"

    else:
        print("WARNING: 'drawtext' not available. Skipping text overlays.")
        video_filter = base_filter

    # ── Build and Run FFmpeg Command ──────────────────────────────────────────
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss", str(seg_start),           # Seek before input for speed
        "-i", input_path,
        "-t", str(duration),
        "-vf", video_filter,
        "-c:v", video_encoder,
        "-pix_fmt", "yuv420p",            # Mobile compatibility (Phase 2 spec)
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",        # Web-optimized MP4 structure
        output_path,
    ]

    # VideoToolbox doesn't support all libx264 options — keep it clean
    if video_encoder == "h264_videotoolbox":
        cmd.insert(-1, "-q:v")
        cmd.insert(-1, "65")              # Quality factor for VideoToolbox

    print(f"Video Processor: Rendering with {video_encoder}...")
    subprocess.run(cmd, check=True)
    print(f"Video Processor: ✅ Output ready → {output_path}")


# ──────────────── SRT Generator — PRESERVED & EXTENDED ───────────────────────

def generate_srt(transcript_raw: list, start_time_str: str,
                 end_time_str: str, srt_path: str) -> bool:
    """
    Generates an SRT caption file for YouTube SEO auto-indexing.
    PRESERVED from v1 with robustness improvements.
    """
    seg_start = parse_time(start_time_str)
    seg_end   = parse_time(end_time_str)
    srt_content = ""
    counter = 1

    def format_srt_time(seconds: float) -> str:
        hrs, rem = divmod(seconds, 3600)
        mins, secs = divmod(rem, 60)
        millis = int((secs - int(secs)) * 1000)
        return f"{int(hrs):02d}:{int(mins):02d}:{int(secs):02d},{millis:03d}"

    for entry in transcript_raw:
        e_start = entry.get("start", 0) if isinstance(entry, dict) else getattr(entry, "start", 0)
        e_dur   = entry.get("duration", 0) if isinstance(entry, dict) else getattr(entry, "duration", 0)
        e_text  = entry.get("text", "") if isinstance(entry, dict) else getattr(entry, "text", "")
        e_end   = e_start + e_dur

        if e_start >= seg_start and e_end <= seg_end:
            r_start = e_start - seg_start
            r_end   = e_end   - seg_start
            srt_content += f"{counter}\n"
            srt_content += f"{format_srt_time(r_start)} --> {format_srt_time(r_end)}\n"
            srt_content += f"{e_text}\n\n"
            counter += 1

    if srt_content:
        with open(srt_path, "w") as f:
            f.write(srt_content)
        print(f"SRT: Generated {counter - 1} caption entries → {srt_path}")
        return True

    print("SRT: No matching transcript entries found for segment.")
    return False


# ──────────────── Orchestration Helper ────────────────────────────────────────

def create_short(url: str, start_time: str, end_time: str,
                 bridge_text: str, output_path: str,
                 hook_text: str = "", transcript_raw: list = None,
                 cta_overlay_text: str = "Want this tool? Link in bio 👆",
                 affiliate_link: str = "") -> str:
    """
    Orchestrates download + Shorts processing for a single clip.
    Returns the output_path on success.
    """
    raw_path = "/tmp/full_video.mp4"

    # Clean up previous artifacts
    for p in [raw_path, output_path]:
        if os.path.exists(p):
            os.remove(p)

    download_video_section(url, "0", "0", raw_path)
    process_for_shorts(
        raw_path, output_path,
        start_time, end_time,
        bridge_text, hook_text,
        transcript_raw,
        cta_overlay_text,
        affiliate_link,
    )

    return output_path
