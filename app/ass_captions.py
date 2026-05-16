"""
ass_captions.py — premium caption file generation for FFmpeg subtitles.

The first implementation uses transcript phrase timing, splits long chunks into
short beats, and highlights power words. It is ready to be upgraded later with
Whisper/WhisperX word-level timestamps.
"""
import os
import re
import tempfile
from typing import Dict, List

try:
    from app import visual_retention
except ImportError:
    import visual_retention


def _clean(text: str) -> str:
    text = re.sub(r"\[.*?\]", "", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _entry_start(entry) -> float:
    return float(entry.get("start", 0) if isinstance(entry, dict) else getattr(entry, "start", 0))


def _entry_duration(entry) -> float:
    return float(entry.get("duration", 0) if isinstance(entry, dict) else getattr(entry, "duration", 0))


def _entry_text(entry) -> str:
    return str(entry.get("text", "") if isinstance(entry, dict) else getattr(entry, "text", ""))


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int((seconds - int(seconds)) * 100)
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("{", "").replace("}", "").replace("\\", "")


def _split_beats(text: str, max_words: int = 4) -> List[str]:
    words = text.split()
    beats = []
    current = []
    for word in words:
        current.append(word)
        end_punct = bool(re.search(r"[.!?]$", word))
        if len(current) >= max_words or (end_punct and len(current) >= 3):
            beats.append(" ".join(current))
            current = []
    if current:
        beats.append(" ".join(current))
    return beats


def _wrap_caption(text: str, max_chars: int = 14) -> str:
    words = text.split()
    if not words:
        return ""
    lines = []
    current = []
    for word in words:
        candidate = " ".join(current + [word])
        if current and len(candidate) > max_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    if len(lines) <= 2:
        return "\\N".join(lines)

    best_split = 1
    best_score = float("inf")
    for split_at in range(1, len(words)):
        left = " ".join(words[:split_at])
        right = " ".join(words[split_at:])
        overflow = max(0, len(left) - max_chars) + max(0, len(right) - max_chars)
        balance = abs(len(left) - len(right))
        score = overflow * 10 + balance
        if score < best_score:
            best_score = score
            best_split = split_at
    return "\\N".join([
        " ".join(words[:best_split]),
        " ".join(words[best_split:]),
    ])


def _highlight(text: str, accent_color: str, primary_color: str) -> str:
    power_words = visual_retention.keyword_set_for_text(text)
    highlighted_lines = []
    for line in text.split("\\N"):
        pieces = []
        tokens = re.split(r"(\s+)", line)
        for token in tokens:
            clean = re.sub(r"[^a-zA-Z0-9%$]", "", token).lower()
            escaped = _ass_escape(token)
            if token.isspace():
                pieces.append(token)
                continue
            if clean in power_words or re.search(r"\d|%|\$", clean):
                pieces.append(
                    r"{\c" + accent_color + r"\b1}" + escaped
                    + r"{\c" + primary_color + r"\b1}"
                )
            else:
                pieces.append(escaped)
        highlighted_lines.append("".join(pieces))
    return "\\N".join(highlighted_lines)


def _caption_entries(transcript_raw: List[dict], seg_start: float, seg_end: float) -> List[Dict]:
    entries = []
    for entry in transcript_raw or []:
        start = _entry_start(entry)
        duration = _entry_duration(entry)
        end = start + duration
        if start >= seg_start and end <= seg_end:
            text = _clean(_entry_text(entry))
            if not text:
                continue
            entries.append({
                "start": max(0.0, start - seg_start),
                "end": max(0.0, end - seg_start),
                "text": text,
            })
    return entries


def generate_ass(transcript_raw: List[dict], seg_start: float, seg_end: float,
                 visual_plan: Dict = None) -> str:
    visual_plan = visual_plan or {}
    style = visual_plan.get("caption_style_pack", {})
    primary = style.get("caption_primary", "&H00FFFFFF")
    accent = style.get("caption_accent", "&H0000FFFF")
    outline = style.get("caption_outline", "&H00000000")
    font_size = int(style.get("font_size", 70))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Verdana,{font_size},{primary},{accent},{outline},&H99000000,1,0,0,0,100,100,0,0,1,5,2,2,90,90,285,1
Style: CaptionHigh,Verdana,{font_size},{primary},{accent},{outline},&H99000000,1,0,0,0,100,100,0,0,1,5,2,2,90,90,650,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    beat_candidates = []
    cta_start = float(visual_plan.get("cta_start", -1) or -1)
    cta_end = float(visual_plan.get("cta_end", -1) or -1)
    cta_quiet_start = cta_start - 0.35 if cta_start >= 0 else -1
    cta_quiet_end = cta_end + 0.35 if cta_end >= 0 else -1

    caption_items = _caption_entries(transcript_raw, seg_start, seg_end)
    for entry_index, item in enumerate(caption_items):
        beats = _split_beats(item["text"], max_words=4)
        if not beats:
            continue
        next_start = (
            caption_items[entry_index + 1]["start"]
            if entry_index + 1 < len(caption_items)
            else item["end"]
        )
        # Transcript sources often use rolling two-line captions. The current
        # line can remain visible after the next line starts, so the next line's
        # start is a better estimate of when this phrase has finished speaking.
        timing_end = item["end"]
        if item["start"] + 0.35 < next_start < item["end"]:
            timing_end = next_start
        total = max(timing_end - item["start"], len(item["text"].split()) * 0.18, 0.55)
        word_count = max(1, len(item["text"].split()))
        words_seen = 0
        for idx, beat in enumerate(beats):
            beat_words = max(1, len(beat.split()))
            natural_start = item["start"] + (words_seen / word_count) * total
            natural_end = item["start"] + ((words_seen + beat_words) / word_count) * total
            words_seen += beat_words
            natural_end = min(item["end"], max(natural_start + 0.36, natural_end))
            beat_candidates.append({
                "entry_index": entry_index,
                "beat_index": idx,
                "natural_start": natural_start,
                "natural_end": natural_end,
                "beat": beat,
            })

    # YouTube transcript chunks can be "rolling" captions: timestamps overlap, but
    # the text is still sequential. Preserve transcript order before timing so
    # dense speech compresses instead of jumbling or dropping words.
    beat_candidates.sort(key=lambda item: (
        item["entry_index"],
        item["beat_index"],
        item["natural_start"],
    ))

    events = []
    last_end = -0.2
    normal_gap = 0.12
    dense_gap = 0.04
    normal_display = 1.08
    dense_display = 0.74
    min_display = 0.42

    for candidate in beat_candidates:
        natural_start = candidate["natural_start"]
        natural_end = candidate["natural_end"]
        lag = max(0.0, last_end - natural_start)
        min_gap = dense_gap if lag > 0.35 else normal_gap
        max_display = dense_display if lag > 0.35 else normal_display

        start = max(natural_start, last_end + min_gap)
        end = min(natural_end, start + max_display)
        if end - start < min_display:
            end = start + min_display
        clip_duration = max(0.0, float(seg_end) - float(seg_start))
        if clip_duration and start >= clip_duration - 0.2:
            continue
        if clip_duration and end > clip_duration:
            end = clip_duration
        if end - start < min_display - 1e-6:
            continue
        if start < last_end + min_gap:
            continue

        beat = candidate["beat"]
        last_end = end
        style_name = "CaptionHigh" if (
            cta_start >= 0 and start < cta_quiet_end and end > cta_quiet_start
        ) else "Caption"

        wrapped = _wrap_caption(beat.upper(), max_chars=14)
        highlighted = _highlight(wrapped, accent, primary)
        line_count = wrapped.count("\\N") + 1
        longest_line = max(len(line) for line in wrapped.split("\\N"))
        size_guard = r"{\fs48}" if longest_line > 14 or line_count > 1 else ""
        text = (
            r"{\q2\fad(70,70)\t(0,100,\fscx103\fscy103)"
            r"\t(100,190,\fscx100\fscy100)}"
            + size_guard
            + highlighted
        )
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style_name},,0,0,0,,{text}"
        )

    fd, path = tempfile.mkstemp(suffix=".ass", prefix="shorts_captions_")
    with os.fdopen(fd, "w") as handle:
        handle.write(header)
        handle.write("\n".join(events))
        handle.write("\n")
    return path


def escape_subtitles_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
