"""
content_scorer.py — Evidence-backed viral candidate ranking.

This module gives the LLM a stronger starting point by scoring transcript
windows before prompt generation. It is intentionally deterministic and local:
the LLM still handles narrative packaging, but it no longer has to discover
candidate moments from a blank transcript alone.
"""
import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Dict, List

import yt_dlp


POWER_TERMS = {
    "money", "million", "billion", "secret", "mistake", "never", "always",
    "truth", "wrong", "fail", "win", "growth", "rich", "poor", "ai",
    "automation", "business", "startup", "sales", "revenue", "profit",
    "risk", "opportunity", "market", "customers", "attention", "viral",
}

CONTRADICTION_TERMS = {
    "but", "however", "instead", "actually", "wrong", "opposite", "ignore",
    "stop", "nobody", "myth", "lie", "fake", "trap", "paradox",
}

VALUE_TERMS = {
    "how", "why", "because", "learn", "step", "framework", "rule",
    "system", "strategy", "exactly", "simple", "fast", "best",
}

PAIN_TERMS = {
    "problem", "struggle", "hard", "expensive", "slow", "waste", "manual",
    "confused", "stuck", "lost", "broke", "panic", "fear", "failure",
}


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


def _parse_upload_age_hours(upload_date: str) -> float:
    if not upload_date:
        return 0.0
    try:
        published = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - published).total_seconds() / 3600.0, 1.0)
    except Exception:
        return 0.0


def collect_source_metadata(video_url: str) -> Dict:
    """
    Pull lightweight source metadata with yt-dlp.

    The score intentionally favors velocity and engagement density over raw
    view count so smaller but fast-moving videos can still enter the queue.
    """
    opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    metadata = {"url": video_url}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception as exc:
        metadata["error"] = str(exc)
        return metadata

    view_count = _safe_int(info.get("view_count"))
    like_count = _safe_int(info.get("like_count"))
    comment_count = _safe_int(info.get("comment_count"))
    age_hours = _parse_upload_age_hours(info.get("upload_date"))
    views_per_hour = view_count / age_hours if age_hours else 0.0
    engagement_rate = ((like_count + comment_count * 2) / max(view_count, 1)) * 100.0

    velocity_score = min(40.0, math.log10(max(views_per_hour, 1)) * 10.0)
    engagement_score = min(30.0, engagement_rate * 10.0)
    authority_score = min(30.0, math.log10(max(view_count, 1)) * 4.0)

    metadata.update({
        "id": info.get("id", ""),
        "title": info.get("title", ""),
        "channel_id": info.get("channel_id", ""),
        "channel": info.get("channel", ""),
        "duration": _safe_float(info.get("duration")),
        "view_count": view_count,
        "like_count": like_count,
        "comment_count": comment_count,
        "age_hours": age_hours,
        "views_per_hour": views_per_hour,
        "engagement_rate": engagement_rate,
        "velocity_score": round(velocity_score + engagement_score, 2),
        "authority_score": round(authority_score, 2),
        "source_score": round(velocity_score + engagement_score + authority_score, 2),
    })
    return metadata


def _entry_text(entry) -> str:
    if isinstance(entry, dict):
        return str(entry.get("text", "") or "")
    return str(getattr(entry, "text", "") or "")


def _entry_start(entry) -> float:
    if isinstance(entry, dict):
        return _safe_float(entry.get("start"))
    return _safe_float(getattr(entry, "start", 0))


def _entry_duration(entry) -> float:
    if isinstance(entry, dict):
        return _safe_float(entry.get("duration"))
    return _safe_float(getattr(entry, "duration", 0))


def _seconds_to_mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _min_distance_from_used(start: float, end: float, used_segments: List[dict]) -> float:
    if not used_segments:
        return 9999.0
    distances = []
    for seg in used_segments:
        s = _safe_float(seg.get("Start_Time", seg.get("start", 0)))
        e = _safe_float(seg.get("End_Time", seg.get("end", 0)))
        if _overlap(start, end, s, e) > 0:
            return 0.0
        distances.append(min(abs(start - e), abs(s - end)))
    return min(distances) if distances else 9999.0


def _score_text(text: str) -> Dict:
    clean = re.sub(r"\s+", " ", text).strip()
    lower = clean.lower()
    words = re.findall(r"[a-zA-Z0-9%$]+", lower)
    word_count = len(words)
    unique_words = len(set(words))
    numbers = len(re.findall(r"(\d+|%|\$)", clean))
    question_marks = clean.count("?")
    uppercase_entities = len(re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", clean))

    power_hits = sum(1 for w in words if w in POWER_TERMS)
    contradiction_hits = sum(1 for w in words if w in CONTRADICTION_TERMS)
    value_hits = sum(1 for w in words if w in VALUE_TERMS)
    pain_hits = sum(1 for w in words if w in PAIN_TERMS)
    second_person = len(re.findall(r"\b(you|your|yours|yourself)\b", lower))

    density = unique_words / max(word_count, 1)
    duration_fit = 1.0 if 80 <= word_count <= 150 else max(0.0, 1.0 - abs(word_count - 115) / 115.0)

    score = 0.0
    score += min(18.0, power_hits * 2.0)
    score += min(16.0, contradiction_hits * 3.0)
    score += min(12.0, value_hits * 1.5)
    score += min(12.0, pain_hits * 2.0)
    score += min(10.0, numbers * 3.0)
    score += min(8.0, question_marks * 4.0)
    score += min(8.0, second_person * 1.5)
    score += min(6.0, uppercase_entities * 0.75)
    score += density * 6.0
    score += duration_fit * 10.0

    return {
        "score": round(score, 2),
        "word_count": word_count,
        "numbers": numbers,
        "questions": question_marks,
        "power_hits": power_hits,
        "contradiction_hits": contradiction_hits,
        "value_hits": value_hits,
        "pain_hits": pain_hits,
        "second_person_hits": second_person,
        "lexical_density": round(density, 3),
        "duration_fit": round(duration_fit, 3),
    }


def build_ranked_candidates(transcript_raw: List[dict], parent_url: str,
                            source_metadata: Dict = None,
                            used_segments: List[dict] = None,
                            window_seconds: int = 52,
                            stride_seconds: int = 18,
                            limit: int = 8) -> List[Dict]:
    """
    Build overlapping candidate windows and rank them with deterministic signals.
    """
    if not transcript_raw:
        return []

    entries = sorted(transcript_raw, key=_entry_start)
    first_start = _entry_start(entries[0])
    last_end = max(_entry_start(e) + _entry_duration(e) for e in entries)
    used_segments = used_segments or []
    source_metadata = source_metadata or {}
    source_score = _safe_float(source_metadata.get("source_score", 0.0))

    candidates = []
    cursor = first_start
    while cursor + 30 <= last_end:
        start = cursor
        end = min(cursor + window_seconds, last_end)
        window_entries = [
            e for e in entries
            if _entry_start(e) < end and (_entry_start(e) + _entry_duration(e)) > start
        ]
        text = " ".join(_entry_text(e).strip() for e in window_entries if _entry_text(e).strip())
        if len(text.split()) < 35:
            cursor += stride_seconds
            continue

        text_score = _score_text(text)
        distance = _min_distance_from_used(start, end, used_segments)
        novelty_score = 0.0 if distance == 0 else min(20.0, distance / 3.0)
        transcript_score = text_score["score"]
        virality_score = transcript_score + min(25.0, source_score * 0.25) + novelty_score

        concept_terms = [
            w for w in re.findall(r"[A-Za-z]{4,}", text.lower())
            if w in POWER_TERMS or w in VALUE_TERMS or w in PAIN_TERMS
        ]
        topic = ", ".join(dict.fromkeys(concept_terms[:4])) or "general insight"
        candidate_id = hashlib.sha1(f"{parent_url}:{start:.2f}:{end:.2f}".encode()).hexdigest()[:16]

        candidates.append({
            "candidate_id": candidate_id,
            "parent_url": parent_url,
            "start": round(start, 2),
            "end": round(end, 2),
            "start_time": _seconds_to_mmss(start),
            "end_time": _seconds_to_mmss(end),
            "duration": round(end - start, 2),
            "topic": topic,
            "summary_text": text[:650],
            "virality_score": round(virality_score, 2),
            "transcript_score": round(transcript_score, 2),
            "source_score": round(source_score, 2),
            "novelty_score": round(novelty_score, 2),
            "features": text_score,
            "status": "ranked",
        })
        cursor += stride_seconds

    candidates.sort(key=lambda item: item["virality_score"], reverse=True)

    # Keep candidates diverse by requiring some distance between selected windows.
    selected = []
    for candidate in candidates:
        if all(_overlap(candidate["start"], candidate["end"], c["start"], c["end"]) < 12 for c in selected):
            selected.append(candidate)
        if len(selected) >= limit:
            break

    return selected


def candidates_for_prompt(candidates: List[Dict]) -> str:
    if not candidates:
        return ""
    lines = []
    for idx, item in enumerate(candidates, 1):
        features = item.get("features", {})
        lines.append(
            f"{idx}. {item['start_time']}–{item['end_time']} | "
            f"score={item['virality_score']} | topic={item.get('topic', '')} | "
            f"signals=power:{features.get('power_hits', 0)}, "
            f"contrarian:{features.get('contradiction_hits', 0)}, "
            f"value:{features.get('value_hits', 0)}, pain:{features.get('pain_hits', 0)} | "
            f"text={item.get('summary_text', '')[:280]}"
        )
    return "\n".join(lines)


def find_matching_candidate(task: Dict, candidates: List[Dict]) -> Dict:
    """Return the ranked candidate with the strongest timestamp overlap."""
    if not candidates:
        return {}

    def parse(value: str) -> float:
        parts = str(value).split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            return float(value)
        except Exception:
            return 0.0

    start = parse(task.get("start_time", 0))
    end = parse(task.get("end_time", 0))
    best = {}
    best_overlap = 0.0
    for candidate in candidates:
        overlap = _overlap(start, end, candidate["start"], candidate["end"])
        if overlap > best_overlap:
            best = candidate
            best_overlap = overlap
    return best
